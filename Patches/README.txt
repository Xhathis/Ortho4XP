Patches for a tile go in Patches\<10x10 block>\<tile>\, for example
Patches\+60-060\+64-052\BGGH.patch.osm for tile +64-052 (the block is the
tile's lat/lon rounded down to a multiple of 10). Step 1 reads every
*.patch.osm there; a patch named <ICAO>.patch.osm also replaces the flat
area X-Plane gives that airport. A file directly in Patches\<tile>\ is
never read.
