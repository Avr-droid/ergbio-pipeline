"""
penny_agent.py — ErgBio Research Assistant Agent for Penny and the science team.

Claude Sonnet with tool use. Loaded context at startup:
  - All run records from data/run_records/
  - Enzyme KB summary
  - ErgBio process context

Available tools:
  search_papers     — Semantic Scholar / PubMed literature search
  lookup_enzyme     — Local KB + UniProt enzyme information
  get_biomass_info  — Biomass composition from local KB
  compare_runs      — Side-by-side comparison of two or more runs
  get_run_detail    — Full detail for a specific run ID
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

from tools.literature_search import search_papers, format_for_context
from tools.enzyme_lookup import (
    lookup_enzyme, get_biomass_info, list_enzymes, format_enzyme_for_context
)

load_dotenv()
logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

RUN_RECORDS_DIR = Path(__file__).parent.parent / "data" / "run_records"
MODEL            = "claude-sonnet-4-6"
MAX_TOKENS       = 4096

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the ErgBio Research Assistant — a scientific peer and reasoning partner for the ErgBio team, especially Penny (CEO) and the lab scientists.

ErgBio is a biotech company focused on cellulosic ethanol production from lignocellulosic biomass (switchgrass, rice straw, corn stover, albizia). The process:
  1. Pretreatment — breaks down the lignin structure to expose cellulose/hemicellulose
  2. Enzymatic Hydrolysis (EH) — cellulase cocktails convert cellulose→glucose, hemicellulose→xylose
  3. Fermentation — microorganisms (yeast or bacteria) convert sugars→ethanol

KEY METRICS ErgBio tracks:
  - EH Yield (%) = glucose released ÷ theoretical maximum from glucan content × 100
  - Fermentation Efficiency (%) = ethanol produced ÷ theoretical maximum from sugars × 100
  - Sugar consumption: did the organism consume all glucose AND xylose?
  - Inhibitor accumulation: acetic acid, formic acid, furfural can stall fermentation
  - Cellobiose: if elevated, indicates insufficient beta-glucosidase activity

HPLC analytes measured at each timepoint (g/L):
  Cellobiose, Glucose, Xylose, Arabinose, Xylitol, Succinic_Acid,
  Glycerol, Formic_Acid, Acetic_Acid, Ethanol, Citric_Acid

EXPERIMENTAL RUN RECORDS are loaded below. These are ErgBio's actual data. When reasoning about performance, always ground your analysis in the specific numbers from these records.

HOW TO BEHAVE:
- Reason like a senior biochemical engineer / fermentation scientist
- Be specific: cite actual numbers from run records, not vague generalities
- When you search literature, tell the team which papers you found and why they're relevant
- Flag potential problems proactively (e.g. acetic acid level approaching inhibition threshold)
- Make concrete experimental suggestions with reasoning
- Be honest about uncertainty and small sample size (currently only a few runs)
- Don't hallucinate enzyme lot numbers or yield values — use only what's in the run records
- When comparing to literature, note whether ErgBio's conditions match the paper's conditions

TOOL USE:
- Use search_papers when the team asks about mechanisms, benchmarks, or optimal conditions that aren't in the run data
- Use lookup_enzyme when discussing specific enzyme products
- Use compare_runs when asked to compare experiments
- Always cite your sources (run ID for data, paper title/DOI for literature)"""


# ---------------------------------------------------------------------------
# Run record loading
# ---------------------------------------------------------------------------

def load_run_records() -> dict:
    """Load all run JSON files from data/run_records/. Returns {run_id: record}."""
    records = {}
    if not RUN_RECORDS_DIR.exists():
        RUN_RECORDS_DIR.mkdir(parents=True, exist_ok=True)
        return records

    for fpath in sorted(RUN_RECORDS_DIR.glob("*.json")):
        try:
            with open(fpath) as f:
                rec = json.load(f)
            run_id = rec.get("run_id", fpath.stem)
            records[run_id] = rec
        except Exception as e:
            logger.warning("Could not load run record %s: %s", fpath.name, e)

    return records


