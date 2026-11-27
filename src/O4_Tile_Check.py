"""Checks of a freshly built DSF, run at the end of step 3 (#157).

Each check stands for a bug class that once reached built tiles without
any error: they were found only by measuring the output.
  hubs      one point shared by many triangles (#155: a 65,000-triangle
            fan around one vertex)
  density   triangles in one 0.001 x 0.001 degree cell (#154/#155)
  uv        a texture UV that is not where its point lies in the tile's
            Web Mercator texture (#146), the same for the mask UVs, and
            UVs outside [0, 1]
  files     terrain files and the textures they name, missing in the tile
  nan       NaN or infinity in a pool
No check of triangle size: Triangle4XP refines by terrain curvature only,
so flat ground (airports built flat, lakes, sea-level flats) rightly gets
triangles as large as a texture square, and a triangle past its texture's
edge already shows as a UV outside [0, 1].
A problem is logged as a WARNING naming the place; the tile is still
built (the DSF is fine to load, only parts of it may look wrong). The
result is also written to the tile's check file, so a batch can list the
warnings of its worker processes in its summary.

The DSF is read directly from its binary atoms; nothing here may raise
into step 3.
"""
import os
import re
import struct
import time

import numpy

import O4_File_Names as FNAMES
import O4_UI_Utils as UI

LIMITS = {
    "hub_max": 400,      # triangles at one point (lake fans reach ~100)
    "density_max": 6000,  # triangles in a 0.001 degree cell
    "uv_bad": 0,
    "mask_uv_bad": 0,
    "uv_range": 0,
    "missing_files": 0,
    "nan": 0,
}
# 16-bit DSF positions are coarser than a ZL18 texel at high latitudes
# (82 N: up to ~2 texels, 17 cm); #146 was hundreds of texels off.
UV_TEXELS = 4
TEX_KEYS = ("BASE_TEX", "BASE_TEX_NOWRAP", "TEXTURE", "TEXTURE_NOWRAP",
            "BORDER_TEX", "NORMAL_TEX")
# terrain/<til_y>_<til_x>_<provider><zl>[_suffix].ter
TER_NAME = re.compile(
    r"terrain/(\d+)_(\d+)_([A-Za-z0-9]+?)(\d\d)(_\w+)?\.ter$")
OK = "ok"


# --- DSF reader -------------------------------------------------------------
def _atoms(buf, start, end):
    pos = start
    while pos + 8 <= end:
        (aid, size) = struct.unpack_from("<4sI", buf, pos)
        if size < 8 or pos + size > end:
            raise ValueError(f"bad atom size {size} at {pos}")
        yield (aid[::-1], pos + 8, pos + size)
        pos += size


def _decode_plane(buf, pos, n):
    """One 16-bit plane of a pool: (values as int64, next position).
    Encodings: 0 raw, 1 differenced, 2 run-length, 3 both."""
    enc = buf[pos]
    pos += 1
    if enc in (0, 1):
        vals = numpy.frombuffer(buf, "<u2", n, pos).astype(numpy.int64)
        pos += 2 * n
    elif enc in (2, 3):
        vals = numpy.empty(n, numpy.int64)
        i = 0
        while i < n:
            head = buf[pos]
            pos += 1
            cnt = head & 0x7F
            if cnt == 0 or i + cnt > n:
                raise ValueError("bad run in a pool plane")
            if head & 0x80:
                vals[i:i + cnt] = struct.unpack_from("<H", buf, pos)[0]
                pos += 2
            else:
                vals[i:i + cnt] = numpy.frombuffer(buf, "<u2", cnt, pos)
                pos += 2 * cnt
            i += cnt
    else:
        raise ValueError(f"unknown plane encoding {enc}")
    if enc in (1, 3):
        vals = numpy.cumsum(vals) % 65536
    return vals, pos


