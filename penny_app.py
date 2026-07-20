"""
penny_app.py — ErgBio Research Assistant (Penny Agent)
Run with:  streamlit run penny_app.py
"""

import streamlit as st
from agents.penny_agent import chat, load_run_records, list_enzymes

st.set_page_config(
    page_title="Penny — ErgBio Research Assistant",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
/* ── Layout: constrain content width ── */
section[data-testid="stMain"] .block-container {
    max-width: 1200px;
    padding: 1.2rem 2rem 2rem 2rem;
    margin: 0 auto;
}

/* ── Hide Streamlit chrome ── */
#MainMenu, footer { visibility: hidden; }

/* ── Compact header ── */
.penny-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 0.7rem 1.1rem;
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
    border-radius: 10px; margin-bottom: 0.75rem; color: white;
}
.penny-header-title { font-size: 1rem; font-weight: 700; margin: 0; }
.penny-header-sub   { font-size: 0.72rem; color: #94a3b8; margin: 0.15rem 0 0 0; }
.penny-header-sync  { font-size: 0.7rem; color: #64748b; }

/* ── Sources bar ── */
.sources-bar {
    display: flex; align-items: center; gap: 0.5rem;
    font-size: 0.74rem; color: #475569;
    background: #f8fafc; border: 1px solid #e2e8f0;
    border-radius: 8px; padding: 0.4rem 0.9rem;
    margin-bottom: 0.85rem;
}
.sources-bar strong { color: #0f172a; }
.sources-sep { color: #cbd5e1; }

/* ── Stat cards ── */
.stat-row  { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.7rem; margin-bottom: 1rem; }
.stat-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 0.8rem 1rem; }
.stat-card .sv  { font-size: 1.45rem; font-weight: 700; color: #0f172a; line-height: 1.1; }
.stat-card .sl  { font-size: 0.71rem; color: #64748b; margin-top: 0.15rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; }
.stat-card .ss  { font-size: 0.69rem; color: #94a3b8; margin-top: 0.2rem; }
.sv-warn { color: #d97706; }
.sv-ok   { color: #16a34a; }
.sv-muted { color: #94a3b8; }

/* ── Prompt section ── */
.cat-label {
    font-size: 0.67rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.09em; color: #94a3b8;
    margin: 0.9rem 0 0.4rem 0;
}

/* ── Prompt card buttons ── */
div[data-testid="stButton"] > button.prompt-btn {
    background: #fff; border: 1px solid #e2e8f0;
    border-radius: 9px; padding: 0.65rem 0.9rem;
    text-align: left; width: 100%;
    font-size: 0.83rem; font-weight: 600; color: #1e293b;
    transition: border-color 0.15s, background 0.15s;
    white-space: normal; line-height: 1.35;
}
div[data-testid="stButton"] > button.prompt-btn:hover {
    border-color: #93c5fd; background: #eff6ff; color: #1d4ed8;
}
/* Global button override for prompt cards */
.stButton > button {
    background: #fff; border: 1px solid #e2e8f0;
    border-radius: 9px; padding: 0.55rem 0.85rem;
    text-align: left; white-space: normal;
    font-size: 0.82rem; font-weight: 600; color: #1e293b;
    transition: border-color 0.15s, background 0.15s;
}
.stButton > button:hover {
    border-color: #93c5fd; background: #eff6ff; color: #1d4ed8;
}

/* ── Context chips ── */
.ctx-row { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.35rem; font-size: 0.73rem; }
.ctx-label { color: #64748b; font-weight: 600; }
.ctx-chip  { background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 20px; padding: 0.15rem 0.65rem; color: #1d4ed8; }

/* ── Tool call banners ── */
.tool-call {
    background: #f0fdf4; border-left: 3px solid #22c55e;
    padding: 0.35rem 0.8rem; border-radius: 0 6px 6px 0;
    font-size: 0.79rem; color: #166534; margin: 0.25rem 0;
}

/* ── QC drawer ── */
.qc-row { display: flex; gap: 0.4rem; align-items: flex-start; padding: 0.35rem 0; border-bottom: 1px solid #f1f5f9; font-size: 0.79rem; }
.qc-run   { font-weight: 700; color: #1e293b; min-width: 52px; }
.qc-issue { color: #475569; flex: 1; }
.qc-badge { font-size: 0.65rem; padding: 0.1rem 0.5rem; border-radius: 10px; font-weight: 600; white-space: nowrap; }
.qc-warn  { background: #fef3c7; color: #92400e; }
.qc-info  { background: #f1f5f9;  color: #64748b; }
.qc-crit  { background: #fee2e2; color: #991b1b; }

/* ── Sidebar nav ── */
.nav-section { font-size: 0.64rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.09em; color: #94a3b8; margin: 0.9rem 0 0.3rem 0; }
.nav-badge { background: #e2e8f0; color: #64748b; font-size: 0.65rem;
    padding: 0.05rem 0.45rem; border-radius: 10px; margin-left: 0.4rem; }
.conn-row { display: flex; justify-content: space-between; align-items: center;
    font-size: 0.74rem; padding: 0.18rem 0; }
.conn-name { color: #475569; }
.conn-ok   { color: #16a34a; font-weight: 600; }
.conn-soon { color: #94a3b8; }
.conn-off  { color: #f59e0b; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _tool_label(name: str, inputs: dict) -> str:
    labels = {
        "search_papers":          lambda i: f"Searched literature: \"{i.get('query','')}\"",
        "lookup_enzyme":          lambda i: f"Enzyme KB: {i.get('name','')}",
        "lookup_enzyme_kinetics": lambda i: f"BRENDA/ExPASy: {i.get('enzyme_name','')}",
        "lookup_chemical":        lambda i: f"PubChem: {i.get('compound_name','')}",
        "calculate_yields":       lambda i: "Calculated EH yield + fermentation efficiency",
        "get_biomass_info":       lambda i: f"Biomass data: {i.get('biomass_code','')}",
        "compare_runs":           lambda i: f"Compared runs: {', '.join(i.get('run_ids',[]))}",
        "get_run_detail":         lambda i: f"Full record: {i.get('run_id','')}",
    }
    fn = labels.get(name)
    return fn(inputs) if fn else f"Tool: {name}"


def _glucose_consumed(rec: dict):
    """Return (g/L consumed, final_timepoint). None if missing."""
    ts = rec.get("analyte_timeseries", {}).get("Glucose", {})
    if not ts:
        return None, None
    vals = {int(k): v for k, v in ts.items() if v is not None}
    if not vals:
        return None, None
    t0   = vals.get(0)
    tfin = vals.get(max(vals))
    if t0 is None or tfin is None:
        return None, None
    return round(t0 - tfin, 1), max(vals)


def _stats(records: dict):
    """Derive useful stats that actually have data."""
    latest  = sorted(records.keys())[-1] if records else "—"
    n_flags = sum(len(r.get("qc_flags", [])) for r in records.values())
    # best glucose consumption
    best_run, best_consumed = "—", None
    for rid, rec in records.items():
        consumed, _ = _glucose_consumed(rec)
        if consumed and (best_consumed is None or consumed > best_consumed):
            best_consumed, best_run = consumed, rid
    # data completeness: fields with real values
    filled = 0; total_checked = 0
    key_fields = ["enzyme_lot", "enzyme", "biomass_type", "date"]
    for rec in records.values():
        for f in key_fields:
            total_checked += 1
            v = rec.get(f)
            if v and "UPDATE" not in str(v) and v not in (None, "null", ""):
                filled += 1
    completeness = int(100 * filled / total_checked) if total_checked else 0
    return latest, n_flags, best_run, best_consumed, completeness


def _qc_detail(records: dict):
    """Return list of (run_id, issue, severity) for the QC drawer."""
    rows = []
    for rid, rec in records.items():
        for flag in rec.get("qc_flags", []):
            if "empty sheet" in flag.lower():
                sev = "info"
            elif any(w in flag.lower() for w in ["r²", "r2", "calibration", "mismatch"]):
                sev = "warn"
            else:
                sev = "info"
            rows.append((rid, flag, sev))
    return rows


# ─────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────
for key, default in [("messages", []), ("history", []), ("section", "chat"), ("show_sources", False), ("show_qc", False), ("show_more_prompts", False)]:
    if key not in st.session_state:
        st.session_state[key] = default


# ─────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────
@st.cache_data(ttl=120)
def _load_records():
    return load_run_records()

records = _load_records()
enzymes = list_enzymes()
latest, n_flags, best_run, best_consumed, completeness = _stats(records)
run_list = ", ".join(records.keys()) if records else "none"


# ─────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🧬 Penny")

    st.markdown('<div class="nav-section">Workspace</div>', unsafe_allow_html=True)

    def nav_btn(label, key, section):
        badge = f'<span class="nav-badge">{len(records)}</span>' if section == "runs" else ""
        if st.button(label, key=key, use_container_width=True):
            st.session_state.section = section
            st.rerun()

    nav_btn("💬  Chat",       "nav_chat",  "chat")
    nav_btn("📊  Runs",       "nav_runs",  "runs")
    nav_btn("📚  Knowledge",  "nav_know",  "knowledge")

    st.markdown('<div class="nav-section">Current Context</div>', unsafe_allow_html=True)
    st.caption(f"**Project:** Switchgrass Optimization")
    st.caption(f"**Runs:** {run_list}")
    st.caption(f"**Enzyme KB:** {len(enzymes)} enzymes")

    st.markdown('<div class="nav-section">Connections</div>', unsafe_allow_html=True)
    connections = [
        ("HPLC pipeline",   "Connected",   "ok"),
        ("Literature",      "Connected",   "ok"),
        ("Enzyme databases","Connected",   "ok"),
        ("Benchling",       "Coming soon", "soon"),
        ("Predictions",     "Disabled",    "soon"),
    ]
    for name, status, cls in connections:
        color = {"ok": "#16a34a", "soon": "#94a3b8", "off": "#f59e0b"}[cls]
        st.markdown(
            f'<div class="conn-row"><span class="conn-name">{name}</span>'
            f'<span style="color:{color}; font-size:0.72rem; font-weight:600;">{status}</span></div>',
            unsafe_allow_html=True,
        )

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("↺ Sync", use_container_width=True, help="Reload run records from disk"):
            st.cache_data.clear(); st.rerun()
    with c2:
        if st.button("＋ New", use_container_width=True, help="Start a new conversation"):
            st.session_state.messages = []; st.session_state.history = []; st.rerun()

    st.caption(f"claude-sonnet-4-6")


# ─────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────
st.markdown(f"""
<div class="penny-header">
    <div>
        <div class="penny-header-title">🧬 Penny — Fermentation Research Assistant</div>
        <div class="penny-header-sub">Switchgrass Optimization &nbsp;·&nbsp; {len(records)} runs selected ({run_list})</div>
    </div>
    <div class="penny-header-sync">Synced just now</div>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Sources bar (compact, collapsible)
# ─────────────────────────────────────────────
src_summary = f"<strong>Sources:</strong> {len(records)} runs &nbsp;·&nbsp; {len(enzymes)} enzymes &nbsp;·&nbsp; Literature enabled &nbsp;·&nbsp; PubChem · BRENDA connected"
st.markdown(f'<div class="sources-bar">{src_summary}</div>', unsafe_allow_html=True)

with st.expander("Manage sources", expanded=False):
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Selected run records**")
        for rid in records: st.caption(f"✅ {rid}")
        st.markdown("**Knowledge sources**")
        st.caption(f"✅ {len(enzymes)} enzyme records (local KB)")
        st.caption("✅ Semantic Scholar (200M papers)")
        st.caption("✅ PubMed (NCBI Entrez)")
    with c2:
        st.markdown("**External databases**")
        st.caption("✅ PubChem — inhibitor properties")
        st.caption("✅ BRENDA / ExPASy — enzyme kinetics")
        st.markdown("**Not available**")
        st.caption("⬜ Benchling — not connected")
        st.caption("⬜ Predictive model — not enabled")


# ─────────────────────────────────────────────
# SECTION: Runs
# ─────────────────────────────────────────────
if st.session_state.section == "runs":
    st.markdown("### 📊 Fermentation Runs")
    for rid, rec in records.items():
        consumed, final_tp = _glucose_consumed(rec)
        with st.expander(f"**{rid}** — {rec.get('biomass_type','?')} · Fermenter {rec.get('fermenter','?')} · {rec.get('date','?')}"):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown("**Conditions**")
                st.caption(f"Enzyme: {rec.get('enzyme','?')}")
                st.caption(f"Lot: {rec.get('enzyme_lot','?')}")
                st.caption(f"Timepoints (h): {rec.get('timepoints', [])}")
            with c2:
                st.markdown("**Performance**")
                st.caption(f"EH yield: {'pending real data' if not rec.get('computed_yields',{}).get('eh_yield_pct') else str(rec['computed_yields']['eh_yield_pct'])+'%'}")
                st.caption(f"Glucose consumed: {f'{consumed} g/L by {final_tp}h' if consumed else 'calculating…'}")
            with c3:
                st.markdown("**QC Flags**")
                flags = rec.get("qc_flags", [])
                for f in flags[:4]: st.caption(f"⚠️ {f[:75]}")
                if not flags: st.caption("✅ No flags")
            st.markdown("**Timeseries (g/L)**")
            for analyte in ["Glucose", "Xylose", "Ethanol", "Acetic_Acid"]:
                ts = rec.get("analyte_timeseries", {})
                if analyte in ts:
                    vals = {str(k): (round(v, 2) if v is not None else None) for k, v in ts[analyte].items()}
                    st.caption(f"{analyte}: {vals}")


# ─────────────────────────────────────────────
# SECTION: Knowledge
# ─────────────────────────────────────────────
elif st.session_state.section == "knowledge":
    st.markdown("### 📚 Knowledge Base")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Enzyme Catalog**")
        for e in enzymes: st.caption(f"🧪 {e}")
        st.markdown("**Biomass Types**")
        for code, name in [("SB","Switchgrass"),("RS","Rice Straw"),("CS","Corn Stover"),("ALB","Albizia")]:
            st.caption(f"🌾 {code} — {name}")
    with c2:
        st.markdown("**Inhibitor Thresholds**")
        thresholds = [
            ("Acetic acid",  "> 5 g/L",  "inhibitory to most yeast"),
            ("Formic acid",  "> 1 g/L",  "inhibitory"),
            ("Furfural",     "> 1 g/L",  "inhibitory"),
            ("HMF",          "> 2 g/L",  "inhibitory"),
            ("Ethanol",      "< 40 g/L", "ErgBio currently 8–10 g/L (safe)"),
        ]
        for compound, threshold, note in thresholds:
            st.caption(f"{'✅' if 'safe' in note else '⚠️'} {compound} {threshold} — {note}")
        st.markdown("**Data Sources**")
        st.caption("📡 Semantic Scholar — 200M papers, real-time")
        st.caption("📡 PubMed — NCBI Entrez API")
        st.caption("📡 PubChem REST — chemical properties")
        st.caption("📡 BRENDA / ExPASy — enzyme kinetics")


# ─────────────────────────────────────────────
# SECTION: Chat
# ─────────────────────────────────────────────
else:
    # ── Empty state ──────────────────────────
    if not st.session_state.messages:

        # 3-card stat row
        consumed_vals = [_glucose_consumed(r)[0] for r in records.values()]
        avg_consumed  = round(sum(v for v in consumed_vals if v) / max(len([v for v in consumed_vals if v]), 1), 1)

        flag_color = "#d97706" if n_flags > 0 else "#16a34a"
        flag_sub   = "Mostly empty analyte sheets" if n_flags > 0 else "All clear"

        st.markdown(f"""
        <div class="stat-row">
            <div class="stat-card">
                <div class="sv">{latest}</div>
                <div class="sl">Latest run</div>
                <div class="ss">Switchgrass · Fermenter 1 · 5 timepoints</div>
            </div>
            <div class="stat-card">
                <div class="sv {'sv-muted' if not avg_consumed else ''}">{f'{avg_consumed} g/L' if avg_consumed else '—'}</div>
                <div class="sl">Avg. glucose consumed</div>
                <div class="ss">Across {len(records)} runs · by final timepoint</div>
            </div>
            <div class="stat-card">
                <div class="sv" style="color:{flag_color};">{n_flags}</div>
                <div class="sl">QC flags</div>
                <div class="ss">{flag_sub}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # QC drawer (triggered by clicking the card area — use expander)
        if n_flags:
            with st.expander(f"View {n_flags} QC flags"):
                qc_rows = _qc_detail(records)
                for rid, issue, sev in qc_rows:
                    badge_cls = {"warn": "qc-warn", "crit": "qc-crit", "info": "qc-info"}[sev]
                    badge_txt = {"warn": "Warning", "crit": "Critical", "info": "Info"}[sev]
                    st.markdown(
                        f'<div class="qc-row">'
                        f'<span class="qc-run">{rid}</span>'
                        f'<span class="qc-issue">{issue}</span>'
                        f'<span class="qc-badge {badge_cls}">{badge_txt}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

        # ── Prompt cards ─────────────────────
        PROMPTS = {
            "🔍 Investigate": [
                ("FR009 slowdown",
                 "Why was glucose consumption slower in FR009 than FR003/FR004?",
                 "Compare kinetics across runs and identify likely inhibitory factors."),
            ],
            "📊 Compare": [
                ("Compare selected runs",
                 "Compare FR003, FR004 and FR009 — where did performance differ most?",
                 "Side-by-side yield, sugar consumption, and inhibitor comparison."),
            ],
            "📄 Research": [
                ("Cellulase loading benchmarks",
                 "What does literature recommend for cellulase loading on switchgrass?",
                 "Search Semantic Scholar and PubMed for loading and yield benchmarks."),
            ],
            "⚗️ Next Steps": [
                ("Recommend next experiment",
                 "What should we change in the next run to improve xylose consumption?",
                 "Prioritize follow-up experiments using current data and literature."),
            ],
        }

        cols = st.columns(4)
        for col, (cat, prompts) in zip(cols, PROMPTS.items()):
            with col:
                st.markdown(f'<div class="cat-label">{cat}</div>', unsafe_allow_html=True)
                title, question, desc = prompts[0]
                if st.button(title, key=f"p_{title[:15]}", use_container_width=True):
                    st.session_state.messages.append({"role": "user", "content": question})
                    st.rerun()
                st.caption(desc)

        # More prompts (collapsed)
        MORE = [
            "Is acetic acid approaching an inhibitory level at 96h?",
            "How does Cellic CTec3 compare to CTec2 for lignocellulosic biomass?",
            "Which run had the best xylose utilization?",
            "What data quality issues should I be aware of?",
        ]
        with st.expander("View more questions"):
            for q in MORE:
                if st.button(q, key=f"more_{q[:20]}", use_container_width=True):
                    st.session_state.messages.append({"role": "user", "content": q})
                    st.rerun()

    # ── Conversation ─────────────────────────
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            with st.chat_message("user"):
                st.markdown(msg["content"])
        else:
            with st.chat_message("assistant", avatar="🧬"):
                for t in msg.get("tools_used", []):
                    st.markdown(
                        f'<div class="tool-call">🔍 {_tool_label(t["name"], t["inputs"])}</div>',
                        unsafe_allow_html=True,
                    )
                st.markdown(msg["content"])

    # ── Context chips + input ─────────────────
    if records:
        chips = "".join(f'<span class="ctx-chip">{rid}</span>' for rid in records.keys())
        st.markdown(
            f'<div class="ctx-row"><span class="ctx-label">Selected runs:</span>{chips}</div>',
            unsafe_allow_html=True,
        )

    user_input = st.chat_input("Ask why a run behaved differently, compare conditions, or search the literature…")

    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        tools_fired = []
        def on_tool_call(tool_name, inputs):
            tools_fired.append({"name": tool_name, "inputs": inputs})

        with st.chat_message("assistant", avatar="🧬"):
            with st.spinner("Thinking…"):
                response_text, updated_history = chat(
                    user_message=user_input,
                    history=st.session_state.history,
                    records=records,
                    on_tool_call=on_tool_call,
                )
            for t in tools_fired:
                st.markdown(
                    f'<div class="tool-call">🔍 {_tool_label(t["name"], t["inputs"])}</div>',
                    unsafe_allow_html=True,
                )
            st.markdown(response_text)

        st.session_state.history = updated_history
        st.session_state.messages.append({
            "role": "assistant",
            "content": response_text,
            "tools_used": tools_fired,
        })
