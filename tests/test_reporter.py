"""
Layer 3 — Reporter structure tests
Anthropic + LLM call are mocked — we validate output structure, not prose.
"""
import pytest
import sys, os
from unittest.mock import patch, MagicMock

# Mock anthropic before any import of agents.reporter
mock_anthropic = MagicMock()
mock_msg = MagicMock()
mock_msg.content = [MagicMock(text="Mock reporter summary.")]
mock_anthropic.Anthropic.return_value.messages.create.return_value = mock_msg
sys.modules["anthropic"] = mock_anthropic

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from agents.reporter import generate_report


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _cbp_result():
    return {
        "success": True, "run_name": "CBP-TEST-01",
        "experiment_type": "cbp", "biomass_type": "SB",
        "calcs": {
            "type": "cbp",
            "theoretical": {"ethanol_kg": 0.1775, "theo_ethanol_per_vessel_g": 0.35},
            "best_efficiency": 85.0, "best_efficiency_colour": "green",
            "conditions": [
                {"name": "Control",  "enzyme": 0, "reps": 3, "eth0": 0.1, "ethF": 0.3,
                 "net_ethanol_gL": 0.2, "net_ethanol_g": 0.01,
                 "cbp_efficiency": 5.6, "efficiency_colour": "neutral", "ctrl": True},
                {"name": "Strain A", "enzyme": 5, "reps": 3, "eth0": 0.1, "ethF": 8.5,
                 "net_ethanol_gL": 8.4, "net_ethanol_g": 0.42,
                 "cbp_efficiency": 85.0, "efficiency_colour": "green", "ctrl": False},
                {"name": "Strain B", "enzyme": 5, "reps": 3, "eth0": 0.1, "ethF": 6.2,
                 "net_ethanol_gL": 6.1, "net_ethanol_g": 0.305,
                 "cbp_efficiency": 61.7, "efficiency_colour": "amber", "ctrl": False},
                {"name": "Strain C", "enzyme": 5, "reps": 3, "eth0": 0.1, "ethF": 2.0,
                 "net_ethanol_gL": 1.9, "net_ethanol_g": 0.095,
                 "cbp_efficiency": 19.2, "efficiency_colour": "red", "ctrl": False},
            ],
            "ranked_summary": [
                {"rank": 1, "condition": "Strain A", "net_ethanol_gL": 8.4,
                 "cbp_efficiency_pct": 85.0, "below_threshold": False},
                {"rank": 2, "condition": "Strain B", "net_ethanol_gL": 6.1,
                 "cbp_efficiency_pct": 61.7, "below_threshold": False},
                {"rank": 3, "condition": "Strain C", "net_ethanol_gL": 1.9,
                 "cbp_efficiency_pct": 19.2, "below_threshold": True},
            ],
        },
    }


def _eh_result():
    return {
        "success": True, "run_name": "EH-TEST-01",
        "experiment_type": "eh", "biomass_type": "SB",
        "calcs": {
            "type": "eh",
            "theoretical": {"ethanol_kg": 31.5, "glucose_kg": 38.6,
                            "xylose_kg": 21.2, "arabinose_kg": 1.8, "total_sugars_kg": 61.6},
            "enzymatic_hydrolysis": {
                "glucose_yield_pct": 75.2, "xylose_yield_pct": 63.6,
                "overall_yield_pct": 71.6, "efficiency_colour": "amber",
            },
            "fermentation": {
                "efficiency_pct": 46.6, "actual_ethanol_kg": 10.5,
                "residual_sugars_kg": 5.5, "efficiency_colour": "red",
            },
            "overall": {
                "efficiency_pct": 33.4, "actual_ethanol_kg": 10.5,
                "efficiency_colour": "red",
            },
        },
    }


# ── CBP ───────────────────────────────────────────────────────────────────────

class TestReporterCBP:
    def setup_method(self):
        self.report = generate_report(_cbp_result())

    def test_success(self):
        assert self.report["success"] is True

    def test_ranked_summary_present(self):
        assert "ranked_summary" in self.report
        assert len(self.report["ranked_summary"]) > 0

    def test_ranked_summary_excludes_controls(self):
        names = [r["condition"] for r in self.report["ranked_summary"]]
        assert "Control" not in names

    def test_ranked_summary_sorted_best_to_worst(self):
        effs = [r["cbp_efficiency_pct"] for r in self.report["ranked_summary"]]
        assert effs == sorted(effs, reverse=True)

    def test_ranks_sequential(self):
        ranks = [r["rank"] for r in self.report["ranked_summary"]]
        assert ranks == list(range(1, len(ranks) + 1))

    def test_below_threshold_flagged(self):
        strain_c = next(r for r in self.report["ranked_summary"] if r["condition"] == "Strain C")
        assert strain_c["below_threshold"] is True

    def test_above_threshold_not_flagged(self):
        strain_a = next(r for r in self.report["ranked_summary"] if r["condition"] == "Strain A")
        assert strain_a["below_threshold"] is False

    def test_flags_list_present(self):
        assert isinstance(self.report["flags"], list)

    def test_flags_contain_below_threshold_warning(self):
        flag_text = " ".join(self.report["flags"])
        assert "Strain C" in flag_text or "19.2" in flag_text

    def test_key_metrics_best_efficiency(self):
        assert self.report["key_metrics"]["best_cbp_efficiency"] == 85.0

    def test_key_metrics_has_conditions(self):
        assert "conditions" in self.report["key_metrics"]

    def test_per_condition_has_net_ethanol(self):
        for c in self.report["key_metrics"]["conditions"]:
            assert "net_ethanol_gL" in c

    def test_per_condition_has_efficiency(self):
        for c in self.report["key_metrics"]["conditions"]:
            assert "cbp_efficiency_pct" in c

    def test_summary_is_non_empty_string(self):
        assert isinstance(self.report["summary"], str)
        assert len(self.report["summary"]) > 0


# ── EH ───────────────────────────────────────────────────────────────────────

class TestReporterEH:
    def setup_method(self):
        self.report = generate_report(_eh_result())

    def test_success(self):
        assert self.report["success"] is True

    def test_ranked_summary_empty_for_eh(self):
        assert self.report["ranked_summary"] == []

    def test_flags_include_low_ferm_efficiency(self):
        flag_text = " ".join(self.report["flags"])
        assert "46.6" in flag_text or "Fermentation" in flag_text

    def test_key_metrics_has_eh_fields(self):
        km = self.report["key_metrics"]
        assert "eh_glucose_yield" in km
        assert "ferm_efficiency" in km
        assert "overall_efficiency" in km

    def test_key_metrics_theoretical_ethanol(self):
        assert abs(self.report["key_metrics"]["theoretical_ethanol_kg"] - 31.5) < 0.01


# ── Failure handling ──────────────────────────────────────────────────────────

class TestReporterFailure:
    def test_failed_result_returns_gracefully(self):
        r = generate_report({"success": False, "error": "parse failed"})
        assert r["success"] is False
        assert "failed" in r["summary"].lower()
        assert r["ranked_summary"] == []
