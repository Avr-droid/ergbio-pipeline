"""
Layer 1 — Calculation unit tests
Tests _calc_theo, _calc_eh, _calc_cbp with known reference values.
Regression tests for bugs found and fixed:
  - CBP double-division (net_kg was /1000 twice)
  - Arabinose missing from EH total sugars
  - Solid loading → slurry volume auto-calc
"""
import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.save_run import _calc_theo, _calc_eh, _calc_cbp, _eff_colour

# _calc_theo expects comp with keys: cellulose, xylan, arabinose (% values)
SB_COMP_FOR_THEO = {
    "cellulose": 34.71, "xylan": 18.68, "arabinose": 1.61,
    "lignin": 20.94, "ash": 10.46, "extractives": 13.01,
    "water": 10.90, "ethanolSol": 2.09, "aceticAcid": 3.16, "massClosure": 92.13,
}

# _calc_eh/_calc_cbp expect _pct suffix keys (from UI / run_data dict)
SB_COMP_FOR_EH = {
    "cellulose_pct": 34.71, "xylan_pct": 18.68, "arabinose_pct": 1.61,
    "lignin_pct": 20.94, "ash_pct": 10.46, "extractives_pct": 13.01,
    "water_pct": 10.90, "ethanolSol_pct": 2.09, "aceticAcid_pct": 3.16,
    "massClosure_pct": 92.13,
}


# ── _calc_theo ────────────────────────────────────────────────────────────────

class TestCalcTheo:
    def test_glucose_constant(self):
        """Cellulose × 1.111 (§4.1)"""
        t = _calc_theo(100.0, SB_COMP_FOR_THEO)
        assert abs(t["glucose_kg"] - 100 * 0.3471 * 1.111) < 0.01

    def test_xylose_constant(self):
        """Xylan × 1.136 (§4.1)"""
        t = _calc_theo(100.0, SB_COMP_FOR_THEO)
        assert abs(t["xylose_kg"] - 100 * 0.1868 * 1.136) < 0.01

    def test_arabinose_constant(self):
        """Arabinose × 1.136 (§4.1)"""
        t = _calc_theo(100.0, SB_COMP_FOR_THEO)
        assert abs(t["arabinose_kg"] - 100 * 0.0161 * 1.136) < 0.01

    def test_ethanol_stoichiometry(self):
        """Total sugars × 0.511 (Gay-Lussac, §4.1)"""
        t = _calc_theo(100.0, SB_COMP_FOR_THEO)
        assert abs(t["ethanol_kg"] - t["total_sugars_kg"] * 0.511) < 0.001

    def test_total_sugars_sum(self):
        """Total sugars = glucose + xylose + arabinose"""
        t = _calc_theo(100.0, SB_COMP_FOR_THEO)
        assert abs(t["total_sugars_kg"] - (t["glucose_kg"] + t["xylose_kg"] + t["arabinose_kg"])) < 0.001

    def test_scales_linearly_with_odw(self):
        """Doubling ODW doubles all theo values"""
        t1 = _calc_theo(100.0, SB_COMP_FOR_THEO)
        t2 = _calc_theo(200.0, SB_COMP_FOR_THEO)
        assert abs(t2["ethanol_kg"] / t1["ethanol_kg"] - 2.0) < 0.001

    def test_zero_cellulose_gives_zero_glucose(self):
        comp = {**SB_COMP_FOR_THEO, "cellulose": 0.0}
        t = _calc_theo(100.0, comp)
        assert t["glucose_kg"] == 0.0

    def test_zero_odw_gives_zero(self):
        t = _calc_theo(0.0, SB_COMP_FOR_THEO)
        assert t["ethanol_kg"] == 0.0


# ── _calc_eh ─────────────────────────────────────────────────────────────────

BASE_EH = {
    **SB_COMP_FOR_EH,
    "total_odw_kg": 100.0,
    "solid_loading_pct": 10.0,
    # slurry vol = 1000 L; theo glucose = 100 × 0.3471 × 1.111 = 38.56 kg
    # 75% yield → 28.92 kg actual → 28.92 g/L in 1000 L
    "eh_glc_gL": 28.92, "eh_xyl_gL": 13.40, "eh_arab_gL": 1.00,
    "eh_vol_l": None,
    "ferm_eth_gL": 10.5, "ferm_eth_kg": None, "ferm_vol_l": None,
    "ferm_res_glc_gL": 2.0, "ferm_res_xyl_gL": 3.0, "ferm_res_arab_gL": 0.5,
}

