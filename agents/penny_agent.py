"""
penny_agent.py — ErgBio Research Assistant Agent.

Claude Sonnet with 8 tools:
  search_papers          Semantic Scholar + PubMed literature search
  lookup_enzyme          Local KB + UniProt enzyme information
  get_biomass_info       Biomass composition from local KB
  lookup_chemical        PubChem — inhibitor properties, molecular data
  lookup_enzyme_kinetics BRENDA / ExPASy — Km, Vmax, substrate specificity
  calculate_yields       Live EH yield + fermentation efficiency calculator
  compare_runs           Side-by-side run comparison
  get_run_detail         Full detail for a specific run
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

from tools.literature_search import search_papers, format_for_context as fmt_papers
from tools.enzyme_lookup     import lookup_enzyme, get_biomass_info, list_enzymes, format_enzyme_for_context
from tools.pubchem_lookup    import get_fermentation_inhibitor_profile, format_for_context as fmt_pubchem
from tools.brenda_lookup     import lookup_enzyme_kinetics, format_for_context as fmt_brenda
from tools.calculator_tool   import (
    calculate_eh_yield, calculate_fermentation_efficiency,
    calculate_from_run_record, format_for_context as fmt_calc
)

load_dotenv()
logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

RUN_RECORDS_DIR = Path(__file__).parent.parent / "data" / "run_records"
MODEL           = "claude-sonnet-4-6"
MAX_TOKENS      = 4096

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the ErgBio Research Assistant — a scientific peer and reasoning partner for the ErgBio team, especially Penny (CEO) and the lab scientists.

ErgBio is a biotech company focused on cellulosic ethanol production from lignocellulosic biomass (switchgrass, rice straw, corn stover, albizia). The process:
  1. Pretreatment — breaks down lignin to expose cellulose/hemicellulose
  2. Enzymatic Hydrolysis (EH) — cellulase cocktails convert cellulose→glucose, hemicellulose→xylose
  3. Fermentation — microorganisms convert sugars→ethanol

KEY METRICS:
  EH Yield (%)          = glucose released ÷ theoretical max from glucan × 100
  Fermentation Eff. (%) = ethanol produced ÷ theoretical max from sugars × 100
  Xylose utilization    = xylose consumed ÷ initial xylose × 100
  Target: EH yield >80%, ferm efficiency >90%, full xylose utilization

HPLC ANALYTES (g/L at each timepoint):
  Cellobiose, Glucose, Xylose, Arabinose, Xylitol, Succinic_Acid,
  Glycerol, Formic_Acid, Acetic_Acid, Ethanol, Citric_Acid

INHIBITOR THRESHOLDS (watch for these in run data):
  Acetic acid  >5 g/L  = inhibitory to most yeast
  Formic acid  >1 g/L  = inhibitory
  Ethanol      >40 g/L = inhibitory (ErgBio currently 8–10 g/L, well below)

TOOLS AVAILABLE — use them proactively:
  search_papers          → benchmarks, mechanisms, optimal conditions from literature
  lookup_enzyme          → ErgBio KB + UniProt for enzyme products (CTec3, etc.)
  lookup_enzyme_kinetics → BRENDA/ExPASy for Km, Vmax, substrate kinetics
  lookup_chemical        → PubChem for inhibitor properties and thresholds
  calculate_yields       → compute EH yield and ferm efficiency from numbers
  compare_runs           → side-by-side run comparison
  get_run_detail         → full data for a specific run

BEHAVIOR:
  - Reason like a senior biochemical engineer
  - Cite specific numbers from run records — never hallucinate values
  - Use calculate_yields whenever Penny asks about yields — don't just estimate
  - Use lookup_chemical when discussing acetic acid, formic acid, furfural, or any inhibitor
  - Flag problems proactively (e.g. incomplete xylose consumption, rising acetic acid)
  - Be honest about small sample size (currently 3 runs)
  - When comparing to literature, note whether ErgBio's conditions match"""


# ---------------------------------------------------------------------------
# Run record loading
# ---------------------------------------------------------------------------

def load_run_records() -> dict:
    records = {}
    if not RUN_RECORDS_DIR.exists():
        RUN_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
        return records
    for fpath in sorted(RUN_RECORDS_DIR.glob("*.json")):
        try:
            with open(fpath) as f:
                rec = json.load(f)
            records[rec.get("run_id", fpath.stem)] = rec
        except Exception as e:
            logger.warning("Could not load %s: %s", fpath.name, e)
    return records