def read_dsf(path):
    """(terrain names, pools, buffer, (start, end) of the commands).

    Each pool is (lonlat float64 (n, 2), planes 5-8 float32 (n, 4)):
    only what the checks need, to keep a big tile's memory low. Planes
    a pool does not have are 0.
    """
    with open(path, "rb") as f:
        buf = f.read()
    if buf[:8] != b"XPLNEDSF":
        raise ValueError("not a plain DSF")
    end = len(buf) - 16  # MD5 footer
    (terrains, raw, scals, cmds) = ([], [], [], None)
    for (aid, s, e) in _atoms(buf, 12, end):
        if aid == b"DEFN":
            for (sid, ss, se) in _atoms(buf, s, e):
                if sid == b"TERT":
                    terrains = buf[ss:se].decode("latin-1").split("\0")[:-1]
        elif aid == b"GEOD":
            # only 16-bit pools (POOL/SCAL) carry patches; the 32-bit ones
            # are for vectors
            for (sid, ss, se) in _atoms(buf, s, e):
                if sid == b"POOL":
                    raw.append(ss)
                elif sid == b"SCAL":
                    scals.append(numpy.frombuffer(buf, "<f4", (se - ss) // 4,
                                                  ss))
        elif aid == b"CMDS":
            cmds = (s, e)
    if cmds is None:
        raise ValueError("no CMDS atom")
    pools = []
    for (ss, sc) in zip(raw, scals):
        (n, planes) = struct.unpack_from("<IB", buf, ss)
        pos = ss + 5
        lonlat = numpy.zeros((n, 2), numpy.float64)
        uv = numpy.zeros((n, 4), numpy.float32)
        for p in range(planes):
            (v, pos) = _decode_plane(buf, pos, n)
            (scale, off) = (float(sc[2 * p]), float(sc[2 * p + 1]))
            if p < 2:
                lonlat[:, p] = v / 65535.0 * scale + off if scale else v + off
            elif 5 <= p <= 8:
                uv[:, p - 5] = v / 65535.0 * scale + off if scale else v + off
        pools.append((lonlat, uv))
    return terrains, pools, buf, cmds


def _expand(kind, pairs):
    """Triangles (k, 3, 2) of (pool, index) from a triangle list (0), a
    strip (3) or a fan (6)."""
    n = len(pairs)
    if kind == 0:
        return pairs[: n - n % 3].reshape(-1, 3, 2)
    if n < 3:
        return numpy.empty((0, 3, 2), numpy.int32)
    if kind == 3:
        t = numpy.stack([pairs[:-2], pairs[1:-1], pairs[2:]], 1)
        t[1::2, [1, 2]] = t[1::2, [2, 1]]
        return t
    return numpy.stack(
        [numpy.repeat(pairs[:1], n - 2, 0), pairs[1:-1], pairs[2:]], 1)


# bytes to skip after the command byte, for commands without triangles
_SKIP = {2: 4, 6: 1, 7: 2, 8: 4, 10: 4, 13: 6}


def read_patches(buf, cmds, offs):
    """{(terrain index, patch flag): (k, 3) int32 point ids}: a point id
    counts over all pools, offs[pool] is the id of a pool's first point."""
    out = {}
    npools = len(offs) - 1

    def add(kind, pairs):
        if len(pairs) and (pairs[:, 0] >= npools).any():
            raise ValueError("a patch names a missing pool")
        t = _expand(kind, pairs)
        g = (offs[t[..., 0]] + t[..., 1]).astype(numpy.int32)
        out.setdefault((terrain, flag), []).append(g)
    (pos, end) = cmds
    (pool, terrain, flag) = (0, None, 1)
    u16 = struct.Struct("<H")
    while pos < end:
        c = buf[pos]
        pos += 1
        if c == 1:
            pool = u16.unpack_from(buf, pos)[0]
            pos += 2
        elif c in _SKIP:
            pos += _SKIP[c]
        elif c == 3:
            terrain = buf[pos]
            pos += 1
        elif c == 4:
            terrain = u16.unpack_from(buf, pos)[0]
            pos += 2
        elif c == 5:
            terrain = struct.unpack_from("<I", buf, pos)[0]
            pos += 4
        elif c == 9:
            pos += 1 + 2 * buf[pos]
        elif c == 11:
            pos += 1 + 4 * buf[pos]
        elif c == 12:
            pos += 2
            pos += 1 + 2 * buf[pos]
        elif c == 14:
            pos += 2
            n = buf[pos]
            pos += 1
            for _ in range(n):
                pos += 1 + 2 * buf[pos]
        elif c == 15:
            pos += 2
            pos += 1 + 2 * (buf[pos] + 1)
        elif c == 16:
            flag = 1
        elif c == 17:
            flag = buf[pos]
            pos += 1
        elif c == 18:
            flag = buf[pos]
            pos += 9
        elif c in (23, 26, 29):
            n = buf[pos]
            pos += 1
            idx = numpy.frombuffer(buf, "<u2", n, pos).astype(numpy.int32)
            pos += 2 * n
            add(c - 23, numpy.stack([numpy.full(n, pool, numpy.int32), idx], 1))
        elif c in (24, 27, 30):
            n = buf[pos]
            pos += 1
            pairs = numpy.frombuffer(buf, "<u2", 2 * n, pos).astype(
                numpy.int32).reshape(n, 2)
            pos += 4 * n
            add(c - 24, pairs)
        elif c in (25, 28, 31):
            (a, b) = struct.unpack_from("<HH", buf, pos)
            pos += 4
            idx = numpy.arange(a, b, dtype=numpy.int32)
            add(c - 25, numpy.stack(
                [numpy.full(len(idx), pool, numpy.int32), idx], 1))
        elif c == 32:
            pos += 1 + buf[pos]
        elif c == 33:
            pos += 2 + u16.unpack_from(buf, pos)[0]
        elif c == 34:
            pos += 4 + struct.unpack_from("<I", buf, pos)[0]
        else:
            raise ValueError(f"unknown DSF command {c} at {pos - 1}")
    return {k: numpy.concatenate(v) for (k, v) in out.items()}


