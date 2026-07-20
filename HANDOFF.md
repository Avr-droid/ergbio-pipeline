# ErgBio AI Pipeline — Full Context Handoff
**Last updated:** 2026-07-20 | **Repo:** `Avr-droid/ergbio-pipeline` (public)

---

## The Big Picture

ErgBio is a cellulosic ethanol company converting lignocellulosic biomass (switchgrass, rice straw, corn stover) into ethanol via:
1. **Pretreatment** — breaks down lignin
2. **Enzymatic Hydrolysis (EH)** — cellulases convert cellulose→glucose, hemicellulose→xylose
3. **Fermentation** — organisms convert sugars→ethanol

The AI pipeline has two goals:
- **Short-term:** Automate HPLC data processing and give scientists an AI research partner
- **Long-term:** Build a proprietary ErgBio intelligence layer that reasons over all experimental history, enzyme databases, and scientific literature — becoming more valuable with every run

This is also a **proof-of-concept for a biotech AI consulting/product business**. If it works at ErgBio, the same architecture deploys for other biotech companies.

---

## The Team

| Person | Role | Pipeline involvement |
|--------|------|---------------------|
| **Penny** | CEO | Uses Research Assistant; wants AI reasoning partner for scientific decisions |
| **Ares** | Lab scientist | Runs experiments, drops HPLC files into Drive, fills in run conditions |
| **Diana** | Operations/Admin | Manages Google Drive permissions; needs to add service account as Content Manager to Shared Drive and provide Fermentation Runs subfolder ID |
| **Aarav** | AI Engineer (you) | Building everything |

---

## Pipeline 1: Agentic HPLC Pipeline (Lab → Structured Data)

**Purpose:** Automate the journey from raw instrument file to structured run record. Ares should never have to manually enter numbers.

**Flow:**
```
Ares runs experiment
    → Shimadzu HPLC produces XLS file
    → Ares drops XLS into Google Drive: Fermentation/HPLC Input/
    → drive_watcher.py detects new file (polls every 60s)
    → hplc_parser.py extracts all 12 analytes, parses R², QC flags
    → QC Gate checks: R²≥0.995, %Diff≤15%, replicates CV≤10%
    → extractor.py structures data per (run_id, fermenter) pair
    → calculator computes EH yield, ferm efficiency
    → reporter.py (Claude Haiku) writes narrative summary
    → save_run.py saves JSON to Drive: Fermentation/Fermentation Runs/
    → JSON also copied to data/run_records/ (for Penny agent to read)
```

**Users:** Ares (drops files), Diana (Drive admin), Pipeline runs autonomously

**Live at:** `ergbio-pipeline.streamlit.app` (Manual Calculator — existing)

**What's built:**
- ✅ `tools/hplc_parser.py` — full Shimadzu XLS parser, 18/18 tests passing
- ✅ `agents/extractor.py` — structures data per run/fermenter pair
- ✅ `tools/calculator_tool.py` — EH yield + fermentation efficiency formulas
- ✅ `tools/save_run.py` — calculator + Drive save (has driveId bug — see blocked items)
- ✅ `streamlit_app.py` — manual calculator UI

**What's not built yet:**
- ❌ `tools/drive_watcher.py` — polls Drive HPLC Input folder, triggers pipeline
- ❌ `agent.py` orchestrator — connects watcher→parser→QC→calculator→reporter→save
- ❌ `agents/reporter.py` — Claude Haiku narrative generator (skeleton only)

**Blocked on:**
- Diana: add `ergbio-pipeline@ergbio-pipeline.iam.gserviceaccount.com` as Content Manager to ErgBio Shared Drive (ID: `0AEwqgR6xKpf_Uk9PVA`)
- Diana: provide Fermentation Runs subfolder ID (replace `SHARED_FOLDER_ID` in `save_run.py`)
- Ares: confirm QC thresholds (R²≥0.995 is placeholder), provide biomass composition % and enzyme loading for yield calculation
- Ares: fill in actual enzyme lot numbers and conditions in `data/run_records/*.json`