def _build_runs_context(records: dict) -> str:
    """Serialize run records into a compact context string."""
    if not records:
        return "No run records loaded yet. Records will appear here once runs are processed through the pipeline."

    lines = [f"=== ErgBio Run Records ({len(records)} runs) ===\n"]
    for run_id, rec in records.items():
        lines.append(f"--- {run_id} (Fermenter {rec.get('fermenter', '?')}) ---")
        lines.append(f"Date: {rec.get('date', 'Unknown')} | Biomass: {rec.get('biomass_type', 'Unknown')}")
        lines.append(f"Enzyme: {rec.get('enzyme', 'Unknown')} | Operator: {rec.get('operator', 'Unknown')}")
        if rec.get("conditions"):
            lines.append(f"Conditions: {json.dumps(rec['conditions'])}")
        lines.append(f"Timepoints (h): {rec.get('timepoints', [])}")

        # Key analyte timeseries
        ts = rec.get("analyte_timeseries", {})
        for analyte in ["Glucose", "Xylose", "Ethanol", "Acetic_Acid", "Cellobiose"]:
            if analyte in ts:
                vals = {str(k): round(v, 2) if v is not None else None
                        for k, v in ts[analyte].items()}
                lines.append(f"  {analyte} (g/L): {vals}")

        # Computed yields
        if rec.get("computed_yields"):
            lines.append(f"Computed yields: {json.dumps(rec['computed_yields'])}")

        # QC flags
        if rec.get("qc_flags"):
            lines.append(f"QC flags: {rec['qc_flags'][:3]}")  # first 3

        if rec.get("notes"):
            lines.append(f"Notes: {rec['notes']}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool definitions (Claude tool use API format)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "search_papers",
        "description": (
            "Search scientific literature (Semantic Scholar + PubMed) for papers "
            "relevant to a question about enzymatic hydrolysis, fermentation, enzyme "
            "performance, inhibitor effects, or cellulosic ethanol production. "
            "Use when you need benchmarks, mechanistic explanations, or optimal condition "
            "ranges that aren't answered by ErgBio's own run data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query. Be specific — e.g. 'acetic acid inhibition xylose fermentation Saccharomyces cerevisiae' rather than 'fermentation problems'."
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of papers to return (2–8 recommended). Default 5.",
                    "default": 5
                },
                "source": {
                    "type": "string",
                    "enum": ["semantic_scholar", "pubmed", "both"],
                    "description": "Which database to search. Default: semantic_scholar.",
                    "default": "semantic_scholar"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "lookup_enzyme",
        "description": (
            "Look up information about a specific enzyme product: optimal conditions, "
            "substrates, inhibitors, known strengths/limitations, and ErgBio-specific notes. "
            "Checks the ErgBio local KB first, then UniProt for protein-level detail."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Enzyme commercial name (e.g. 'Cellic CTec3') or common name (e.g. 'cellulase', 'xylanase')."
                },
                "include_uniprot": {
                    "type": "boolean",
                    "description": "Whether to also fetch protein details from UniProt. Default true.",
                    "default": True
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "get_biomass_info",
        "description": "Get biomass composition data (glucan%, xylan%, lignin%) for a feedstock type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "biomass_code": {
                    "type": "string",
                    "description": "Biomass code: SB (switchgrass), RS (rice straw), CS (corn stover), ALB (albizia)."
                }
            },
            "required": ["biomass_code"]
        }
    },
    {
        "name": "compare_runs",
        "description": (
            "Compare two or more ErgBio runs side by side. Returns a structured comparison "
            "of key metrics: glucose yield, xylose consumption, ethanol production, "
            "acetic acid levels, and computed yields across timepoints."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "run_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of run IDs to compare (e.g. ['FR003', 'FR009'])."
                },
                "analytes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Which analytes to include. Default: ['Glucose', 'Xylose', 'Ethanol', 'Acetic_Acid'].",
                    "default": ["Glucose", "Xylose", "Ethanol", "Acetic_Acid"]
                }
            },
            "required": ["run_ids"]
        }
    },
    {
        "name": "get_run_detail",
        "description": "Get the full detail record for a specific run ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "string",
                    "description": "Run ID, e.g. 'FR009'."
                }
            },
            "required": ["run_id"]
        }
    }
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def _execute_tool(name: str, inputs: dict, records: dict) -> str:
    """Dispatch a tool call and return the result as a string."""
    try:
        if name == "search_papers":
            result = search_papers(
                query=inputs["query"],
                limit=inputs.get("limit", 5),
                source=inputs.get("source", "semantic_scholar")
            )
            return format_for_context(result)

        elif name == "lookup_enzyme":
            result = lookup_enzyme(
                name=inputs["name"],
                include_uniprot=inputs.get("include_uniprot", True)
            )
            return format_enzyme_for_context(result)

        elif name == "get_biomass_info":
            result = get_biomass_info(inputs["biomass_code"])
            if result.get("success"):
                return json.dumps(result, indent=2)
            return result.get("error", "Not found")

        elif name == "compare_runs":
            run_ids  = inputs["run_ids"]
            analytes = inputs.get("analytes", ["Glucose", "Xylose", "Ethanol", "Acetic_Acid"])
            comparison = {"runs_compared": run_ids, "analytes": {}}
            for analyte in analytes:
                comparison["analytes"][analyte] = {}
                for rid in run_ids:
                    rec = records.get(rid)
                    if not rec:
                        comparison["analytes"][analyte][rid] = "RUN NOT FOUND"
                        continue
                    ts = rec.get("analyte_timeseries", {}).get(analyte, {})
                    comparison["analytes"][analyte][rid] = {
                        str(k): round(v, 2) if v is not None else None
                        for k, v in ts.items()
                    }
            # Also compare computed yields
            comparison["computed_yields"] = {}
            for rid in run_ids:
                rec = records.get(rid)
                comparison["computed_yields"][rid] = rec.get("computed_yields", {}) if rec else "NOT FOUND"
            return json.dumps(comparison, indent=2)

        elif name == "get_run_detail":
            run_id = inputs["run_id"]
            rec = records.get(run_id)
            if not rec:
                available = list(records.keys())
                return f"Run '{run_id}' not found. Available runs: {available}"
            return json.dumps(rec, indent=2)

        else:
            return f"Unknown tool: {name}"

    except Exception as e:
        logger.error("Tool '%s' failed: %s", name, e)
        return f"Tool error ({name}): {str(e)}"