class TestCalcEH:
    def test_slurry_vol_from_solid_loading(self):
        """Slurry vol = ODW ÷ (solid_loading / 100) — §4.2"""
        r = _calc_eh(BASE_EH)
        assert abs(r["theoretical"]["slurry_vol_l"] - 1000.0) < 0.1

    def test_glucose_yield_pct(self):
        """EH glucose yield ≈ 75%"""
        r = _calc_eh(BASE_EH)
        assert abs(r["enzymatic_hydrolysis"]["glucose_yield_pct"] - 75.0) < 1.0

    def test_arabinose_included_in_total_sugars(self):
        """REGRESSION: arabinose must be included in EH total sugars"""
        r = _calc_eh(BASE_EH)
        eh = r["enzymatic_hydrolysis"]
        expected = (BASE_EH["eh_glc_gL"] + BASE_EH["eh_xyl_gL"] + BASE_EH["eh_arab_gL"]) * 1000 / 1000
        assert abs(eh["total_sugars_kg"] - expected) < 0.01

    def test_arabinose_in_residuals(self):
        """REGRESSION: residual arabinose must appear in residual_sugars_kg"""
        r = _calc_eh(BASE_EH)
        ferm = r["fermentation"]
        res_arab = BASE_EH["ferm_res_arab_gL"] * 1000 / 1000
        assert abs(ferm["residual_arabinose_kg"] - res_arab) < 0.001
        assert ferm["residual_sugars_kg"] >= ferm["residual_arabinose_kg"]

    def test_direct_eth_kg_override(self):
        """direct kg entry bypasses g/L × volume (§3.5)"""
        data = {**BASE_EH, "ferm_eth_kg": 15.0}
        r = _calc_eh(data)
        assert abs(r["fermentation"]["actual_ethanol_kg"] - 15.0) < 0.001

    def test_ferm_efficiency_denominator_is_eh_sugars(self):
        """Ferm eff = actual_eth / (EH_sugars × 0.511) × 100 — not theo"""
        r = _calc_eh(BASE_EH)
        eh = r["enzymatic_hydrolysis"]
        ferm = r["fermentation"]
        expected_denom = eh["total_sugars_kg"] * 0.511
        expected_eff = ferm["actual_ethanol_kg"] / expected_denom * 100
        assert abs(ferm["efficiency_pct"] - expected_eff) < 0.1

    def test_overall_efficiency_denominator_is_theo(self):
        """Overall eff = actual_eth / theo_ethanol × 100"""
        r = _calc_eh(BASE_EH)
        theo_eth = r["theoretical"]["ethanol_kg"]
        actual_eth = r["fermentation"]["actual_ethanol_kg"]
        expected = actual_eth / theo_eth * 100
        assert abs(r["overall"]["efficiency_pct"] - expected) < 0.1

    def test_eh_vol_explicit_overrides_slurry(self):
        """Explicit eh_vol_l overrides slurry vol, giving different glucose kg"""
        data_slurry = {**BASE_EH, "eh_vol_l": None}
        data_half   = {**BASE_EH, "eh_vol_l": 500.0}
        r_slurry = _calc_eh(data_slurry)
        r_half   = _calc_eh(data_half)
        assert r_half["enzymatic_hydrolysis"]["glucose_kg"] < r_slurry["enzymatic_hydrolysis"]["glucose_kg"]


# ── _calc_cbp ─────────────────────────────────────────────────────────────────

