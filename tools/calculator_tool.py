"""
calculator_tool.py — Live yield calculator tool for the Penny Agent.

Wraps the core ErgBio yield calculations so Claude can compute
EH yield, fermentation efficiency, and sugar utilization on the fly
during a conversation — not just reason about them abstractly.

Formulas (standard cellulosic ethanol industry):
  EH Yield (%)        = (Glucose released / Theoretical max from glucan) × 100
  Theoretical max     = Glucan content (g) × 1.111  (glucose/glucan conversion factor)
  Ferm Efficiency (%) = (Ethanol produced / Theoretical max from sugars) × 100
  Theoretical ethanol = (Glucose + Xylose consumed) × 0.511  (ethanol yield factor)
  Xylose utilization  = (Xylose consumed / Initial xylose) × 100
"""

import logging

logger = logging.getLogger(__name__)

# Industry standard conversion factors
GLUCAN_TO_GLUCOSE = 1.111   # g glucose per g glucan (MW correction)
SUGAR_TO_ETHANOL  = 0.511   # theoretical max g ethanol per g fermentable sugar


def calculate_eh_yield(
    glucose_released_g_l: float,
    glucan_content_pct: float,
    solids_loading_g_l: float,
) -> dict:
    """
    Calculate Enzymatic Hydrolysis yield.

    Args:
        glucose_released_g_l : Glucose concentration in hydrolysate (g/L)
        glucan_content_pct   : Glucan % in biomass (e.g. 33.5 for 33.5%)
        solids_loading_g_l   : Biomass loading (g dry biomass per L)

    Returns dict with eh_yield_pct, theoretical_max_g_l, and interpretation.
    """
    try:
        theoretical_max = (glucan_content_pct / 100) * solids_loading_g_l * GLUCAN_TO_GLUCOSE
        if theoretical_max <= 0:
            return {"success": False, "error": "Theoretical max is zero — check glucan% and solids loading"}

        eh_yield = (glucose_released_g_l / theoretical_max) * 100

        interpretation = (
            "Excellent (>80%)" if eh_yield > 80
            else "Good (60–80%)" if eh_yield > 60
            else "Moderate (40–60%)" if eh_yield > 40
            else "Low (<40%) — investigate enzyme loading, pretreatment efficacy, or inhibitors"
        )

        return {
            "success":           True,
            "eh_yield_pct":      round(eh_yield, 1),
            "theoretical_max_g_l": round(theoretical_max, 2),
            "glucose_released_g_l": glucose_released_g_l,
            "interpretation":    interpretation,
            "formula":           f"({glucose_released_g_l} / {theoretical_max:.2f}) × 100 = {eh_yield:.1f}%",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def calculate_fermentation_efficiency(
    ethanol_final_g_l: float,
    glucose_t0_g_l: float,
    xylose_t0_g_l: float,
    glucose_final_g_l: float = 0.0,
    xylose_final_g_l: float = 0.0,
    include_xylose: bool = True,
) -> dict:
    """
    Calculate fermentation efficiency.

    Args:
        ethanol_final_g_l  : Final ethanol concentration (g/L)
        glucose_t0_g_l     : Initial glucose (g/L)
        xylose_t0_g_l      : Initial xylose (g/L)
        glucose_final_g_l  : Residual glucose at end (g/L), default 0
        xylose_final_g_l   : Residual xylose at end (g/L), default 0
        include_xylose     : Whether to include xylose in theoretical max

    Returns dict with ferm_efficiency_pct and sugar utilization breakdown.
    """
    try:
        glucose_consumed = glucose_t0_g_l - glucose_final_g_l
        xylose_consumed  = xylose_t0_g_l  - xylose_final_g_l

        total_sugar = glucose_consumed + (xylose_consumed if include_xylose else 0)
        if total_sugar <= 0:
            return {"success": False, "error": "No sugar consumption detected"}

        theoretical_ethanol = total_sugar * SUGAR_TO_ETHANOL
        ferm_efficiency     = (ethanol_final_g_l / theoretical_ethanol) * 100

        glucose_utilization = (glucose_consumed / glucose_t0_g_l * 100) if glucose_t0_g_l > 0 else None
        xylose_utilization  = (xylose_consumed  / xylose_t0_g_l  * 100) if xylose_t0_g_l  > 0 else None

        interpretation = (
            "Excellent (>90%)" if ferm_efficiency > 90
            else "Good (75–90%)" if ferm_efficiency > 75
            else "Moderate (50–75%)" if ferm_efficiency > 50
            else "Low (<50%) — check inhibitor levels, organism viability, or sugar availability"
        )

        return {
            "success":                True,
            "ferm_efficiency_pct":    round(ferm_efficiency, 1),
            "theoretical_ethanol_g_l": round(theoretical_ethanol, 2),
            "ethanol_produced_g_l":   ethanol_final_g_l,
            "glucose_consumed_g_l":   round(glucose_consumed, 2),
            "xylose_consumed_g_l":    round(xylose_consumed, 2),
            "glucose_utilization_pct": round(glucose_utilization, 1) if glucose_utilization else None,
            "xylose_utilization_pct":  round(xylose_utilization, 1) if xylose_utilization else None,
            "interpretation":          interpretation,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def calculate_from_run_record(run_record: dict) -> dict:
    """
    Compute all yields directly from a run record dict.
    Uses the analyte timeseries — no manual input needed.
    """
    ts      = run_record.get("analyte_timeseries", {})
    tps     = sorted(run_record.get("timepoints", []))
    conds   = run_record.get("conditions", {})
    run_id  = run_record.get("run_id", "Unknown")

    if not tps:
        return {"success": False, "error": f"No timepoints in run record {run_id}"}

    t0, tf = tps[0], tps[-1]

    def _val(analyte, tp):
        return ts.get(analyte, {}).get(str(tp)) or ts.get(analyte, {}).get(tp)

    glucose_t0    = _val("Glucose", t0)
    glucose_final = _val("Glucose", tf)
    xylose_t0     = _val("Xylose",  t0)
    xylose_final  = _val("Xylose",  tf)
    ethanol_final = _val("Ethanol", tf)

    results = {"run_id": run_id, "t0_h": t0, "final_h": tf}

    # EH yield — requires biomass composition and loading from conditions
    glucan_pct     = conds.get("glucan_content_pct")
    solids_loading = conds.get("solids_loading_g_l")

    if glucan_pct and solids_loading and glucose_t0 is not None:
        results["eh_yield"] = calculate_eh_yield(glucose_t0, glucan_pct, solids_loading)
    else:
        results["eh_yield"] = {
            "success": False,
            "error": "Missing glucan_content_pct or solids_loading_g_l in run conditions — ask Ares to update the run record"
        }

    # Fermentation efficiency
    if all(v is not None for v in [ethanol_final, glucose_t0, xylose_t0]):
        results["ferm_efficiency"] = calculate_fermentation_efficiency(
            ethanol_final_g_l=ethanol_final,
            glucose_t0_g_l=glucose_t0,
            xylose_t0_g_l=xylose_t0,
            glucose_final_g_l=glucose_final or 0.0,
            xylose_final_g_l=xylose_final or 0.0,
        )
    else:
        results["ferm_efficiency"] = {"success": False, "error": "Missing glucose/xylose/ethanol data"}

    results["success"] = True
    return results


def format_for_context(result: dict) -> str:
    """Format calculator result for LLM context."""
    if not result.get("success"):
        return f"Calculation failed: {result.get('error')}"

    lines = [f"=== Yield Calculations: {result.get('run_id', '')} ==="]

    eh = result.get("eh_yield", {})
    if eh.get("success"):
        lines.append(f"EH Yield: {eh['eh_yield_pct']}% ({eh['interpretation']})")
        lines.append(f"  Theoretical max glucose: {eh['theoretical_max_g_l']} g/L")
        lines.append(f"  Glucose released: {eh['glucose_released_g_l']} g/L")
    else:
        lines.append(f"EH Yield: {eh.get('error')}")

    fe = result.get("ferm_efficiency", {})
    if fe.get("success"):
        lines.append(f"Fermentation Efficiency: {fe['ferm_efficiency_pct']}% ({fe['interpretation']})")
        lines.append(f"  Ethanol produced: {fe['ethanol_produced_g_l']} g/L (theoretical max: {fe['theoretical_ethanol_g_l']} g/L)")
        lines.append(f"  Glucose utilization: {fe.get('glucose_utilization_pct')}%")
        lines.append(f"  Xylose utilization: {fe.get('xylose_utilization_pct')}%")
    else:
        lines.append(f"Fermentation Efficiency: {fe.get('error')}")

    return "\n".join(lines)
