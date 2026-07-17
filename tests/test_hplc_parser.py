"""
Layer 2 — HPLC parser tests
Uses CSV fixtures in tests/fixtures/. No real lab files required.
"""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.hplc_parser import parse_hplc_file, _is_control

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

def fix(name):
    return os.path.join(FIXTURES, name)


# ── Control label detection ───────────────────────────────────────────────────

class TestIsControl:
    def test_blank(self):        assert _is_control("Blank") is True
    def test_abiotic(self):      assert _is_control("Abiotic") is True
    def test_control(self):      assert _is_control("Control") is True
    def test_novo_only(self):    assert _is_control("Novo Only") is True
    def test_no_cell(self):      assert _is_control("No Cell") is True
    def test_media_only(self):   assert _is_control("Media Only") is True
    def test_case_insensitive(self): assert _is_control("BLANK") is True
    def test_strain_not_ctrl(self):  assert _is_control("Strain A") is False
    def test_cbp_run_not_ctrl(self): assert _is_control("CBP Run 1") is False


# ── Normal parse ──────────────────────────────────────────────────────────────

class TestNormalParse:
    def setup_method(self):
        self.r = parse_hplc_file(fix("normal_hplc.csv"))

    def test_success(self):
        assert self.r["success"] is True

    def test_timepoints_detected(self):
        assert "T0" in self.r["timepoints"]
        assert "T96h" in self.r["timepoints"]
        assert len(self.r["timepoints"]) == 4

    def test_ethanol_t0(self):
        assert abs(self.r["ethanol_t0"] - 0.10) < 0.001

    def test_ethanol_final(self):
        assert abs(self.r["ethanol_final"] - 9.50) < 0.001

    def test_glucose_final(self):
        assert abs(self.r["glucose_final"] - 1.20) < 0.001

    def test_xylose_final(self):
        assert abs(self.r["xylose_final"] - 2.50) < 0.001

    def test_ethanol_series_has_all_timepoints(self):
        assert len(self.r["ethanol"]) == 4


# ── Control auto-detection ────────────────────────────────────────────────────

class TestControlDetection:
    def setup_method(self):
        self.r = parse_hplc_file(fix("controls_hplc.csv"))

    def test_success(self):
        assert self.r["success"] is True

    def test_blank_flagged_as_control(self):
        assert "Blank" in self.r["controls"]

    def test_abiotic_flagged_as_control(self):
        assert "Abiotic" in self.r["controls"]

    def test_novo_only_flagged_as_control(self):
        assert "Novo Only" in self.r["controls"]

    def test_control_flagged(self):
        assert "Control" in self.r["controls"]

    def test_strains_not_flagged(self):
        assert "Strain A" not in self.r["controls"]
        assert "Strain B" not in self.r["controls"]

    def test_condition_rows_have_is_control(self):
        ctrl_rows = [c for c in self.r["condition_rows"] if c["is_control"]]
        assert len(ctrl_rows) >= 4

    def test_condition_matching(self):
        existing = [{"name": "Strain A"}, {"name": "Strain B"}]
        r = parse_hplc_file(fix("controls_hplc.csv"), existing_conditions=existing)
        matched = [c for c in r["condition_rows"] if c["matched_condition"] is not None]
        matched_names = [c["matched_condition"] for c in matched]
        assert "Strain A" in matched_names
        assert "Strain B" in matched_names


# ── Extended timepoint regex (§15.1) ─────────────────────────────────────────

class TestExtendedTimepoints:
    def setup_method(self):
        self.r = parse_hplc_file(fix("extended_timepoints.csv"))

    def test_success(self):
        assert self.r["success"] is True

    def test_t96_plus_h_detected(self):
        """T96+h must match the extended regex"""
        assert "T96+h" in self.r["timepoints"]

    def test_final_value_from_t96_plus(self):
        assert abs(self.r["ethanol_final"] - 10.20) < 0.001

    def test_t0_detected(self):
        assert "T0" in self.r["timepoints"]


# ── Stdev/SEM rows skipped ────────────────────────────────────────────────────

class TestStdevRowsSkipped:
    def setup_method(self):
        self.r = parse_hplc_file(fix("stdev_rows_hplc.csv"))

    def test_success(self):
        assert self.r["success"] is True

    def test_stdev_not_in_condition_rows(self):
        names = [c["name"] for c in self.r["condition_rows"]]
        for bad in ("StDev", "CV%", "SEM"):
            assert bad not in names

    def test_ethanol_final_correct(self):
        """Stdev rows must not corrupt ethanol final value"""
        assert abs(self.r["ethanol_final"] - 9.50) < 0.001


# ── t0_values / final_values dicts (for condition table auto-fill) ────────────

class TestAutoFillDicts:
    def setup_method(self):
        self.r = parse_hplc_file(fix("controls_hplc.csv"))

    def test_t0_values_dict_present(self):
        assert "t0_values" in self.r
        assert isinstance(self.r["t0_values"], dict)

    def test_final_values_dict_present(self):
        assert "final_values" in self.r
        assert isinstance(self.r["final_values"], dict)

    def test_strain_a_has_values(self):
        assert "Strain A" in self.r["t0_values"]
        assert "Strain A" in self.r["final_values"]


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_file_returns_error(self):
        r = parse_hplc_file(fix("empty.csv"))
        assert r["success"] is False
        assert "error" in r

    def test_no_timepoint_header_returns_error(self):
        r = parse_hplc_file(fix("no_timepoints.csv"))
        assert r["success"] is False
        assert "timepoint" in r["error"].lower()

    def test_unsupported_extension(self):
        r = parse_hplc_file("some_file.txt")
        assert r["success"] is False

    def test_nonexistent_file(self):
        r = parse_hplc_file("/tmp/does_not_exist.csv")
        assert r["success"] is False