BASE_CBP = {
    **SB_COMP_FOR_EH,
    "total_odw_kg": 0.5,
    "solid_loading_pct": 10.0,
    "working_vol_ml": 50.0,
    "biomass_per_vessel_g": 0.5,
    "final_tp": 96,
    "conditions": [
        {"name": "Control",  "enzyme": 0.0, "reps": 3, "eth0": 0.1, "ethF": 0.3,  "glc": 8.0, "xyl": 5.0, "ctrl": True},
        {"name": "Strain A", "enzyme": 5.0, "reps": 3, "eth0": 0.1, "ethF": 8.5,  "glc": 1.0, "xyl": 0.5, "ctrl": False},
        {"name": "Strain B", "enzyme": 5.0, "reps": 3, "eth0": 0.1, "ethF": 6.2,  "glc": 2.0, "xyl": 1.0, "ctrl": False},
        {"name": "Strain C", "enzyme": 5.0, "reps": 3, "eth0": 0.1, "ethF": 2.0,  "glc": 4.0, "xyl": 2.0, "ctrl": False},
    ],
}

class TestCalcCBP:
    def test_net_ethanol_is_final_minus_t0(self):
        """Net EtOH = ethF - eth0 (g/L)"""
        r = _calc_cbp(BASE_CBP)
        for c in r["conditions"]:
            raw = next(x for x in BASE_CBP["conditions"] if x["name"] == c["name"])
            assert abs(c["net_ethanol_gL"] - (raw["ethF"] - raw["eth0"])) < 0.001

    def test_net_ethanol_g_single_division(self):
        """REGRESSION: net_g = net_gL × wv_mL / 1000 (ONE ÷1000, not two)"""
        r = _calc_cbp(BASE_CBP)
        strain_a = next(c for c in r["conditions"] if c["name"] == "Strain A")
        expected_g = (8.5 - 0.1) * 50.0 / 1000   # 0.42 g
        assert abs(strain_a["net_ethanol_g"] - expected_g) < 0.001
        assert strain_a["net_ethanol_g"] > 0.01   # must be grams, not micrograms

    def test_controls_excluded_from_ranked_summary(self):
        r = _calc_cbp(BASE_CBP)
        names = [x["condition"] for x in r["ranked_summary"]]
        assert "Control" not in names

    def test_ranked_summary_sorted_best_to_worst(self):
        r = _calc_cbp(BASE_CBP)
        effs = [x["cbp_efficiency_pct"] for x in r["ranked_summary"]]
        assert effs == sorted(effs, reverse=True)

    def test_ranked_summary_rank_sequential(self):
        r = _calc_cbp(BASE_CBP)
        ranks = [x["rank"] for x in r["ranked_summary"]]
        assert ranks == list(range(1, len(ranks) + 1))

    def test_below_threshold_flag(self):
        """Conditions with CBP eff < 60% get below_threshold = True"""
        r = _calc_cbp(BASE_CBP)
        strain_c = next((x for x in r["ranked_summary"] if x["condition"] == "Strain C"), None)
        if strain_c and strain_c["cbp_efficiency_pct"] < 60:
            assert strain_c["below_threshold"] is True

    def test_best_efficiency_is_max_non_control(self):
        r = _calc_cbp(BASE_CBP)
        non_ctrl = [c["cbp_efficiency"] for c in r["conditions"] if not c.get("ctrl") and c["cbp_efficiency"] is not None]
        assert abs(r["best_efficiency"] - max(non_ctrl)) < 0.01

    def test_cbp_efficiency_uses_per_vessel_theo(self):
        """CBP eff = (net_eth_g / theo_ethanol_per_vessel_g) × 100"""
        r = _calc_cbp(BASE_CBP)
        strain_a = next(c for c in r["conditions"] if c["name"] == "Strain A")
        # Key is theo_ethanol_per_vessel_g in theoretical dict
        theo_per_vessel_g = r["theoretical"]["theo_ethanol_per_vessel_g"]
        expected_eff = strain_a["net_ethanol_g"] / theo_per_vessel_g * 100
        assert abs(strain_a["cbp_efficiency"] - expected_eff) < 0.1


# ── _eff_colour ───────────────────────────────────────────────────────────────

class TestEffColour:
    def test_green(self):      assert _eff_colour(80)   == "green"
    def test_green_100(self):  assert _eff_colour(100)  == "green"
    def test_amber(self):      assert _eff_colour(79)   == "amber"
    def test_amber_60(self):   assert _eff_colour(60)   == "amber"
    def test_red(self):        assert _eff_colour(59)   == "red"
    def test_red_zero(self):   assert _eff_colour(0)    == "red"
    def test_none(self):       assert _eff_colour(None) == "neutral"
