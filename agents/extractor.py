"""
extractor.py — Run data extraction agent for ErgBio agentic pipeline.

Consumes the structured output from hplc_parser.parse_hplc_file() and
produces a clean, calculator-ready dict for each (run_id, fermenter) pair
found in the XLS file.

Primary analytes tracked:
  Glucose, Xylose, Arabinose, Ethanol, Acetic_Acid, Glycerol

Usage:
    from agents.extractor import extract_runs
    runs = extract_runs("/path/to/20260716_FR009_Short.XLS")
    # returns list of dicts, one per (run_id, fermenter) combination
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Analytes we extract for the calculator and reporter
PRIMARY_ANALYTES = [
    "Glucose", "Xylose", "Arabinose",
    "Ethanol", "Acetic_Acid", "Glycerol",
    "Cellobiose", "Xylitol", "Succinic_Acid",
    "Formic_Acid", "Citric_Acid",
]


def _infer_metadata(source_file: str, run_id: str) -> dict:
    """
    Ask Claude Haiku to infer operator and biomass type from the XLS filename.

    Falls back gracefully if the API call fails or returns non-JSON.
    """
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": f"""From this HPLC filename and run ID, infer run metadata. Return ONLY valid JSON.

Source file: {source_file}
Run ID: {run_id}

Return JSON with exactly these fields:
- operator: person name if visible in filename, otherwise "Unknown"
- biomass_type: one of SB (switchgrass), RS (rice straw), ALB (albizia),
                CS (corn stover), MN (miscanthus) — if recognisable, otherwise "Unknown"
- notes: any other useful context from the filename (or "")

Return ONLY valid JSON. No explanation, no markdown."""
        }]
    )

    try:
        return json.loads(message.content[0].text)
    except (json.JSONDecodeError, IndexError, AttributeError):
        return {"operator": "Unknown", "biomass_type": "Unknown", "notes": ""}


def extract_run(file_path: str, run_id: str, fermenter: int) -> dict:
    """
    Extract data for a single (run_id, fermenter) from a parsed HPLC file.

    Returns a calculator-ready dict with:
        success, run_id, fermenter, date, source_file,
        timepoints, analyte_timeseries, final_values, t0_values,
        qc_flags, operator, biomass_type
    """
    from tools.hplc_parser import parse_hplc_file, get_timeseries, get_value_at

    parsed = parse_hplc_file(file_path)
    if not parsed["success"]:
        return {"success": False, "error": f"HPLC parse failed: {parsed['error']}"}

    if run_id not in parsed["run_ids"]:
        return {"success": False,
                "error": f"Run ID '{run_id}' not found in {parsed['source_file']}. "
                         f"Available: {parsed['run_ids']}"}

    # Collect timepoints for this run/fermenter
    all_timepoints = set()
    for sample in parsed["samples"].values():
        if sample["run_id"] == run_id and sample["fermenter"] == fermenter:
            if sample["timepoint_h"] is not None:
                all_timepoints.add(sample["timepoint_h"])
    timepoints = sorted(all_timepoints)

    if not timepoints:
        return {"success": False,
                "error": f"No timepoints found for {run_id} fermenter {fermenter}"}

    # Build timeseries for each analyte
    analyte_timeseries = {}
    for analyte in PRIMARY_ANALYTES:
        ts = get_timeseries(parsed, run_id, fermenter, analyte)
        if ts:
            analyte_timeseries[analyte] = ts

    # Convenience: t0 and final values for key analytes
    t0_h    = timepoints[0]
    final_h = timepoints[-1]

    def _val(analyte, tp):
        return get_value_at(parsed, run_id, fermenter, analyte, tp)

    t0_values = {a: _val(a, t0_h) for a in PRIMARY_ANALYTES}
    final_values = {a: _val(a, final_h) for a in PRIMARY_ANALYTES}

    # Date from the first matching sample
    date = None
    for sample in parsed["samples"].values():
        if sample["run_id"] == run_id and sample["fermenter"] == fermenter:
            date = sample["date"]
            break

    # Infer operator and biomass type from filename via Claude
    try:
        meta = _infer_metadata(parsed["source_file"], run_id)
    except Exception as e:
        logger.warning("Claude metadata inference failed: %s", e)
        meta = {"operator": "Unknown", "biomass_type": "Unknown", "notes": ""}

    return {
        "success":            True,
        "run_id":             run_id,
        "fermenter":          fermenter,
        "date":               date,
        "source_file":        parsed["source_file"],
        "timepoints":         timepoints,
        "analyte_timeseries": analyte_timeseries,
        "t0_values":          t0_values,
        "final_values":       final_values,
        "analyte_qc":         parsed["analyte_qc"],
        "qc_flags":           parsed["qc_flags"],
        "operator":           meta.get("operator", "Unknown"),
        "biomass_type":       meta.get("biomass_type", "Unknown"),
        "notes":              meta.get("notes", ""),
    }


def extract_runs(file_path: str) -> list:
    """
    Extract all (run_id, fermenter) combinations from an XLS file.

    Returns a list of extractor dicts (one per unique run/fermenter pair).
    Call this from agent.py to process an entire HPLC file.
    """
    from tools.hplc_parser import parse_hplc_file

    parsed = parse_hplc_file(file_path)
    if not parsed["success"]:
        return [{"success": False, "error": parsed["error"]}]

    # Find all unique (run_id, fermenter) pairs
    pairs = set()
    for sample in parsed["samples"].values():
        pairs.add((sample["run_id"], sample["fermenter"]))

    results = []
    for run_id, fermenter in sorted(pairs):
        result = extract_run(file_path, run_id, fermenter)
        results.append(result)

    return results