# ---------------------------------------------------------------------------
# Main agent function
# ---------------------------------------------------------------------------

def chat(
    user_message: str,
    history: list[dict],
    records: Optional[dict] = None,
    on_tool_call: Optional[callable] = None,
) -> tuple[str, list[dict]]:
    """
    Send a message to the Penny Agent and get a response.

    Args:
        user_message : The scientist's question or message.
        history      : Conversation history (list of {role, content} dicts).
                       Pass [] for a new conversation.
        records      : Run records dict. If None, loads from disk.
        on_tool_call : Optional callback(tool_name, inputs) called when a tool fires.
                       Use this in the Streamlit UI to show live tool status.

    Returns:
        (response_text, updated_history)
    """
    if records is None:
        records = load_run_records()

    # Build system prompt with run context injected
    runs_context = _build_runs_context(records)
    system = f"{SYSTEM_PROMPT}\n\n{runs_context}"

    # Append user message to history
    messages = history + [{"role": "user", "content": user_message}]

    # Agentic loop — keep going until Claude stops calling tools
    while True:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        # Append Claude's response to history
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            break

        # Execute all tool calls in this response
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            if on_tool_call:
                on_tool_call(block.name, block.input)

            result = _execute_tool(block.name, block.input, records)
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": block.id,
                "content":     result,
            })

        messages.append({"role": "user", "content": tool_results})

    # Extract final text response
    text = next(
        (block.text for block in response.content if hasattr(block, "text")),
        ""
    )

    return text, messages


def get_run_summary(records: dict) -> str:
    """One-line summary of loaded runs for sidebar display."""
    if not records:
        return "No runs loaded"
    summaries = []
    for rid, rec in records.items():
        tp = rec.get("timepoints", [])
        biomass = rec.get("biomass_type", "?")
        summaries.append(f"{rid} ({biomass}, {len(tp)} timepoints)")
    return " | ".join(summaries)