def _build_runs_context(records: dict) -> str:
    if not records:
        return "No run records loaded yet."
    lines = [f"=== ErgBio Run Records ({len(records)} runs) ===\n"]
    for run_id, rec in records.items():
        lines.append(f"--- {run_id} (Fermenter {rec.get('fermenter','?')}) ---")
        lines.append(f"Date: {rec.get('date','?')} | Biomass: {rec.get('biomass_type','?')} | Enzyme: {rec.get('enzyme','?')}")
        tps = rec.get("timepoints", [])
        lines.append(f"Timepoints (h): {tps}")
        ts = rec.get("analyte_timeseries", {})
        for analyte in ["Glucose", "Xylose", "Ethanol", "Acetic_Acid", "Cellobiose"]:
            if analyte in ts:
                vals = {str(k): round(v, 2) if v is not None else None for k, v in ts[analyte].items()}
                lines.append(f"  {analyte}: {vals}")
        if rec.get("qc_flags"):
            lines.append(f"  QC flags: {rec['qc_flags'][:2]}")
        if rec.get("notes"):
            lines.append(f"  Notes: {rec['notes'][:200]}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "search_papers",
        "description": "Search Semantic Scholar and PubMed for scientific literature on enzymatic hydrolysis, fermentation, enzyme performance, inhibitor effects, or cellulosic ethanol. Use for benchmarks, mechanisms, and optimal conditions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query":  {"type": "string", "description": "Specific search query, e.g. 'acetic acid inhibition xylose fermentation Saccharomyces cerevisiae'"},
                "limit":  {"type": "integer", "default": 5},
                "source": {"type": "string", "enum": ["semantic_scholar", "pubmed", "both"], "default": "semantic_scholar"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "lookup_enzyme",
        "description": "Look up a commercial enzyme product (e.g. Cellic CTec3). Returns optimal conditions, substrates, inhibitors, ErgBio notes from local KB plus UniProt data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "include_uniprot": {"type": "boolean", "default": True}
            },
            "required": ["name"]
        }
    },
    {
        "name": "lookup_enzyme_kinetics",
        "description": "Look up enzyme kinetics from BRENDA/ExPASy — Km, Vmax, kcat, substrate specificity, inhibition constants. More detailed than lookup_enzyme for kinetic questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "enzyme_name": {"type": "string", "description": "Enzyme name or EC number, e.g. 'cellulase', 'beta-glucosidase', '3.2.1.4'"}
            },
            "required": ["enzyme_name"]
        }
    },
    {
        "name": "lookup_chemical",
        "description": "Look up a chemical compound in PubChem. Essential for inhibitor analysis — acetic acid, formic acid, furfural, HMF, ethanol. Returns molecular data, inhibition thresholds, and fermentation context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "compound_name": {"type": "string", "description": "Chemical name, e.g. 'acetic acid', 'furfural', 'hydroxymethylfurfural'"}
            },
            "required": ["compound_name"]
        }
    },
    {
        "name": "calculate_yields",
        "description": "Calculate EH yield and fermentation efficiency from numbers. Use whenever Penny asks about yields, efficiency, or wants to know how a run performed vs theoretical maximum. Can compute from a run_id directly or from manually provided values.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Run ID to auto-compute from loaded records (e.g. 'FR009'). Leave blank to use manual inputs."},
                "glucose_released_g_l":  {"type": "number"},
                "glucan_content_pct":    {"type": "number", "description": "Glucan % in biomass (e.g. 33.5)"},
                "solids_loading_g_l":    {"type": "number", "description": "Biomass loading g/L"},
                "ethanol_final_g_l":     {"type": "number"},
                "glucose_t0_g_l":        {"type": "number"},
                "xylose_t0_g_l":         {"type": "number"},
                "glucose_final_g_l":     {"type": "number", "default": 0},
                "xylose_final_g_l":      {"type": "number", "default": 0},
            },
            "required": []
        }
    },
    {
        "name": "get_biomass_info",
        "description": "Get biomass composition data (glucan%, xylan%, lignin%) for SB, RS, CS, or ALB feedstocks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "biomass_code": {"type": "string", "description": "SB, RS, CS, or ALB"}
            },
            "required": ["biomass_code"]
        }
    },
    {
        "name": "compare_runs",
        "description": "Compare two or more ErgBio runs side by side across key analytes and timepoints.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_ids": {"type": "array", "items": {"type": "string"}},
                "analytes": {"type": "array", "items": {"type": "string"}, "default": ["Glucose", "Xylose", "Ethanol", "Acetic_Acid"]}
            },
            "required": ["run_ids"]
        }
    },
    {
        "name": "get_run_detail",
        "description": "Get full detail record for a specific run ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"}
            },
            "required": ["run_id"]
        }
    }
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _execute_tool(name: str, inputs: dict, records: dict) -> str:
    try:
        if name == "search_papers":
            return fmt_papers(search_papers(inputs["query"], inputs.get("limit", 5), inputs.get("source", "semantic_scholar")))

        elif name == "lookup_enzyme":
            return format_enzyme_for_context(lookup_enzyme(inputs["name"], inputs.get("include_uniprot", True)))

        elif name == "lookup_enzyme_kinetics":
            return fmt_brenda(lookup_enzyme_kinetics(inputs["enzyme_name"]))

        elif name == "lookup_chemical":
            return fmt_pubchem(get_fermentation_inhibitor_profile(inputs["compound_name"]))

        elif name == "calculate_yields":
            run_id = inputs.get("run_id")
            if run_id and run_id in records:
                return fmt_calc(calculate_from_run_record(records[run_id]))
            elif run_id:
                return f"Run '{run_id}' not found. Available: {list(records.keys())}"
            # Manual inputs
            results = {}
            if all(k in inputs for k in ["glucose_released_g_l", "glucan_content_pct", "solids_loading_g_l"]):
                results["eh_yield"] = calculate_eh_yield(
                    inputs["glucose_released_g_l"], inputs["glucan_content_pct"], inputs["solids_loading_g_l"]
                )
            if all(k in inputs for k in ["ethanol_final_g_l", "glucose_t0_g_l", "xylose_t0_g_l"]):
                results["ferm_efficiency"] = calculate_fermentation_efficiency(
                    inputs["ethanol_final_g_l"], inputs["glucose_t0_g_l"], inputs["xylose_t0_g_l"],
                    inputs.get("glucose_final_g_l", 0), inputs.get("xylose_final_g_l", 0)
                )
            if not results:
                return "Provide either a run_id or manual values (glucose_released_g_l, glucan_content_pct, etc.)"
            results["success"] = True
            return fmt_calc(results)

        elif name == "get_biomass_info":
            result = get_biomass_info(inputs["biomass_code"])
            return json.dumps(result, indent=2) if result.get("success") else result.get("error", "Not found")

        elif name == "compare_runs":
            run_ids  = inputs["run_ids"]
            analytes = inputs.get("analytes", ["Glucose", "Xylose", "Ethanol", "Acetic_Acid"])
            out = {"runs": run_ids, "analytes": {}, "computed_yields": {}}
            for analyte in analytes:
                out["analytes"][analyte] = {}
                for rid in run_ids:
                    rec = records.get(rid)
                    ts  = rec.get("analyte_timeseries", {}).get(analyte, {}) if rec else {}
                    out["analytes"][analyte][rid] = {str(k): round(v,2) if v else None for k,v in ts.items()} if ts else "NOT FOUND"
            for rid in run_ids:
                rec = records.get(rid)
                out["computed_yields"][rid] = rec.get("computed_yields", {}) if rec else "NOT FOUND"
            return json.dumps(out, indent=2)

        elif name == "get_run_detail":
            rid = inputs["run_id"]
            rec = records.get(rid)
            return json.dumps(rec, indent=2) if rec else f"Run '{rid}' not found. Available: {list(records.keys())}"

        return f"Unknown tool: {name}"

    except Exception as e:
        logger.error("Tool '%s' error: %s", name, e)
        return f"Tool error ({name}): {e}"


# ---------------------------------------------------------------------------
# Main chat function
# ---------------------------------------------------------------------------

def chat(user_message: str, history: list, records: Optional[dict] = None,
         on_tool_call: Optional[callable] = None) -> tuple[str, list]:
    if records is None:
        records = load_run_records()

    system = f"{SYSTEM_PROMPT}\n\n{_build_runs_context(records)}"
    messages = history + [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            system=system, tools=TOOLS, messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if on_tool_call:
                on_tool_call(block.name, block.input)
            result = _execute_tool(block.name, block.input, records)
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
        messages.append({"role": "user", "content": tool_results})

    text = next((b.text for b in response.content if hasattr(b, "text")), "")
    return text, messages


def get_run_summary(records: dict) -> str:
    if not records:
        return "No runs loaded"
    return " | ".join(f"{rid} ({rec.get('biomass_type','?')})" for rid, rec in records.items())