**Key HPLC file format (Shimadzu LabSolutions XLS):**
- 12 sheets, one per analyte: Cellobiose, Citric_Acid, Glucose, Xylose, Arabinose, Xylitol, Succinic_Acid, Glycerol, Formic_Acid, Acetic_Acid, Ethanol, Component
- Row 2: calibration — R² lives here, e.g. `Y = 3127.71*X   R^2 = 0.9996`
- Row 4: headers — Filename, Sample Type, Sample Name, Area, Amount, %Diff, Peak Status
- Row 5+: data rows. Sample type `Unknown Sample` = fermentation samples we care about
- Filename pattern: `YYYYMMDD_FR009_1_24_1` = FR009, Fermenter 1, 24h timepoint, replicate 1

**Google Drive structure:**
```
ErgBio Shared Drive (ID: 0AEwqgR6xKpf_Uk9PVA)
└── Fermentation/
    ├── HPLC Input/          ← Ares drops XLS files here
    └── Fermentation Runs/   ← Pipeline saves JSON records here (ID: pending Diana)
```

---

## Pipeline 2: Penny Research Assistant (Data → Intelligence)

**Purpose:** Give Penny and the science team an AI reasoning partner that knows ErgBio's experimental history, enzyme databases, and scientific literature simultaneously.

**Flow:**
```
Penny types question
    → Agent loads all run records from data/run_records/
    → Agent selects tools based on question type
    → Tools execute (literature search, enzyme lookup, calculator, etc.)
    → Claude Sonnet reasons over run data + tool results
    → Answer with citations back to specific runs and papers
```

**Users:** Penny (CEO), scientists

**Live at:** `ergbio-assistant.streamlit.app`

**What's built (all working, all tested):**
- ✅ `penny_app.py` — Streamlit chat UI, deployed
- ✅ `agents/penny_agent.py` — Claude Sonnet with 8 tools, agentic loop
- ✅ `tools/literature_search.py` — Semantic Scholar (200M papers) + PubMed, auto-fallback
- ✅ `tools/enzyme_lookup.py` — ErgBio local KB + UniProt REST API
- ✅ `tools/pubchem_lookup.py` — PubChem chemical/inhibitor lookup, fermentation thresholds
- ✅ `tools/brenda_lookup.py` — BRENDA enzyme kinetics (credential-ready) + ExPASy fallback
- ✅ `tools/calculator_tool.py` — live EH yield + ferm efficiency calculator
- ✅ `data/enzyme_kb.json` — CTec3, CTec2, Accellerase 1500 + 4 biomass types
- ✅ `data/run_records/` — FR003.json, FR004.json, FR009.json (placeholder — Ares to update)

**8 tools available to Claude:**
| Tool | Source | Auth needed |
|------|--------|-------------|
| search_papers | Semantic Scholar + PubMed | None (free) |
| lookup_enzyme | ErgBio KB + UniProt | None (free) |
| lookup_enzyme_kinetics | BRENDA + ExPASy | BRENDA: free registration |
| lookup_chemical | PubChem | None (free) |
| calculate_yields | Internal calculator | None |
| get_biomass_info | ErgBio KB | None |
| compare_runs | Run records | None |
| get_run_detail | Run records | None |

**Streamlit secrets needed:**
```toml
ANTHROPIC_API_KEY = "sk-ant-..."
# Optional — enables full BRENDA kinetics:
BRENDA_EMAIL    = "your@email.com"
BRENDA_PASSWORD = "yourpassword"
```

---

## How the Two Pipelines Connect

Pipeline 1 produces → Pipeline 2 consumes.

Right now the connection is manual: someone copies the processed JSON from Drive into `data/run_records/`. When `agent.py` orchestrator is done, new experiments will automatically appear in Penny's agent within minutes of the HPLC file landing in Drive.

```
Ares drops XLS → Pipeline 1 processes → JSON saved to Drive + data/run_records/
                                                                      ↓
                                         Penny agent reloads on next query → answers include new run
```

---

## What to Build Next (2-Week Sprint)

**Week 1 — Immediate:**
1. Penny's paper library → private RAG
   - Penny shares PDF folder (Google Drive or local)
   - `tools/pdf_processor.py`: extract text → chunk → BM25 index → JSON
   - Add `search_knowledge_base` tool to penny_agent.py
   - No vector DB needed — BM25 keyword search is sufficient at <50 papers
   
2. Ares fills real data into `data/run_records/*.json`
   - Actual enzyme lot numbers
   - Conditions: enzyme loading (mg/g), solids loading (g/L), glucan %
   - Computed yields (once conditions known)

