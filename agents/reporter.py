import os
import anthropic
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _eff_flag(pct, label):
    if pct is None:
        return ""
    if pct < 60:
        return f"⚠ {label}: {pct:.1f}% — BELOW 60% threshold"
    if pct < 80:
        return f"△ {label}: {pct:.1f}% — below 80% target"
    return f"✓ {label}: {pct:.1f}%"


def generate_report(results: dict) -> dict:
    """
    Generate a structured report from save_run() results.

    Compliance:
    - Per-condition net ethanol + CBP efficiency % (Diana §5)
    - Flag any condition <60% threshold
    - Ranked strain summary sorted best→worst (controls excluded)

    Returns:
        success, run_name, summary, flags, key_metrics, ranked_summary
    """
    if not results.get("success"):
        return {
            "success":        False,
            "error":          results.get("error", "Unknown error"),
            "summary":        "Pipeline failed — no report generated.",
            "flags":          [],
            "key_metrics":    {},
            "ranked_summary": [],
        }

    calcs    = results.get("calcs", {})
    exp_type = results.get("experiment_type", "cbp")
    run_name = results.get("run_name", "Unknown Run")
    biomass  = results.get("biomass_type", "Unknown")
    warning  = results.get("biomass_warning")
    flags    = []

    # ── CBP ──────────────────────────────────────────────────────────────────
    if exp_type == "cbp":
        conditions = calcs.get("conditions", [])
        best_eff   = calcs.get("best_efficiency")
        theo       = calcs.get("theoretical", {})

        # Per-condition rows — include net ethanol + efficiency %, flag <60%
        condition_details = []
        for c in conditions:
            eff = c.get("cbp_efficiency")
            net = c.get("net_ethanol_gL")
            is_ctrl = c.get("ctrl", False)
            below   = (eff is not None and eff < 60 and not is_ctrl)
            condition_details.append({
                "name":              c.get("name", "—"),
                "enzyme":            c.get("enzyme", "—"),
                "reps":              c.get("reps"),
                "eth0":              c.get("eth0"),
                "ethF":              c.get("ethF"),
                "net_ethanol_gL":    net,
                "net_ethanol_g":     c.get("net_ethanol_g"),
                "cbp_efficiency_pct": eff,
                "efficiency_colour": c.get("efficiency_colour"),
                "is_control":        is_ctrl,
                "below_threshold":   below,
            })
            if not is_ctrl:
                flags.append(_eff_flag(eff, f"CBP — {c.get('name','?')}"))
                if below:
                    flags.append(f"  ↳ Net EtOH: {net:.2f} g/L" if net else "")

        # Ranked summary — non-controls only, best→worst by CBP efficiency
        # Fall back to ranked_summary from calcs if available (already sorted in save_run)
        ranked_summary = calcs.get("ranked_summary", [])
        if not ranked_summary:
            non_ctrl = [(c["cbp_efficiency_pct"], c) for c in condition_details
                        if not c["is_control"] and c["cbp_efficiency_pct"] is not None]
            non_ctrl.sort(key=lambda x: x[0], reverse=True)
            ranked_summary = [
                {
                    "rank":               i + 1,
                    "condition":          c["name"],
                    "net_ethanol_gL":     c["net_ethanol_gL"],
                    "cbp_efficiency_pct": c["cbp_efficiency_pct"],
                    "below_threshold":    c["below_threshold"],
                }
                for i, (_, c) in enumerate(non_ctrl)
            ]

        key_metrics = {
            "experiment_type":           "CBP",
            "theoretical_ethanol_kg":    theo.get("ethanol_kg"),
            "best_cbp_efficiency":       best_eff,
            "best_efficiency_colour":    calcs.get("best_efficiency_colour"),
            "conditions":                condition_details,
        }

        # Build ranked summary text for Haiku prompt
        ranked_lines = "\n".join(
            f"  #{r['rank']} {r['condition']}: {r['cbp_efficiency_pct']:.1f}% CBP eff, "
            f"{r['net_ethanol_gL']:.2f} g/L net EtOH"
            + (" ⚠ BELOW 60%" if r["below_threshold"] else "")
            for r in ranked_summary
        ) if ranked_summary else "  No non-control conditions."

    # ── EH + Fermentation ────────────────────────────────────────────────────
    else:
        eh      = calcs.get("enzymatic_hydrolysis", {})
        ferm    = calcs.get("fermentation", {})
        overall = calcs.get("overall", {})
        theo    = calcs.get("theoretical", {})

        key_metrics = {
            "experiment_type":         "EH+Fermentation",
            "theoretical_ethanol_kg":  theo.get("ethanol_kg"),
            "eh_glucose_yield":        eh.get("glucose_yield_pct"),
            "eh_xylose_yield":         eh.get("xylose_yield_pct"),
            "eh_overall_yield":        eh.get("overall_yield_pct"),
            "eh_colour":               eh.get("efficiency_colour"),
            "ferm_efficiency":         ferm.get("efficiency_pct"),
            "ferm_colour":             ferm.get("efficiency_colour"),
            "overall_efficiency":      overall.get("efficiency_pct"),
            "overall_colour":          overall.get("efficiency_colour"),
            "actual_ethanol_kg":       overall.get("actual_ethanol_kg"),
        }
        ranked_summary = []
        ranked_lines   = "N/A (EH+Fermentation run)"

        flags.append(_eff_flag(eh.get("overall_yield_pct"),   "Overall EH Yield"))
        flags.append(_eff_flag(ferm.get("efficiency_pct"),    "Fermentation Efficiency"))
        flags.append(_eff_flag(overall.get("efficiency_pct"), "Overall Process Efficiency"))

    if warning:
        flags.insert(0, f"⚠ Biomass warning: {warning}")
    flags = [f for f in flags if f]

    # ── Haiku summary ────────────────────────────────────────────────────────
    metrics_str = "\n".join(
        f"  {k}: {v}"
        for k, v in key_metrics.items()
        if v is not None and k not in ("conditions", "best_efficiency_colour", "eh_colour",
                                        "ferm_colour", "overall_colour")
    )
    flags_str = "\n".join(flags) if flags else "No flags — all efficiencies within acceptable range."

    # Include ranked summary in prompt for CBP
    ranked_section = (
        f"\nRanked strain summary (best → worst, controls excluded):\n{ranked_lines}"
        if exp_type == "cbp" else ""
    )

    prompt = f"""Write a concise bioprocess run summary for Diana at ErgBio.

Run: {run_name}
Biomass: {biomass}
Type: {exp_type.upper()}

Key metrics:
{metrics_str}

Efficiency flags:
{flags_str}
{ranked_section}

Write 3-5 sentences. Include the headline efficiency number(s), mention any below-60% flags explicitly, call out the best-performing strain (CBP only), and note the biomass type. Be direct and scientific."""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=450,
        messages=[{"role": "user", "content": prompt}],
    )
    summary = message.content[0].text

    return {
        "success":        True,
        "run_name":       run_name,
        "summary":        summary,
        "flags":          flags,
        "key_metrics":    key_metrics,
        "ranked_summary": ranked_summary,
    }
