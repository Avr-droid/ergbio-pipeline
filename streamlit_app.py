import streamlit as st
import pandas as pd
from datetime import date
from tools.save_run import (save_run, BIOMASS_PRESETS, VESSEL_VOLS, VESSEL_LABELS,
                             _calc_cbp, _calc_eh, _eff_colour)
from tools.drive_reader import load_all_runs, delete_run
from tools.hplc_parser import parse_hplc_file
import tempfile, os

st.set_page_config(page_title="ErgBio Bioprocess Calculator", page_icon="🌿", layout="wide")

st.markdown("""
<style>
.block-container { max-width: 1400px; padding: 2rem 2rem 4rem 2rem; }
div.stButton > button[kind="primary"] {
    background-color: #1e5c3a !important; border-color: #1e5c3a !important;
    color: #fff !important; font-weight: 700; font-size: 1rem;
}
div.stButton > button[kind="primary"]:hover { background-color: #2d7a52 !important; }
div.stButton > button:not([kind="primary"]) {
    border: 1.5px solid #2d7a52 !important; color: #2d7a52 !important; font-weight: 600;
}
.stTabs [data-baseweb="tab"] { padding: 10px 22px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# ── PALETTE ───────────────────────────────────────────────────────────────────
_PAL = {
    "green":   {"bg": "#edfaf3", "border": "#2d9e5f", "stripe": "#2d9e5f"},
    "amber":   {"bg": "#fffbee", "border": "#c9940a", "stripe": "#c9940a"},
    "red":     {"bg": "#fff0f0", "border": "#d93025", "stripe": "#d93025"},
    "neutral": {"bg": "#ffffff", "border": "#d4ddd6", "stripe": "#d4ddd6"},
}

# ── COMPONENTS ────────────────────────────────────────────────────────────────
def kpi_card(value, label, is_pct=False, highlight=False, unit="", context=None, tooltip=None):
    if value is None:
        disp, cls = "—", "neutral"
    else:
        disp = f"{value:.1f}%" if is_pct else (f"{value:.1f} {unit}" if unit else f"{value:.1f}")
        cls  = _eff_colour(value) if is_pct else "neutral"
    p   = _PAL[cls]
    bg  = p["bg"] if is_pct else "#ffffff"
    tip = f' title="{tooltip}"' if tooltip else ""
    ctx = (f'<div style="font-size:0.74rem;color:#8a9e90;margin-top:5px;">{context}</div>'
           if context else "")
    if is_pct:
        lw  = "7px" if highlight else "5px"
        bdr = (f"border-top:1px solid #dde6de;border-right:1px solid #dde6de;"
               f"border-bottom:1px solid #dde6de;border-left:{lw} solid {p['stripe']};")
    else:
        bdr = "border:1px solid #d4ddd6;"
    return (
        f'<div{tip} style="background:{bg};{bdr}border-radius:8px;padding:14px 16px;text-align:center;">'
        f'<div style="font-size:1.75rem;font-weight:800;color:#1a2e22;line-height:1.1;">{disp}</div>'
        f'<div style="font-size:0.78rem;color:#5a6b62;text-transform:uppercase;'
        f'letter-spacing:0.06em;margin-top:6px;font-weight:500;">{label}</div>'
        f'{ctx}</div>'
    )

def section_header(title, subtitle=None):
    sub = (f'<span style="font-size:0.8rem;font-weight:400;color:#8a9e90;margin-left:8px;">'
           f'{subtitle}</span>') if subtitle else ""
    st.markdown(
        f'<div style="border-left:4px solid #2d7a52;padding-left:10px;margin:22px 0 10px 0;">'
        f'<span style="font-size:1rem;font-weight:700;color:#e8f0ea;">{title}</span>{sub}</div>',
        unsafe_allow_html=True)

def colour_key():
    st.markdown(
        '<div style="display:flex;gap:24px;align-items:center;padding:10px 16px;'
        'background:#1e2e22;border:1px solid #2d4a35;border-radius:6px;margin-bottom:10px;">'
        '<span style="font-size:0.88rem;font-weight:700;color:#7ecfa0;">Efficiency key:</span>'
        '<span style="font-size:0.88rem;color:#c8d8cc;">'
        '<span style="display:inline-block;width:12px;height:12px;background:#2d9e5f;'
        'border-radius:2px;margin-right:5px;vertical-align:middle;"></span>≥ 80% — Good</span>'
        '<span style="font-size:0.88rem;color:#c8d8cc;">'
        '<span style="display:inline-block;width:12px;height:12px;background:#c9940a;'
        'border-radius:2px;margin-right:5px;vertical-align:middle;"></span>60–79% — Acceptable</span>'
        '<span style="font-size:0.88rem;color:#c8d8cc;">'
        '<span style="display:inline-block;width:12px;height:12px;background:#d93025;'
        'border-radius:2px;margin-right:5px;vertical-align:middle;"></span>< 60% — Below threshold</span>'
        '</div>', unsafe_allow_html=True)

def theo_bar(theo):
    items = [("Glucose", theo.get("glucose_kg", 0)), ("Xylose", theo.get("xylose_kg", 0)),
             ("Arabinose", theo.get("arabinose_kg", 0)),
             ("Total Sugars", theo.get("total_sugars_kg", 0)), ("Ethanol", theo.get("ethanol_kg", 0))]
    parts = "".join(
        f'<span style="padding:0 16px;border-right:1px solid #c0d4c8;">'
        f'<span style="font-size:0.82rem;color:#5a7a62;">{n} </span>'
        f'<strong style="font-size:0.95rem;color:#1a2e22;">{v:.1f} kg</strong></span>'
        for n, v in items)
    st.markdown(
        f'<div style="background:#f4f8f5;border:1px solid #c8ddd0;border-radius:6px;'
        f'padding:10px 18px;display:flex;flex-wrap:wrap;align-items:center;gap:2px;margin-bottom:12px;">'
        f'<strong style="font-size:0.82rem;color:#2d7a52;margin-right:12px;white-space:nowrap;">'
        f'Theoretical max (100%):</strong>{parts}</div>', unsafe_allow_html=True)

def headline_banner(value, label, target=80):
    cls  = _eff_colour(value) if value is not None else "neutral"
    p    = _PAL[cls]
    disp = f"{value:.1f}%" if value is not None else "—"
    pct  = min(float(value or 0), 100)
    tag  = {"green":"GOOD","amber":"ACCEPTABLE","red":"BELOW THRESHOLD","neutral":"—"}[cls]
    bar  = (
        f'<div style="margin:14px 0 0 0;">'
        f'<div style="background:#d8e4dc;border-radius:5px;height:10px;position:relative;">'
        f'<div style="background:{p["stripe"]};width:{pct}%;height:100%;border-radius:5px;"></div>'
        f'<div style="position:absolute;top:-4px;left:{pct}%;width:2px;height:18px;'
        f'background:{p["border"]};border-radius:1px;transform:translateX(-50%);"></div>'
        f'<div style="position:absolute;top:-24px;left:{pct}%;transform:translateX(-50%);'
        f'background:{p["border"]};color:white;font-size:0.66rem;font-weight:700;'
        f'padding:2px 6px;border-radius:3px;white-space:nowrap;">{disp}</div>'
        f'<div style="position:absolute;top:-4px;left:{target}%;width:2px;height:18px;'
        f'background:#666;border-radius:1px;transform:translateX(-50%);"></div>'
        f'</div>'
        f'<div style="position:relative;height:20px;margin-top:5px;font-size:0.7rem;color:#7a8a80;">'
        f'<span style="position:absolute;left:0;">0%</span>'
        f'<span style="position:absolute;left:{target}%;transform:translateX(-50%);'
        f'white-space:nowrap;">▲ Target {target}%</span>'
        f'<span style="position:absolute;right:0;">100%</span>'
        f'</div></div>')
    st.markdown(
        f'<div style="background:{p["bg"]};border:2px solid {p["border"]};'
        f'border-left:8px solid {p["stripe"]};border-radius:8px;padding:20px 24px;margin-bottom:14px;">'
        f'<div style="display:flex;align-items:flex-start;justify-content:space-between;">'
        f'<div><div style="font-size:0.72rem;color:#6c7a72;text-transform:uppercase;'
        f'letter-spacing:0.08em;font-weight:600;">{label}</div>'
        f'<div style="font-size:2.6rem;font-weight:900;color:#1a2e22;line-height:1.05;">{disp}</div></div>'
        f'<div style="background:{p["border"]};color:white;padding:4px 14px;border-radius:20px;'
        f'font-size:0.72rem;font-weight:700;letter-spacing:0.06em;margin-top:4px;">{tag}</div>'
        f'</div>{bar}</div>', unsafe_allow_html=True)

def process_insight(eh, ferm):
    eh_ov   = eh.get("overall_yield_pct",  0) or 0
    ferm_ef = ferm.get("efficiency_pct",   0) or 0
    if eh_ov < ferm_ef:
        msg = (f"Likely primary bottleneck: <strong>enzymatic hydrolysis</strong> "
               f"({eh_ov:.1f}% overall sugar yield vs {ferm_ef:.1f}% fermentation efficiency). "
               f"Consider increasing enzyme loading, extending EH time, or optimising pH/temperature.")
    elif ferm_ef < eh_ov:
        msg = (f"Likely primary bottleneck: <strong>fermentation</strong> "
               f"({ferm_ef:.1f}% efficiency vs {eh_ov:.1f}% EH yield). "
               f"Sugars released but not fully converted — check inoculum health, pH, or inhibitors.")
    else:
        msg = "EH and fermentation efficiencies are similar — both stages may benefit from optimisation."
    st.markdown(
        f'<div style="background:#1a2e22;border:1px solid #2d4a35;border-radius:8px;'
        f'padding:14px 18px;margin-top:16px;">'
        f'<div style="font-size:0.72rem;font-weight:700;color:#7ecfa0;text-transform:uppercase;'
        f'letter-spacing:0.07em;margin-bottom:6px;">Process Insight</div>'
        f'<div style="font-size:0.88rem;color:#c8d8cc;line-height:1.5;">{msg}</div></div>',
        unsafe_allow_html=True)

# ── TABS ──────────────────────────────────────────────────────────────────────
tab_new, tab_history, tab_compare = st.tabs(["＋ New Run", "📋 Run History", "⚖ Compare"])

# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — NEW RUN
# ═════════════════════════════════════════════════════════════════════════════
with tab_new:
    st.markdown("## New Bioprocess Run")
    exp_type = st.radio("Experiment Type", ["EH + Fermentation", "CBP"], horizontal=True, key="exp_type")
    is_cbp   = exp_type == "CBP"

    # ── Run Details ──
    with st.expander("Run Details", expanded=True):
        c1, c2, c3 = st.columns(3)
        run_id       = c1.text_input("Run ID",           placeholder="e.g. FR008")
        run_date     = c2.date_input("Date Started",     value=date.today())
        run_vessel   = c3.text_input("Location / Scale", placeholder="e.g. Albany — 1200 L")
        c4, c5       = st.columns(2)
        run_operator = c4.text_input("Operator(s)",      placeholder="e.g. Diana, Ares")
        run_notes    = c5.text_input("Notes",            placeholder="e.g. Rice Straw CBP strain screen")

    # ── Biomass Composition (§3.2) ──
    with st.expander("Biomass Composition", expanded=True):
        preset_key = st.selectbox(
            "Load NREL preset:",
            ["— select —"] + list(BIOMASS_PRESETS.keys()),
            format_func=lambda k: f"{BIOMASS_PRESETS[k]['name']} ({k})" if k in BIOMASS_PRESETS else k,
        )
        preset = BIOMASS_PRESETS.get(preset_key, {})
        if preset.get("warning"):
            st.warning(f"⚠ {preset['warning']}")

        st.caption("Required for calculation")
        c1, c2, c3 = st.columns(3)
        cel  = c1.number_input("Cellulose (%)",    value=float(preset.get("cellulose",  0.0)), step=0.01, format="%.2f")
        xyl  = c2.number_input("Xylan (%)",        value=float(preset.get("xylan",      0.0)), step=0.01, format="%.2f")
        ara  = c3.number_input("Arabinose (%)",    value=float(preset.get("arabinose",  0.0)), step=0.01, format="%.2f")

        st.caption("Informational — recorded in run, used in mass balance add-ons")
        c4, c5, c6 = st.columns(3)
        lig  = c4.number_input("Lignin (%)",       value=float(preset.get("lignin",     0.0)), step=0.01, format="%.2f")
        ash  = c5.number_input("Ash (%)",          value=float(preset.get("ash",        0.0)), step=0.01, format="%.2f")
        ext  = c6.number_input("Extractives (%)",  value=float(preset.get("extractives",0.0)), step=0.01, format="%.2f")
        c7, c8, c9 = st.columns(3)
        wat  = c7.number_input("Structural Water (%)",  value=float(preset.get("water",      0.0)), step=0.01, format="%.2f")
        esol = c8.number_input("Ethanol Solubles (%)",  value=float(preset.get("ethanolSol", 0.0)), step=0.01, format="%.2f")
        acid = c9.number_input("Acetic Acid (%)",       value=float(preset.get("aceticAcid", 0.0)), step=0.01, format="%.2f")
        clos = st.number_input("Mass Closure (%)",      value=float(preset.get("massClosure",0.0)), step=0.01, format="%.2f")

        # §3.2: Flag mass closure <85%
        if clos > 0 and clos < 85:
            st.warning(f"⚠ Mass closure {clos:.2f}% is below the 85% QC threshold. Investigate before using for final calculations.")

    # ── Biomass Lots (§3.3) ──
    with st.expander("Biomass Lots", expanded=True):
        if "lots" not in st.session_state:
            st.session_state.lots = [{"lot": "", "wet_kg": 0.0, "moisture": 0.0}]
        for i, lot in enumerate(st.session_state.lots):
            c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
            st.session_state.lots[i]["lot"]      = c1.text_input("Lot ID",         value=lot["lot"],      key=f"lot_{i}")
            st.session_state.lots[i]["wet_kg"]   = c2.number_input("Wet mass (kg)",value=lot["wet_kg"],   key=f"wet_{i}", step=0.1, format="%.2f")
            st.session_state.lots[i]["moisture"] = c3.number_input("Moisture (%)", value=lot["moisture"], key=f"moi_{i}", step=0.1, format="%.1f")
            odw_i = lot["wet_kg"] * (1 - lot["moisture"] / 100)
            c4.metric("ODW (kg)", f"{odw_i:.2f}")
        if st.button("＋ Add Lot"):
            st.session_state.lots.append({"lot": "", "wet_kg": 0.0, "moisture": 0.0})
            st.rerun()
        total_odw = sum(l["wet_kg"] * (1 - l["moisture"] / 100) for l in st.session_state.lots)
        st.metric("Total ODW (kg)", f"{total_odw:.2f}")

    # ── Process Parameters (§3.4) ──
    with st.expander("Process Parameters", expanded=True):
        c1, c2, c3 = st.columns(3)
        solid_loading  = c1.number_input("Solid Loading (%)*", value=10.0, step=0.5, format="%.1f",
                                          help="Required. Slurry volume auto-calculates from this.")
        ferm_temp      = c2.number_input("Fermentation Temp (°C)", value=0.0, step=0.5, format="%.1f")
        ferm_duration  = c3.number_input("Fermentation Duration (hr)", value=0.0, step=1.0, format="%.0f")

        if not is_cbp:
            st.caption("EH conditions (recorded only)")
            c4, c5, c6, c7 = st.columns(4)
            enzyme_product  = c4.text_input("Enzyme Product", placeholder="e.g. Cellic CTec3")
            enzyme_loading  = c5.number_input("Enzyme Loading (mg/g ODW)", value=0.0, step=0.5, format="%.1f")
            eh_temp         = c6.number_input("EH Temp (°C)",              value=0.0, step=0.5, format="%.1f")
            eh_duration     = c7.number_input("EH Duration (hr)",          value=0.0, step=1.0, format="%.0f")
        else:
            enzyme_product = enzyme_loading = eh_temp = eh_duration = None

        # Auto-calculate slurry volume
        slurry_vol_calc = (total_odw / (solid_loading / 100)) if solid_loading > 0 and total_odw > 0 else 0
        st.info(f"Auto-calculated slurry volume: **{slurry_vol_calc:.1f} L** "
                f"(Total ODW {total_odw:.2f} kg ÷ {solid_loading:.1f}% solid loading)")

    # ── CBP Inputs (§3.6) ──
    if is_cbp:
        with st.expander("CBP Setup", expanded=True):
            c1, c2, c3 = st.columns(3)
            vessel_type_key = c1.selectbox(
                "Vessel Type",
                list(VESSEL_VOLS.keys()),
                format_func=lambda k: VESSEL_LABELS.get(k, k)
            )
            # Auto-fill working volume from vessel type (§6.2)
            default_wv = VESSEL_VOLS.get(vessel_type_key) or 50.0
            working_vol = c2.number_input("Working Volume (mL)", value=float(default_wv), step=5.0, format="%.0f")
            final_tp    = c3.selectbox("Final Timepoint", [24, 48, 72, 96, 120, 144, 168],
                                        index=3, format_func=lambda h: f"T{h}h")
            c4, c5, c6 = st.columns(3)
            seed_stages      = c4.number_input("Seed Stages",      value=2, step=1, min_value=1)
            inoculum_details = c5.text_input("Inoculum Details",   placeholder="e.g. 10% v/v OD600=1.2")
            biomass_per_vessel_g = c6.number_input("Biomass/Vessel (g ODW)", value=0.0, step=0.1, format="%.2f",
                                                    help="If provided, enables per-vessel theoretical ethanol calc.")

            st.caption("Upload HPLC files — values auto-populate conditions below, or enter manually")
            uploaded_eth = st.file_uploader("Ethanol HPLC (.xlsx/.csv)", type=["xlsx","csv"], key="cbp_eth")
            uploaded_glc = st.file_uploader("Glucose HPLC (.xlsx/.csv)", type=["xlsx","csv"], key="cbp_glc")
            uploaded_xyl = st.file_uploader("Xylose HPLC (.xlsx/.csv)",  type=["xlsx","csv"], key="cbp_xyl")

            parsed_eth, parsed_glc, parsed_xyl = {}, {}, {}
            for uploaded, label, store_key in [(uploaded_eth,"Ethanol","eth"),
                                               (uploaded_glc,"Glucose","glc"),
                                               (uploaded_xyl,"Xylose","xyl")]:
                if uploaded:
                    suffix = ".xlsx" if uploaded.name.endswith(".xlsx") else ".csv"
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                        tmp.write(uploaded.read()); tmp_path = tmp.name
                    result = parse_hplc_file(tmp_path); os.unlink(tmp_path)
                    if result["success"]:
                        if store_key == "eth": parsed_eth = result
                        if store_key == "glc": parsed_glc = result
                        if store_key == "xyl": parsed_xyl = result
                        st.success(f"✓ {label} parsed — timepoints: {result['timepoints']}")
                    else:
                        st.error(f"✗ {label}: {result['error']}")

            st.caption("Conditions — one row per strain/condition (§3.6.1)")
            if "conditions" not in st.session_state:
                st.session_state.conditions = [
                    {"name":"Control","enzyme":0.0,"reps":3,"eth0":0.0,"ethF":0.0,
                     "glc":0.0,"xyl":0.0,"ctrl":True}
                ]
            for i, cond in enumerate(st.session_state.conditions):
                cols = st.columns([2, 1.2, 0.8, 1.2, 1.2, 1.2, 1.2, 1.2, 0.8])
                st.session_state.conditions[i]["name"]   = cols[0].text_input("Condition",      key=f"cn_{i}", value=cond["name"])
                st.session_state.conditions[i]["enzyme"] = cols[1].number_input("Enzyme (mg/g)",key=f"ce_{i}", value=float(cond.get("enzyme",0) or 0), step=0.5, format="%.1f")
                st.session_state.conditions[i]["reps"]   = cols[2].number_input("Reps",         key=f"cr_{i}", value=int(cond.get("reps",3)), step=1, min_value=1)
                eth0_v = float(parsed_eth.get("t0_values",{}).get(cond["name"], cond.get("eth0",0)) or 0)
                ethF_v = float(parsed_eth.get("final_values",{}).get(cond["name"], cond.get("ethF",0)) or 0)
                st.session_state.conditions[i]["eth0"]   = cols[3].number_input("EtOH T0 (g/L)", key=f"e0_{i}", value=eth0_v, step=0.01, format="%.2f")
                st.session_state.conditions[i]["ethF"]   = cols[4].number_input(f"EtOH T{final_tp}h (g/L)", key=f"ef_{i}", value=ethF_v, step=0.01, format="%.2f")
                # Live Net EtOH (auto-calc, read-only display)
                net_live = st.session_state.conditions[i]["ethF"] - st.session_state.conditions[i]["eth0"]
                cols[5].metric("Net EtOH (g/L)", f"{net_live:.2f}")
                st.session_state.conditions[i]["glc"]    = cols[6].number_input("Res. Glc (g/L)", key=f"rg_{i}", value=float(cond.get("glc",0)), step=0.01, format="%.2f")
                st.session_state.conditions[i]["xyl"]    = cols[7].number_input("Res. Xyl (g/L)", key=f"rx_{i}", value=float(cond.get("xyl",0)), step=0.01, format="%.2f")
                st.session_state.conditions[i]["ctrl"]   = cols[8].checkbox("Ctrl",               key=f"cc_{i}", value=bool(cond.get("ctrl",False)))
            if st.button("＋ Add Condition"):
                st.session_state.conditions.append(
                    {"name":"","enzyme":0.0,"reps":3,"eth0":0.0,"ethF":0.0,"glc":0.0,"xyl":0.0,"ctrl":False})
                st.rerun()

    # ── EH + Fermentation Inputs (§3.5) ──
    else:
        with st.expander("Enzymatic Hydrolysis Results (HPLC)", expanded=True):
            c1, c2, c3, c4 = st.columns(4)
            eh_glc  = c1.number_input("Glucose (g/L)",       value=0.0, step=0.1, format="%.2f")
            eh_xyl  = c2.number_input("Xylose (g/L)",        value=0.0, step=0.1, format="%.2f")
            eh_arab = c3.number_input("Arabinose (g/L)",      value=0.0, step=0.1, format="%.2f")
            eh_vol  = c4.number_input(f"Volume (L) — defaults to {slurry_vol_calc:.1f} L if 0",
                                       value=0.0, step=1.0, format="%.1f",
                                       help="Leave 0 to use auto-calculated slurry volume")

        with st.expander("Fermentation Results", expanded=True):
            c1, c2 = st.columns(2)
            ferm_eth_gL = c1.number_input("Ethanol produced (g/L)", value=0.0, step=0.1, format="%.2f")
            ferm_eth_kg = c2.number_input("Ethanol produced — direct (kg)",  value=0.0, step=0.1, format="%.3f",
                                           help="If provided, overrides g/L × volume (§3.5)")
            c3, c4 = st.columns(2)
            ferm_vol    = c3.number_input(f"Fermentation vol (L) — defaults to {slurry_vol_calc:.1f} L if 0",
                                           value=0.0, step=1.0, format="%.1f")
            st.caption("Residual sugars (g/L) — for QC KPIs")
            c5, c6, c7 = st.columns(3)
            ferm_res_glc  = c5.number_input("Residual Glucose (g/L)",    value=0.0, step=0.1, format="%.2f")
            ferm_res_xyl  = c6.number_input("Residual Xylose (g/L)",     value=0.0, step=0.1, format="%.2f")
            ferm_res_arab = c7.number_input("Residual Arabinose (g/L)",  value=0.0, step=0.1, format="%.2f")

    # ── Calculate / Save ──
    st.markdown("---")
    col_calc, col_save = st.columns(2)
    calc_clicked = col_calc.button("Calculate Results", type="primary", use_container_width=True)

    if calc_clicked:
        if total_odw == 0:
            st.error("Enter at least one biomass lot with wet weight > 0.")
        elif cel == 0:
            st.error("Cellulose % is required for theoretical max calculation.")
        elif solid_loading == 0:
            st.error("Solid Loading % is required (Process Parameters).")
        else:
            # Build run data dict — includes all composition values so calc uses user-entered values
            run_data = {
                "run_name": run_id or "Unnamed Run", "date": str(run_date),
                "vessel": run_vessel, "operator": run_operator, "notes": run_notes,
                "experiment_type": "cbp" if is_cbp else "eh",
                "biomass_type": preset_key if preset_key in BIOMASS_PRESETS else "",
                "total_odw_kg": total_odw,
                "lots": [{"lot": l["lot"], "wet": l["wet_kg"], "moist": l["moisture"],
                          "odw": l["wet_kg"] * (1 - l["moisture"]/100)}
                         for l in st.session_state.lots],
                # Pass user-entered composition (overrides preset in calc)
                "cellulose_pct": cel, "xylan_pct": xyl, "arabinose_pct": ara,
                "lignin_pct": lig, "ash_pct": ash, "extractives_pct": ext,
                "water_pct": wat, "ethanolSol_pct": esol, "aceticAcid_pct": acid,
                "massClosure_pct": clos,
                # Process params
                "solid_loading_pct": solid_loading,
                "ferm_temp_c": ferm_temp or None, "ferm_duration_hr": ferm_duration or None,
            }
            if is_cbp:
                run_data.update({
                    "vessel_type": vessel_type_key, "working_vol_ml": working_vol,
                    "final_tp": final_tp, "seed_stages": seed_stages,
                    "inoculum_details": inoculum_details or None,
                    "biomass_per_vessel_g": biomass_per_vessel_g or None,
                    "conditions": st.session_state.conditions,
                })
                calcs = _calc_cbp(run_data)
            else:
                run_data.update({
                    "enzyme_product": enzyme_product or None,
                    "enzyme_loading_mg_g": enzyme_loading or None,
                    "eh_temp_c": eh_temp or None, "eh_duration_hr": eh_duration or None,
                    "eh_glc_gL": eh_glc, "eh_xyl_gL": eh_xyl, "eh_arab_gL": eh_arab,
                    "eh_vol_l": eh_vol or None,     # None → defaults to slurry vol in calc
                    "ferm_eth_gL": ferm_eth_gL,
                    "ferm_eth_kg": ferm_eth_kg or None,   # direct kg override
                    "ferm_vol_l": ferm_vol or None,         # None → defaults to slurry vol
                    "ferm_res_glc_gL": ferm_res_glc, "ferm_res_xyl_gL": ferm_res_xyl,
                    "ferm_res_arab_gL": ferm_res_arab,
                })
                calcs = _calc_eh(run_data)
            st.session_state["current_run"]   = run_data
            st.session_state["current_calcs"] = calcs

    # ── RESULTS ──────────────────────────────────────────────────────────
    if "current_calcs" in st.session_state:
        calcs    = st.session_state["current_calcs"]
        run_data = st.session_state["current_run"]
        theo     = calcs.get("theoretical", {})

        st.markdown("---")
        st.markdown("## Calculation Results")
        colour_key()
        theo_bar(theo)

        if is_cbp:
            headline_banner(calcs.get("best_efficiency"), f"Best CBP Efficiency — T{run_data.get('final_tp',96)}h")
            section_header("Conditions")
            cond_rows = []
            for c in calcs.get("conditions", []):
                cond_rows.append({
                    "Condition":  c.get("name","—"), "Enzyme (mg/g)": c.get("enzyme","—"),
                    "Reps": c.get("reps","—"),
                    "EtOH T0 (g/L)": c.get("eth0"), f"EtOH T{run_data.get('final_tp',96)}h (g/L)": c.get("ethF"),
                    "Net EtOH (g/L)": c.get("net_ethanol_gL"),
                    "Net EtOH/vessel (g)": c.get("net_ethanol_g"),
                    "CBP Efficiency %": c.get("cbp_efficiency"),
                    "Control": c.get("ctrl",False),
                })
            st.dataframe(pd.DataFrame(cond_rows), use_container_width=True)

            # Ranked summary (non-controls, best→worst)
            ranked = calcs.get("ranked_summary", [])
            if ranked:
                section_header("Ranked Strain Summary")
                st.dataframe(pd.DataFrame([{
                    "Rank": r["rank"], "Condition": r["condition"],
                    "Net EtOH (g/L)": r["net_ethanol_gL"],
                    "CBP Efficiency %": r["cbp_efficiency_pct"],
                    "Below 60% Threshold": "⚠ Yes" if r["below_threshold"] else "—",
                } for r in ranked]), use_container_width=True)

        else:
            eh      = calcs.get("enzymatic_hydrolysis", {})
            ferm    = calcs.get("fermentation", {})
            overall = calcs.get("overall", {})
            theo_eth    = theo.get("ethanol_kg", 0)
            actual_eth  = ferm.get("actual_ethanol_kg", 0)
            shortfall   = max((theo_eth or 0) - (actual_eth or 0), 0)
            recovery    = overall.get("efficiency_pct", 0)

            headline_banner(overall.get("efficiency_pct"), "Overall Process Efficiency")

            section_header("Enzymatic Hydrolysis", subtitle="(EH)")
            c1, c2, c3 = st.columns(3)
            c1.markdown(kpi_card(eh.get("glucose_yield_pct"), "Glucose EH Yield", is_pct=True,
                tooltip="(Actual glucose kg / Theoretical glucose kg) × 100"), unsafe_allow_html=True)
            c2.markdown(kpi_card(eh.get("xylose_yield_pct"), "Xylose EH Yield", is_pct=True,
                tooltip="(Actual xylose kg / Theoretical xylose kg) × 100"), unsafe_allow_html=True)
            c3.markdown(kpi_card(eh.get("overall_yield_pct"), "Overall EH Yield", is_pct=True, highlight=True,
                tooltip="(Actual total sugars kg / Theoretical total sugars kg) × 100"), unsafe_allow_html=True)

            section_header("Fermentation")
            c4, c5, c6 = st.columns(3)
            c4.markdown(kpi_card(ferm.get("efficiency_pct"), "Fermentation Efficiency", is_pct=True, highlight=True,
                tooltip="(Actual ethanol kg / Theoretical ethanol from EH sugars) × 100"), unsafe_allow_html=True)
            c5.markdown(kpi_card(actual_eth, "Actual Ethanol", unit="kg",
                context=f"{actual_eth:.1f} kg of {theo_eth:.1f} kg theoretical ({recovery:.1f}% recovery)",
                tooltip="EtOH (g/L) × fermentation volume (L) ÷ 1000 — or direct kg entry if provided"),
                unsafe_allow_html=True)
            c6.markdown(kpi_card(ferm.get("residual_sugars_kg"), "Residual Sugars", unit="kg",
                context="Glucose + xylose + arabinose remaining post-fermentation",
                tooltip="Sum of residual glucose, xylose, arabinose (g/L) × ferm volume ÷ 1000"),
                unsafe_allow_html=True)

            section_header("Material Outputs")
            c7, c8, c9 = st.columns(3)
            c7.markdown(kpi_card(theo_eth, "Theoretical Max Ethanol", unit="kg",
                context="Maximum possible at 100% process efficiency",
                tooltip="Theoretical total sugars × 0.511 (Gay-Lussac stoichiometric yield)"),
                unsafe_allow_html=True)
            c8.markdown(kpi_card(shortfall, "Ethanol Shortfall", unit="kg",
                context=f"{shortfall:.1f} kg unrealised potential",
                tooltip="Theoretical max ethanol minus actual ethanol produced"),
                unsafe_allow_html=True)
            c9.markdown(kpi_card(recovery, "Ethanol Recovery", unit="%",
                context="Actual ÷ theoretical × 100 (= overall process efficiency)",
                tooltip="(Actual ethanol / Theoretical max ethanol) × 100"),
                unsafe_allow_html=True)

            process_insight(eh, ferm)

        st.markdown("")
        if col_save.button("Save to Drive", use_container_width=True):
            with st.spinner("Saving..."):
                result = save_run(st.session_state["current_run"])
            if result.get("success"):
                st.success(f"✅ Saved — file ID: {result.get('drive_file_id')}")
                if "runs_cache" in st.session_state: del st.session_state["runs_cache"]
            else:
                st.error(f"❌ Save failed: {result.get('error')}")

# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — RUN HISTORY (§3.8)
# ═════════════════════════════════════════════════════════════════════════════
with tab_history:
    st.markdown("## Run History")
    if st.button("Refresh", key="refresh_history"):
        if "runs_cache" in st.session_state: del st.session_state["runs_cache"]
    if "runs_cache" not in st.session_state:
        with st.spinner("Loading from Drive..."):
            try: st.session_state["runs_cache"] = load_all_runs()
            except Exception as e:
                st.error(f"Could not load runs: {e}")
                st.session_state["runs_cache"] = []
    runs = st.session_state.get("runs_cache", [])
    if not runs:
        st.info("No runs saved yet. Calculate and save a run to see it here.")
    else:
        rows = []
        for r in runs:
            calcs = r.get("calcs", {}); rtype = r.get("type","").upper()
            overall = calcs.get("best_efficiency") if rtype=="CBP" else calcs.get("overall",{}).get("efficiency_pct")
            # §13 add-on #8: Theoretical Ethanol column in History table
            theo_eth = calcs.get("theoretical",{}).get("ethanol_kg")
            rows.append({
                "Run ID": r.get("name","—"), "Date": r.get("date","—"), "Type": rtype,
                "Biomass": r.get("biomassType", r.get("biomass_type","—")),
                "Operator": r.get("operator","—"),
                "Best/Overall Eff %": f"{overall:.1f}%" if overall is not None else "—",
                "Theo Ethanol (kg)": f"{theo_eth:.3f}" if theo_eth is not None else "—",
                "_id": r.get("_driveFileId"),
            })
        st.dataframe(pd.DataFrame(rows).drop(columns=["_id"]), use_container_width=True)
        run_names = [r.get("name", f"Run {i}") for i, r in enumerate(runs)]
        selected  = st.selectbox("View run details:", ["— select —"] + run_names)
        if selected != "— select —":
            idx = run_names.index(selected)
            st.json(runs[idx].get("calcs", {}))
            if st.button(f"Delete '{selected}'", key=f"del_{idx}"):
                fid = runs[idx].get("_driveFileId")
                if fid and delete_run(fid):
                    st.success("Deleted."); del st.session_state["runs_cache"]; st.rerun()
                else: st.error("Delete failed.")

# ═════════════════════════════════════════════════════════════════════════════
# TAB 3 — COMPARE (§3.8)
# ═════════════════════════════════════════════════════════════════════════════
with tab_compare:
    st.markdown("## Compare Runs")
    runs = st.session_state.get("runs_cache", [])
    if not runs:
        st.info("Load runs in Run History first.")
    else:
        run_names = [r.get("name", f"Run {i}") for i, r in enumerate(runs)]
        selected  = st.multiselect("Select runs to compare:", run_names)
        if len(selected) >= 2:
            rows = []
            for n in selected:
                r = runs[run_names.index(n)]; calcs = r.get("calcs",{}); rtype = r.get("type","").upper()
                theo = calcs.get("theoretical",{})
                row  = {
                    "Run ID": r.get("name"), "Date": r.get("date"), "Type": rtype,
                    "Biomass": r.get("biomassType", r.get("biomass_type","")),
                    "Operator": r.get("operator",""),
                    "Total ODW (kg)": r.get("totalODW", r.get("total_odw_kg","")),
                    "Solid Loading (%)": r.get("params",{}).get("solidLoad",""),
                    "Theo Sugars (kg)": theo.get("total_sugars_kg",""),
                    "Theo Ethanol (kg)": theo.get("ethanol_kg",""),
                }
                if rtype == "CBP":
                    row["Best CBP Eff %"]  = calcs.get("best_efficiency")
                else:
                    row["EH Overall %"]   = calcs.get("enzymatic_hydrolysis",{}).get("overall_yield_pct")
                    row["Ferm Eff %"]     = calcs.get("fermentation",{}).get("efficiency_pct")
                    row["Overall Eff %"]  = calcs.get("overall",{}).get("efficiency_pct")
                    row["Actual EtOH (kg)"] = calcs.get("overall",{}).get("actual_ethanol_kg")
                rows.append(row)
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        elif len(selected) == 1:
            st.info("Select at least 2 runs to compare.")