3. Fix `save_run.py` driveId bug
   - Add `driveId='0AEwqgR6xKpf_Uk9PVA'` to Drive API call
   - Update `SHARED_FOLDER_ID` to Fermentation Runs subfolder ID (pending Diana)

**Week 2 — Pipeline completion:**
4. Build `tools/drive_watcher.py`
   - Poll HPLC Input folder every 60s
   - Detect new XLS, validate filename pattern
   - Trigger agent.py pipeline

5. Wire `agent.py` orchestrator
   - watcher → parser → QC gate → calculator → reporter → save

6. End-to-end test with real HPLC file

**After 2 weeks (Phase 2):**
- Supabase database (when 15+ runs exist, move from JSON files)
- pgvector embeddings (upgrade BM25 to semantic search)
- Benchling connector (when access granted — closes loop between lab protocols and HPLC data)
- BRENDA registration (register at brenda-enzymes.org for full kinetics data)

---

## Long-Term Vision (1 Year)

**Month 1–2:** Pipeline complete + paper library. Penny has a working AI research partner.

**Month 2–4:** Supabase. All runs in a structured database. Cross-run queries, trend analysis, yield comparisons by enzyme/biomass/condition.

**Month 4–8:** RAG upgrade. pgvector semantic search over runs + papers. Much better retrieval than BM25.

**Month 8–12:** ML yield predictor. Once 50+ diverse runs exist, XGBoost regression model predicts glucose yield given enzyme lot + loading + biomass composition + pretreatment conditions. Feeds into Penny agent as a prediction tool.

**Year 2+:** Fine-tuned open-source LLM (Llama/Mistral) for full ErgBio domain knowledge. On-premise deployment for data sovereignty. Multi-modal (spectroscopy, microscopy).

---

## Business Model (Longer Term)

ErgBio is the proof-of-concept. The same architecture (HPLC parser + RAG + AI reasoner + enzyme KB) deploys for any biotech company working with fermentation data.

**Phase 1 (now):** Build at ErgBio. Get paid consulting. Document everything as if building a product.

**Phase 2:** Second biotech client. Reuse parser, KB, agent pattern. Customize for their instrument format and analytes.

**Phase 3:** Package as Pipeline-as-a-Service. Clients bring their data, you run setup + training. Recurring infra fee.

**Phase 4:** Multi-tenant SaaS platform. Each company gets isolated data. Shared scientific knowledge layer (enzyme KB, literature) improves for everyone. Subscription per seat.

---

## File Structure
```
ErgBio Agents/
├── streamlit_app.py          Manual Calculator (Ares) — ergbio-pipeline.streamlit.app
├── penny_app.py              Research Assistant (Penny) — ergbio-assistant.streamlit.app
├── agent.py                  Orchestrator skeleton (TO BUILD)
│
├── agents/
│   ├── penny_agent.py        8-tool Claude Sonnet agent
│   ├── extractor.py          HPLC data structuring
│   └── reporter.py           Claude Haiku narrative (skeleton)
│
├── tools/
│   ├── hplc_parser.py        Shimadzu XLS parser ✅ (18/18 tests)
│   ├── literature_search.py  Semantic Scholar + PubMed ✅
│   ├── enzyme_lookup.py      UniProt + local KB ✅
│   ├── pubchem_lookup.py     Chemical/inhibitor lookup ✅
│   ├── brenda_lookup.py      Enzyme kinetics ✅
│   ├── calculator_tool.py    EH yield + ferm efficiency ✅
│   ├── save_run.py           Calculator + Drive save (driveId bug)
│   └── drive_watcher.py      TO BUILD
│
├── data/
│   ├── enzyme_kb.json        ErgBio enzyme knowledge base
│   └── run_records/          FR003.json, FR004.json, FR009.json (placeholder)
│
└── tests/
    └── test_hplc_parser.py   18 unit tests, all passing
```

---

## Key Numbers
- Claude Haiku per run report: ~$0.002
- Claude Sonnet per Penny query: ~$0.02–0.05
- Streamlit Cloud: free (public repo)
- Total monthly cost at current scale: <$10
- Runs needed for ML predictor: ~50 diverse runs
- Current runs: 3 (FR003, FR004, FR009)
