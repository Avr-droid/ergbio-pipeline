import os
import json
import anthropic
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def extract_data(file_path: str) -> dict:
    """
    Extract all run data from an HPLC file.

    Step 1 — Parse the file with hplc_parser to get numerical values
             (ethanol, glucose, xylose at each timepoint).
    Step 2 — Ask Claude to infer run metadata from the filename
             (run name, date, operator, biomass type).
    Step 3 — Combine and return one clean dict ready for the calculator.
    """

    # Import here to avoid circular imports at module load time
    from tools.hplc_parser import parse_hplc_file

    # --- Step 1: Parse the HPLC file ---
    parsed = parse_hplc_file(file_path)
    if not parsed["success"]:
        return {"success": False, "error": f"HPLC parse failed: {parsed['error']}"}

    # --- Step 2: Use Claude to infer metadata from the filename ---
    # The HPLC file contains numbers only — run name, date, operator, and
    # biomass type have to be inferred from context (usually the filename).
    filename = Path(file_path).stem  # e.g. "CBP_Run47_SB_20250714"

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{
            "role": "user",
            "content": f"""From this HPLC filename, extract run metadata. Return ONLY valid JSON.

Filename: {filename}

Return JSON with exactly these fields:
- run_name: descriptive name for this run (use filename if unclear)
- date: date in YYYY-MM-DD format (infer from filename digits, or use "Unknown")
- operator: person name if visible in filename, otherwise "Unknown"
- biomass_type: one of SB, RS, ALB, CS, MN if recognisable, otherwise "Unknown"

Return ONLY valid JSON. No explanation, no markdown."""
        }]
    )

    # Parse Claude's response — fall back gracefully if it returns non-JSON
    try:
        metadata = json.loads(message.content[0].text)
    except (json.JSONDecodeError, IndexError):
        metadata = {
            "run_name": filename,
            "date": "Unknown",
            "operator": "Unknown",
            "biomass_type": "Unknown",
        }

    # --- Step 3: Combine metadata + HPLC numbers ---
    return {
        "success": True,
        # Run metadata (from Claude's inference)
        "run_name":     metadata.get("run_name", filename),
        "date":         metadata.get("date", "Unknown"),
        "operator":     metadata.get("operator", "Unknown"),
        "biomass_type": metadata.get("biomass_type", "Unknown"),
        # Key values the calculator needs (from parser)
        "ethanol_t0":    parsed["ethanol_t0"],
        "ethanol_final": parsed["ethanol_final"],
        "glucose_final": parsed["glucose_final"],
        "xylose_final":  parsed["xylose_final"],
        # Full timeseries (for trends and reporting)
        "timepoints":     parsed["timepoints"],
        "ethanol_series": parsed["ethanol"],
        "glucose_series": parsed["glucose"],
        "xylose_series":  parsed["xylose"],
    }
