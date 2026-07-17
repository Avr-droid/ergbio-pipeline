"""
Layer 4 — End-to-end smoke test
Full chain: fixture CSV → parse → calc → save_run → generate_report
Drive and LLM calls are mocked. Validates §7 JSON schema fields.
"""
import pytest
import sys, os, json
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

# ── §7 Required JSON schema fields ───────────────────────────────────────────
REQUIRED_TOP    = {"id", "type", "name", "date", "comp", "params", "calcs", "savedAt"}
REQUIRED_COMP   = {"cellulose", "xylan", "arabinose", "lignin", "ash"}
REQUIRED_PARAMS = {"solidLoad"}


def _mock_drive():
    """Mock _drive_service and MediaIoBaseUpload so no real Drive calls happen."""
    mock_file = MagicMock()
    mock_file.get.return_value = "mock-drive-id-123"
    mock_service = MagicMock()
    mock_service.files.return_value.create.return_value.execute.return_value = mock_file
    return mock_service

# Patch context: mocks both the service AND MediaIoBaseUpload (not installed in test env)
def drive_patches():
    return (
        patch("tools.save_run._drive_service", return_value=_mock_drive()),
        patch("tools.save_run.MediaIoBaseUpload", MagicMock(), create=True),
    )


def _mock_haiku():
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="Mock pipeline summary.")]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


def _mock_sonnet():
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=json.dumps({
        "run_name": "CBP-FIXTURE-01", "date": "2026-07-17",
        "operator": "Diana", "biomass_type": "SB",
    }))]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


# ── EH smoke test ─────────────────────────────────────────────────────────────

EH_RUN_DATA = {
    "run_name": "SMOKE-EH-01", "date": "2026-07-17", "experiment_type": "eh",
    "biomass_type": "SB", "vessel": "Albany 1200L", "operator": "Diana",
    "total_odw_kg": 100.0,
    "lots": [{"lot": "SB-001", "wet": 120.0, "moist": 16.67, "odw": 100.0}],
    "cellulose_pct": 34.71, "xylan_pct": 18.68, "arabinose_pct": 1.61,
    "lignin_pct": 20.94, "ash_pct": 10.46, "extractives_pct": 13.01,
    "water_pct": 10.90, "ethanolSol_pct": 2.09, "aceticAcid_pct": 3.16,
    "massClosure_pct": 92.13, "solid_loading_pct": 10.0,
    "ferm_temp_c": 32.0, "ferm_duration_hr": 72.0,
    "enzyme_product": "Cellic CTec3", "enzyme_loading_mg_g": 10.0,
    "eh_temp_c": 50.0, "eh_duration_hr": 48.0,
    "eh_glc_gL": 28.92, "eh_xyl_gL": 13.40, "eh_arab_gL": 1.00,
    "eh_vol_l": None, "ferm_eth_gL": 10.5, "ferm_eth_kg": None, "ferm_vol_l": None,
    "ferm_res_glc_gL": 2.0, "ferm_res_xyl_gL": 3.0, "ferm_res_arab_gL": 0.5,
}

CBP_RUN_DATA = {
    "run_name": "SMOKE-CBP-01", "date": "2026-07-17", "experiment_type": "cbp",
    "biomass_type": "SB", "operator": "Ares",
    "total_odw_kg": 0.5,
    "lots": [{"lot": "SB-001", "wet": 0.6, "moist": 16.67, "odw": 0.5}],
    "cellulose_pct": 34.71, "xylan_pct": 18.68, "arabinose_pct": 1.61,
    "lignin_pct": 20.94, "ash_pct": 10.46,
    "solid_loading_pct": 10.0, "vessel_type": "falcon50",
    "working_vol_ml": 50.0, "final_tp": 96,
    "seed_stages": 2, "inoculum_details": "10% v/v", "biomass_per_vessel_g": 0.5,
    "conditions": [
        {"name": "Control",  "enzyme": 0, "reps": 3, "eth0": 0.1, "ethF": 0.3, "glc": 8.0, "xyl": 5.0, "ctrl": True},
        {"name": "Strain A", "enzyme": 5, "reps": 3, "eth0": 0.1, "ethF": 8.5, "glc": 1.0, "xyl": 0.5, "ctrl": False},
        {"name": "Strain B", "enzyme": 5, "reps": 3, "eth0": 0.1, "ethF": 6.2, "glc": 2.0, "xyl": 1.0, "ctrl": False},
    ],
}