# --- checks -----------------------------------------------------------------
def _merc_texels(lon, lat, zl):
    """Global Web Mercator pixel position at zoom level zl."""
    s = numpy.sin(numpy.radians(lat))
    gx = (lon + 180) / 360 * 2 ** zl * 256
    gy = (0.5 - numpy.log((1 + s) / (1 - s)) / (4 * numpy.pi)) * 2 ** zl * 256
    return gx, gy


def _at(lat, lon):
    return f"{float(lat):.5f}, {float(lon):.5f}"


def check_dsf(path, tile_dir=None):
    """The numbers of every check, with where the worst case lies.
    Raises on an unreadable DSF (check_tile turns it into a warning)."""
    (terrains, pools, buf, cmds) = read_dsf(path)
    offs = numpy.cumsum([0] + [len(ll) for (ll, _) in pools])
    patches = read_patches(buf, cmds, offs)
    del buf
    if pools:
        lonlat = numpy.concatenate([ll for (ll, _) in pools])
        uvs = numpy.concatenate([uv for (_, uv) in pools])
    else:
        lonlat = numpy.zeros((0, 2))
        uvs = numpy.zeros((0, 4), numpy.float32)
    del pools
    (lon, lat) = (lonlat[:, 0], lonlat[:, 1])
    res = {"nan": int((~numpy.isfinite(lonlat)).sum()
                      + (~numpy.isfinite(uvs)).sum())}
    phys = []
    (uv_bad, mask_bad, uv_range) = (0, 0, 0)
    worst = (0.0, None)
    for ((ter, flag), g) in patches.items():
        name = terrains[ter] if ter is not None and ter < len(terrains) else ""
        sea = name.endswith("_sea.ter")
        if flag == 1:
            phys.append(g)
        m = TER_NAME.match(name)
        if not m:
            continue
        v = numpy.unique(g.ravel())
        (ty, tx, zl) = (int(m.group(1)), int(m.group(2)), int(m.group(4)))
        (gx, gy) = _merc_texels(lon[v], lat[v], zl)
        # XP12 sea terrains: planes 5-6 are water parameters, the texture
        # UV is in planes 7-8
        (u, w) = (uvs[v, 2], uvs[v, 3]) if sea else (uvs[v, 0], uvs[v, 1])
        err = numpy.maximum(abs((gx - tx * 256) / 4096 - u),
                            abs((1 - (gy - ty * 256) / 4096) - w)) * 4096
        uv_bad += int((err > UV_TEXELS).sum())
        uv_range += int(((u < -1e-6) | (u > 1 + 1e-6)
                         | (w < -1e-6) | (w > 1 + 1e-6)).sum())
        if err.size and err.max() > worst[0]:
            i = int(err.argmax())
            worst = (float(err[i]), (name, _at(lat[v][i], lon[v][i])))
        if flag == 2 and not sea:
            # border_tex mask: build_dsf repeats the texture UV in planes
            # 7-8; constant planes are the ratio_water overlays
            (u2, w2) = (uvs[v, 2], uvs[v, 3])
            if u2.std() > 1e-6 or w2.std() > 1e-6:
                mask_bad += int((numpy.maximum(abs(u2 - u), abs(w2 - w))
                                 * 4096 > UV_TEXELS).sum())
    res.update(uv_bad=uv_bad, mask_uv_bad=mask_bad, uv_range=uv_range,
               uv_worst=worst)
    del patches
    T = numpy.concatenate(phys) if phys else numpy.zeros((0, 3), numpy.int32)
    del phys
    res["triangles"] = len(T)
    if len(T):
        # one place lies in several pools: count by position
        key = (numpy.round(lon * 1e7).astype(numpy.int64) * 4_000_000_000
               + numpy.round(lat * 1e7).astype(numpy.int64))
        (_, inv) = numpy.unique(key, return_inverse=True)
        del key
        cnt = numpy.bincount(inv[T.ravel()], minlength=1)
        h = int(cnt.argmax())
        hv = int(numpy.nonzero(inv == h)[0][0])
        res["hub_max"] = int(cnt[h])
        res["hub_at"] = _at(lat[hv], lon[hv])
        res["hubs_over"] = int((cnt > LIMITS["hub_max"]).sum())
        del inv, cnt
        # centroids without a (k, 3) temporary
        cx = (lon[T[:, 0]] + lon[T[:, 1]] + lon[T[:, 2]]) / 3
        cy = (lat[T[:, 0]] + lat[T[:, 1]] + lat[T[:, 2]]) / 3
        cell = (numpy.floor(cx * 1000).astype(numpy.int64) * 1_000_000
                + numpy.floor(cy * 1000).astype(numpy.int64))
        (uc, cc) = numpy.unique(cell, return_counts=True)
        k = int(cc.argmax())
        res["density_max"] = int(cc[k])
        res["density_at"] = _at((uc[k] % 1_000_000) / 1000 + 0.0005,
                                (uc[k] // 1_000_000) / 1000 + 0.0005)
        del cell, uc, cc
    if tile_dir:
        missing = _missing_files(terrains, tile_dir)
        res["missing_files"] = len(missing)
        res["missing_examples"] = missing[:3]
    return res


def _missing_files(terrains, tile_dir):
    missing = set()
    for name in terrains:
        if not name.startswith("terrain/"):
            continue
        ter = os.path.join(tile_dir, name)
        if not os.path.isfile(ter):
            missing.add(name)
            continue
        with open(ter, encoding="latin-1") as f:
            for line in f:
                p = line.split()
                if (len(p) >= 2 and p[0] in TEX_KEYS
                        and not p[-1].startswith("lib/")):
                    tex = os.path.normpath(
                        os.path.join(os.path.dirname(ter), p[-1]))
                    if not os.path.isfile(tex):
                        missing.add(os.path.relpath(tex, tile_dir)
                                    .replace("\\", "/"))
    return sorted(missing)


def warnings_of(res):
    """One line per check over its limit, naming the place."""
    out = []
    if res.get("hub_max", 0) > LIMITS["hub_max"]:
        out.append(f"{res['hub_max']} triangles meet at one point "
                   f"({res['hub_at']}); {res['hubs_over']} point(s) over "
                   f"{LIMITS['hub_max']}")
    if res.get("density_max", 0) > LIMITS["density_max"]:
        out.append(f"{res['density_max']} triangles in one 0.001 degree "
                   f"cell ({res['density_at']})")
    if res.get("uv_bad", 0) > LIMITS["uv_bad"]:
        (err, (name, at)) = res["uv_worst"]
        out.append(f"{res['uv_bad']} texture coordinate(s) off by more than "
                   f"{UV_TEXELS} texels, worst {err:.0f} in {name} ({at})")
    if res.get("mask_uv_bad", 0) > LIMITS["mask_uv_bad"]:
        out.append(f"{res['mask_uv_bad']} mask coordinate(s) off by more "
                   f"than {UV_TEXELS} texels")
    if res.get("uv_range", 0) > LIMITS["uv_range"]:
        out.append(f"{res['uv_range']} texture coordinate(s) outside 0-1")
    if res.get("missing_files", 0) > LIMITS["missing_files"]:
        out.append(f"{res['missing_files']} terrain or texture file(s) "
                   f"missing, e.g. {', '.join(res['missing_examples'])}")
    if res.get("nan", 0) > LIMITS["nan"]:
        out.append(f"{res['nan']} NaN or infinite value(s) in the DSF")
    return out


def check_tile(build_dir, lat, lon):
    """Check a tile's DSF after step 3; log and return its warnings.

    Never raises: a check that cannot run is itself reported, and the tile
    stays built either way.
    """
    tile = FNAMES.short_latlon(lat, lon)
    t0 = time.time()
    try:
        res = check_dsf(FNAMES.dsf_file(build_dir, lat, lon), build_dir)
        warnings = warnings_of(res)
    except MemoryError:
        warnings = ["not enough memory to check the DSF"]
    except Exception as e:  # a DSF the checks cannot read is a finding too
        warnings = [f"the DSF could not be read back ({type(e).__name__}: "
                    f"{e})"]
    for w in warnings:
        UI.lvprint(0, f"WARNING: tile check {tile}: {w}")
    if warnings:
        UI.lvprint(0, f"   The tile {tile} is built; look at the places above "
                   "before using it.")
    else:
        UI.vprint(1, f"   Tile check: ok ({time.time() - t0:.1f} s).")
    _write_result(build_dir, lat, lon, warnings)
    return warnings


def _write_result(build_dir, lat, lon, warnings):
    path = FNAMES.tile_check_file(build_dir, lat, lon)
    tmp = FNAMES.temp_path_for(path)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(warnings) + "\n" if warnings else OK + "\n")
        os.replace(tmp, path)
    except OSError as e:
        UI.vprint(1, f"   Could not write {path} ({e}).")
        try:
            os.remove(tmp)
        except OSError:
            pass


def read_result(build_dir, lat, lon, since=0):
    """The warnings a check wrote at or after since (epoch seconds), [] for
    a clean tile, None when there is no such result."""
    path = FNAMES.tile_check_file(build_dir, lat, lon)
    try:
        if os.path.getmtime(path) < since:
            return None
        with open(path, encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
    except OSError:
        return None
    return [] if lines == [OK] else lines
