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
    page_title="ErgBio Research Assistant",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
        padding: 1.2rem 1.5rem; border-radius: 12px;
        margin-bottom: 1.2rem; color: white;
    }
    .main-header h1 { color: white; margin: 0; font-size: 1.6rem; }
    .main-header p  { color: #94a3b8; margin: 0.3rem 0 0 0; font-size: 0.9rem; }
    .tool-call {
        background: #f0fdf4; border-left: 3px solid #22c55e;
        padding: 0.4rem 0.8rem; border-radius: 0 6px 6px 0;
        font-size: 0.82rem; color: #166534; margin: 0.3rem 0;
    }
    #MainMenu { visibility: hidden; }
    footer     { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Helper — MUST be defined before the display loop uses it
# ---------------------------------------------------------------------------
def _tool_label(name: str, inputs: dict) -> str:
    if name == "search_papers":
        return f"Searched literature: \"{inputs.get('query', '')}\" ({inputs.get('source', 'semantic_scholar')})"
    elif name == "lookup_enzyme":
        return f"Looked up enzyme: {inputs.get('name', '')}"
    elif name == "get_biomass_info":
        return f"Retrieved biomass data: {inputs.get('biomass_code', '')}"
    elif name == "compare_runs":
        return f"Compared runs: {', '.join(inputs.get('run_ids', []))}"
    elif name == "get_run_detail":
        return f"Loaded full record: {inputs.get('run_id', '')}"
    return f"Called tool: {name}"

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "history"  not in st.session_state:
    st.session_state.history  = []

# ---------------------------------------------------------------------------
# Load run records (cached 2 min)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=120)
def _load_records():
    return load_run_records()

records = _load_records()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 🔬 ErgBio Assistant")
    st.markdown("---")
    st.markdown("### 📊 Loaded Runs")
    if records:
        for rid, rec in records.items():
            with st.expander(f"**{rid}** — {rec.get('biomass_type','?')}"):
                st.markdown(f"**Date:** {rec.get('date','?')}")
                st.markdown(f"**Timepoints (h):** {rec.get('timepoints',[])}")
                yields = rec.get("computed_yields", {})
                for k, v in yields.items():
                    if v is not None:
                        st.markdown(f"**{k}:** {v:.1f}%" if isinstance(v, float) else f"**{k}:** {v}")
    else:
        st.info("No runs loaded yet.")

    st.markdown("---")
    st.markdown("### 🧪 Enzyme KB")
    for e in list_enzymes():
        st.markdown(f"- {e}")

    st.markdown("---")
    if st.button("🔄 Reload Runs"):
        st.cache_data.clear()
        st.rerun()
    if st.button("🗑️ Clear Chat"):
        st.session_state.messages = []
        st.session_state.history  = []
        st.rerun()

    st.markdown("---")
    st.caption(f"Model: claude-sonnet-4-6 · Runs: {len(records)}")

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("""
<div class="main-header">
    <h1>🧬 ErgBio Research Assistant</h1>
    <p>Ask about fermentation runs, enzyme performance, literature benchmarks, or get experiment suggestions.</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Suggested questions (shown when chat is empty)
# ---------------------------------------------------------------------------
if not st.session_state.messages:
    st.markdown("#### Try asking:")
    cols = st.columns(2)
    suggestions = [
        "What does literature say about optimal cellulase loading for switchgrass?",
        "Compare FR003, FR004 and FR009 — where did performance differ most?",
        "Is our acetic acid level at 96h approaching inhibition thresholds?",
        "What should we change in the next run to improve xylose consumption?",
        "How does Cellic CTec3 perform on lignocellulosic biomass vs CTec2?",
        "Why might glucose consumption be slower in FR009 than FR003/FR004?",
    ]
    for i, s in enumerate(suggestions):
        if cols[i % 2].button(s, key=f"sug_{i}", use_container_width=True):
            st.session_state.messages.append({"role": "user", "content": s})
            st.rerun()

# ---------------------------------------------------------------------------
# Display conversation history
# ---------------------------------------------------------------------------
for msg in st.session_state.messages:
    role = msg["role"]
    if role == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
    else:
        with st.chat_message("assistant", avatar="🧬"):
            for t in msg.get("tools_used", []):
                st.markdown(
                    f'<div class="tool-call">🔍 {_tool_label(t["name"], t["inputs"])}</div>',
                    unsafe_allow_html=True
                )
            st.markdown(msg["content"])

# ---------------------------------------------------------------------------
# Chat input
# ---------------------------------------------------------------------------
user_input = st.chat_input("Ask about your runs, enzymes, or search the literature...")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    tools_fired = []

    def on_tool_call(tool_name, inputs):
        tools_fired.append({"name": tool_name, "inputs": inputs})

    with st.chat_message("assistant", avatar="🧬"):
        with st.spinner("Thinking..."):
            response_text, updated_history = chat(
                user_message=user_input,
                history=st.session_state.history,
                records=records,
                on_tool_call=on_tool_call,
            )

        for t in tools_fired:
            st.markdown(
                f'<div class="tool-call">🔍 {_tool_label(t["name"], t["inputs"])}</div>',
                unsafe_allow_html=True
            )
        st.markdown(response_text)

    st.session_state.history = updated_history
    st.session_state.messages.append({
        "role": "assistant",
        "content": response_text,
        "tools_used": tools_fired,
    })