class TestPipelineEH:
    def _run(self):
        p1, p2 = drive_patches()
        with p1, p2:
            from tools.save_run import save_run
            return save_run(EH_RUN_DATA)

    def test_save_run_returns_success(self):
        assert self._run()["success"] is True

    def test_type_field_is_eh(self):
        assert self._run()["type"] == "eh"

    def test_json_schema_top_level_fields(self):
        result = self._run()
        missing = REQUIRED_TOP - set(result.keys())
        assert not missing, f"Missing §7 fields: {missing}"

    def test_json_schema_comp_fields(self):
        result = self._run()
        missing = REQUIRED_COMP - set(result.get("comp", {}).keys())
        assert not missing, f"Missing comp fields: {missing}"

    def test_json_schema_params_solidLoad(self):
        result = self._run()
        missing = REQUIRED_PARAMS - set(result.get("params", {}).keys())
        assert not missing, f"Missing params fields: {missing}"

    def test_calcs_has_eh_and_fermentation(self):
        calcs = self._run().get("calcs", {})
        assert "enzymatic_hydrolysis" in calcs
        assert "fermentation" in calcs
        assert "theoretical" in calcs

    def test_full_chain_to_report(self):
        p1, p2 = drive_patches()
        with p1, p2, patch("agents.reporter.client", _mock_haiku()):
            from tools.save_run import save_run
            from agents.reporter import generate_report
            saved  = save_run(EH_RUN_DATA)
            report = generate_report(saved)
        assert report["success"] is True
        assert isinstance(report["summary"], str)
        assert "flags" in report


class TestPipelineCBP:
    def _run(self):
        p1, p2 = drive_patches()
        with p1, p2:
            from tools.save_run import save_run
            return save_run(CBP_RUN_DATA)

    def test_save_run_success(self):
        assert self._run()["success"] is True

    def test_cbp_type_field(self):
        assert self._run()["type"] == "cbp"

    def test_ranked_summary_in_calcs(self):
        result = self._run()
        ranked = result["calcs"]["ranked_summary"]
        assert len(ranked) == 2   # control excluded

    def test_ranked_summary_excludes_control(self):
        result = self._run()
        names = [r["condition"] for r in result["calcs"]["ranked_summary"]]
        assert "Control" not in names

    def test_full_chain_ranked_summary_in_report(self):
        p1, p2 = drive_patches()
        with p1, p2, patch("agents.reporter.client", _mock_haiku()):
            from tools.save_run import save_run
            from agents.reporter import generate_report
            saved  = save_run(CBP_RUN_DATA)
            report = generate_report(saved)
        assert len(report["ranked_summary"]) == 2
        assert report["ranked_summary"][0]["condition"] == "Strain A"


class TestExtractorSmoke:
    def test_parse_and_extract_normal_csv(self):
        csv_path = os.path.join(FIXTURES, "normal_hplc.csv")
        with patch("agents.extractor.client", _mock_sonnet()):
            from agents.extractor import extract_data
            result = extract_data(csv_path)
        assert result["success"] is True
        assert result["run_name"] == "CBP-FIXTURE-01"
        assert result["ethanol_t0"] is not None
        assert result["ethanol_final"] is not None

    def test_invalid_file_returns_failure(self):
        with patch("agents.extractor.client", _mock_sonnet()):
            from agents.extractor import extract_data
            result = extract_data(os.path.join(FIXTURES, "no_timepoints.csv"))
        assert result["success"] is False
