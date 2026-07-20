"""
penny_app.py — ErgBio Research Assistant (Penny Agent)

Run with:  streamlit run penny_app.py
Deploy to Streamlit Cloud as a second app pointing to this file.
Required secret: ANTHROPIC_API_KEY
"""

import streamlit as st
from agents.penny_agent import chat, load_run_records, list_enzymes

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Penny — ErgBio Research Assistant",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    #MainMenu, footer { visibility: hidden; }

    /* Compact header */
    .penny-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
        padding: 0.75rem 1.2rem; border-radius: 10px;
        margin-bottom: 0.8rem; color: white;
    }
    .penny-header h2 { color: white; margin: 0; font-size: 1.1rem; font-weight: 700; }
    .penny-header p  { color: #94a3b8; margin: 0.2rem 0 0 0; font-size: 0.76rem; }

    /* Source status row */
    .source-row { display: flex; gap: 0.6rem; margin-bottom: 0.85rem; flex-wrap: wrap; }
    .source-chip {
        font-size: 0.73rem; border-radius: 20px; padding: 0.2rem 0.65rem;
        border: 1px solid #e2e8f0; color: #475569; background: #f8fafc;
    }
    .source-chip.ok   { border-color: #86efac; color: #166534; background: #f0fdf4; }
    .source-chip.off  { border-color: #e2e8f0; color: #94a3b8; }

    /* Category labels */
    .cat-label {
        font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.08em; color: #94a3b8; margin: 0.9rem 0 0.35rem 0;
    }

    /* Tool call banners */
    .tool-call {
        background: #f0fdf4; border-left: 3px solid #22c55e;
        padding: 0.35rem 0.8rem; border-radius: 0 6px 6px 0;
        font-size: 0.79rem; color: #166534; margin: 0.25rem 0;
    }

    /* Context chips near input */
    .ctx-chips { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.3rem; font-size: 0.73rem; }
    .ctx-chip {
        background: #eff6ff; border: 1px solid #bfdbfe;
        border-radius: 20px; padding: 0.15rem 0.6rem; color: #1d4ed8;
    }

    /* Stats grid */
    .stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.7rem; margin-bottom: 1rem; }
    .stat-card {
        background: #f8fafc; border: 1px solid #e2e8f0;
        border-radius: 8px; padding: 0.7rem 0.9rem;
    }
    .stat-val { font-size: 1.35rem; font-weight: 700; color: #0f172a; }
    .stat-lbl { font-size: 0.7rem; color: #64748b; margin-top: 0.1rem; }
    .stat-sub { font-size: 0.68rem; color: #94a3b8; margin-top: 0.15rem; }
    .stat-alert { color: #dc2626; }
    .stat-ok    { color: #16a34a; }

    /* Sidebar nav labels */
    .nav-section {
        font-size: 0.66rem; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.08em; color: #94a3b8; margin: 0.9rem 0 0.3rem 0;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _tool_label(name: str, inputs: dict) -> str:
    if name == "search_papers":
        return f"Searched literature: \"{inputs.get('query', '')}\" ({inputs.get('source', 'semantic_scholar')})"
    elif name == "lookup_enzyme":
        return f"Looked up enzyme: {inputs.get('name', '')}"
    elif name == "lookup_enzyme_kinetics":
        return f"Enzyme kinetics (BRENDA/ExPASy): {inputs.get('enzyme_name', '')}"
    elif name == "lookup_chemical":
        return f"PubChem lookup: {inputs.get('compound_name', '')}"
    elif name == "calculate_yields":
        return "Calculated EH yield + fermentation efficiency"
    elif name == "get_biomass_info":
        return f"Retrieved biomass data: {inputs.get('biomass_code', '')}"
    elif name == "compare_runs":
        return f"Compared runs: {', '.join(inputs.get('run_ids', []))}"
    elif name == "get_run_detail":
        return f"Loaded full record: {inputs.get('run_id', '')}"
    return f"Called tool: {name}"


def _best_yield(records: dict):
    best_run, best_val = "—", 0.0
    for rid, rec in records.items():
        ey = rec.get("computed_yields", {}).get("eh_yield_pct")
        if ey and ey > best_val:
            best_val, best_run = ey, rid
    return best_run, best_val


def _qc_alerts(records: dict) -> int:
    return sum(len(rec.get("qc_flags", [])) for rec in records.values())


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "history" not in st.session_state:
    st.session_state.history = []
if "section" not in st.session_state:
    st.session_state.section = "chat"


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
@st.cache_data(ttl=120)
def _load_records():
    return load_run_records()

records  = _load_records()
enzymes  = list_enzymes()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🧬 Penny")

    st.markdown('<div class="nav-section">Workspace</div>', unsafe_allow_html=True)
    if st.button("💬 Chat",      use_container_width=True): st.session_state.section = "chat";     st.rerun()
    if st.button("📊 Runs",      use_container_width=True): st.session_state.section = "runs";     st.rerun()
    if st.button("📚 Knowledge", use_container_width=True): st.session_state.section = "knowledge"; st.rerun()

    st.markdown('<div class="nav-section">Current Context</div>', unsafe_allow_html=True)
    if records:
        st.caption(f"**Project:** Switchgrass Optimization")
        st.caption(f"**Runs:** {', '.join(records.keys())}")
        st.caption(f"**Enzyme KB:** {len(enzymes)} enzymes")
    else:
        st.caption("No runs loaded")

    st.markdown('<div class="nav-section">Connections</div>', unsafe_allow_html=True)
    st.caption("✅ HPLC pipeline")
    st.caption("✅ Enzyme database")
    st.caption("✅ Literature (Semantic Scholar + PubMed)")
    st.caption("✅ PubChem · BRENDA")
    st.caption("⬜ Benchling (coming soon)")
    st.caption("⬜ Predictions (coming soon)")

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔄 Reload", use_container_width=True):
            st.cache_data.clear(); st.rerun()
    with c2:
        if st.button("🗑️ Clear", use_container_width=True):
            st.session_state.messages = []; st.session_state.history = []; st.rerun()

    st.markdown("---")
    st.caption(f"Model: claude-sonnet-4-6 · {len(records)} runs")


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
run_list = ", ".join(records.keys()) if records else "none"
st.markdown(f"""
<div class="penny-header">
    <h2>🧬 Penny — Fermentation Research Assistant</h2>
    <p>Project: Switchgrass Optimization &nbsp;·&nbsp; {len(records)} runs selected ({run_list}) &nbsp;·&nbsp; Data synced just now</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Source status row
# ---------------------------------------------------------------------------
st.markdown(f"""
<div class="source-row">
    <span class="source-chip ok">📊 {len(records)} runs loaded</span>
    <span class="source-chip ok">🧪 {len(enzymes)} enzymes in KB</span>
    <span class="source-chip ok">📄 Literature: live</span>
    <span class="source-chip ok">🔬 PubChem · BRENDA: active</span>
    <span class="source-chip off">🔗 Benchling: not connected</span>
    <span class="source-chip off">🤖 Predictions: not enabled</span>
</div>
""", unsafe_allow_html=True)


# ============================================================
# SECTION: Runs
# ============================================================
if st.session_state.section == "runs":
    st.markdown("### 📊 Fermentation Runs")
    if not records:
        st.info("No run records found in data/run_records/")
    else:
        for rid, rec in records.items():
            with st.expander(f"**{rid}** — {rec.get('biomass_type','?')} · Fermenter {rec.get('fermenter','?')} · {rec.get('date','?')}"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown("**Conditions**")
                    st.caption(f"Enzyme: {rec.get('enzyme','?')}")
                    st.caption(f"Lot: {rec.get('enzyme_lot','?')}")
                    st.caption(f"Timepoints (h): {rec.get('timepoints', [])}")
                with c2:
                    st.markdown("**Computed Yields**")
                    for k, v in rec.get("computed_yields", {}).items():
                        if v is not None:
                            label = f"{v:.1f}%" if isinstance(v, float) else str(v)
                            st.caption(f"{k}: **{label}**")
                with c3:
                    st.markdown("**QC Flags**")
                    flags = rec.get("qc_flags", [])
                    if flags:
                        for f in flags[:4]: st.caption(f"⚠️ {f[:80]}")
                    else:
                        st.caption("✅ No flags")
                st.markdown("**Timeseries (g/L)**")
                for analyte in ["Glucose", "Xylose", "Ethanol", "Acetic_Acid"]:
                    ts = rec.get("analyte_timeseries", {})
                    if analyte in ts:
                        vals = {str(k): (round(v, 2) if v is not None else None) for k, v in ts[analyte].items()}
                        st.caption(f"{analyte}: {vals}")


# ============================================================
# SECTION: Knowledge
# ============================================================
elif st.session_state.section == "knowledge":
    st.markdown("### 📚 Knowledge Base")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Enzyme Catalog**")
        for e in enzymes:
            st.caption(f"🧪 {e}")
        st.markdown("**Biomass Types**")
        for code, name in [("SB","Switchgrass"),("RS","Rice Straw"),("CS","Corn Stover"),("ALB","Albizia")]:
            st.caption(f"🌾 {code} — {name}")
    with c2:
        st.markdown("**Inhibitor Thresholds**")
        st.caption("⚠️ Acetic acid > 5 g/L — inhibitory to most yeast")
        st.caption("⚠️ Formic acid > 1 g/L — inhibitory")
        st.caption("⚠️ Furfural > 1 g/L — inhibitory")
        st.caption("⚠️ HMF > 2 g/L — inhibitory")
        st.caption("✅ Ethanol < 40 g/L — ErgBio currently 8–10 g/L (safe)")
        st.markdown("**Connected Sources**")
        st.caption("📡 Semantic Scholar — 200M papers, free, no auth")
        st.caption("📡 PubMed — via NCBI Entrez, free")
        st.caption("📡 PubChem REST API — free")
        st.caption("📡 BRENDA / ExPASy — enzyme kinetics, free tier")


# ============================================================
# SECTION: Chat (default)
# ============================================================
else:
    # Empty state
    if not st.session_state.messages:
        best_run, best_val = _best_yield(records)
        alerts = _qc_alerts(records)
        latest = sorted(records.keys())[-1] if records else "—"

        alert_class = "stat-alert" if alerts else "stat-ok"
        alert_sub   = "Review recommended" if alerts else "All clear"

        st.markdown(f"""
        <div class="stat-grid">
            <div class="stat-card">
                <div class="stat-val">{len(records)}</div>
                <div class="stat-lbl">Runs analyzed</div>
                <div class="stat-sub">{run_list}</div>
            </div>
            <div class="stat-card">
                <div class="stat-val">{latest}</div>
                <div class="stat-lbl">Latest run</div>
                <div class="stat-sub">Switchgrass · Fermenter 1</div>
            </div>
            <div class="stat-card">
                <div class="stat-val">{f"{best_val:.0f}%" if best_val else "—"}</div>
                <div class="stat-lbl">Best EH yield</div>
                <div class="stat-sub">{best_run}</div>
            </div>
            <div class="stat-card">
                <div class="stat-val {alert_class}">{alerts}</div>
                <div class="stat-lbl">QC alerts</div>
                <div class="stat-sub">{alert_sub}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        PROMPTS = {
            "🔍 Investigate": [
                "Why was glucose consumption slower in FR009 than FR003/FR004?",
                "Is acetic acid approaching an inhibitory level at 96h?",
            ],
            "📊 Compare": [
                "Compare FR003, FR004 and FR009 — where did performance differ most?",
                "Which run had the best xylose utilization?",
            ],
            "📄 Research": [
                "What does literature recommend for cellulase loading on switchgrass?",
                "How does Cellic CTec3 compare to CTec2 for lignocellulosic biomass?",
            ],
            "⚗️ Next Steps": [
                "What should we change in the next run to improve xylose consumption?",
                "What are the recommended next experiments based on current data?",
            ],
        }

        for cat, prompts in PROMPTS.items():
            st.markdown(f'<div class="cat-label">{cat}</div>', unsafe_allow_html=True)
            cols = st.columns(len(prompts))
            for col, question in zip(cols, prompts):
                if col.button(question, key=f"sug_{question[:25]}", use_container_width=True):
                    st.session_state.messages.append({"role": "user", "content": question})
                    st.rerun()

    # Conversation display
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

    # Context chips
    if records:
        chips = "".join(f'<span class="ctx-chip">{rid}</span>' for rid in records.keys())
        st.markdown(f'<div class="ctx-chips">Reasoning over: {chips}</div>', unsafe_allow_html=True)

    # Chat input
    user_input = st.chat_input("Ask about your runs, enzymes, or search the literature…")

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
