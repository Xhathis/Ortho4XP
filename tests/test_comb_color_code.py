"""#64: an unknown color filter skips one line of a .comb, not the file."""
import O4_File_Names as FNAMES
import O4_Imagery_Utils as IMG


def test_unknown_color_code_skips_only_its_line(tmp_path, monkeypatch, capsys):
    (tmp_path / "TEST.comb").write_text(
        "Arc  Ext1  warm  high\n"
        "GO2  Ext1  none  high\n"
    )
    monkeypatch.setattr(FNAMES, "Provider_dir", str(tmp_path))
    monkeypatch.setattr(IMG, "providers_dict", {
        "Arc": {"extent": "global", "color_filters": "none"},
        "GO2": {"extent": "global", "color_filters": "none"},
    })
    monkeypatch.setattr(IMG, "extents_dict", {"Ext1": {}})
    monkeypatch.setattr(IMG, "color_filters_dict", {"none": []})
    monkeypatch.setattr(IMG, "combined_providers_dict", {})
    IMG.initialize_combined_providers_dict()
    layers = IMG.combined_providers_dict["TEST"]
    assert [l["layer_code"] for l in layers] == ["GO2"]
    assert "Unknown color filter in combined provider TEST : warm" in (
        capsys.readouterr().out)
