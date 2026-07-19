"""
enzyme_lookup.py — Enzyme information lookup for the Penny Agent.

Two sources:
  1. Local KB  (data/enzyme_kb.json) — ErgBio-curated, always available
  2. UniProt   (free REST API)        — protein-level details for any enzyme

Usage:
    from tools.enzyme_lookup import lookup_enzyme
    info = lookup_enzyme("Cellic CTec3")
"""

import json
import requests
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

KB_PATH  = Path(__file__).parent.parent / "data" / "enzyme_kb.json"
UNIPROT_SEARCH = "https://rest.uniprot.org/uniprotkb/search"
TIMEOUT  = 12


def _load_kb() -> dict:
    try:
        with open(KB_PATH) as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Could not load enzyme KB: %s", e)
        return {"enzymes": [], "biomass_types": {}}


def _kb_lookup(query: str) -> Optional[dict]:
    """Find enzyme by commercial name (fuzzy, case-insensitive)."""
    kb = _load_kb()
    q = query.lower().strip()
    for enz in kb.get("enzymes", []):
        name = enz.get("commercial_name", "").lower()
        if q in name or name in q:
            return enz
    return None


def _uniprot_lookup(enzyme_name: str, limit: int = 3) -> list[dict]:
    """
    Search UniProt for protein entries matching an enzyme name.
    Returns key functional data.
    """
    try:
        resp = requests.get(
            UNIPROT_SEARCH,
            params={
                "query":  f"{enzyme_name} AND organism_id:9606 OR (cellulase OR hemicellulase OR xylanase)",
                "fields": "accession,protein_name,organism_name,cc_function,cc_catalytic_activity,ft_binding",
                "format": "json",
                "size":   limit,
            },
            timeout=TIMEOUT,
            headers={"User-Agent": "ErgBio-Research-Agent/1.0"}
        )
        # Retry with simpler query if first fails
        if not resp.ok:
            resp = requests.get(
                UNIPROT_SEARCH,
                params={"query": enzyme_name, "fields": "accession,protein_name,organism_name,cc_function",
                        "format": "json", "size": limit},
                timeout=TIMEOUT,
                headers={"User-Agent": "ErgBio-Research-Agent/1.0"}
            )
        resp.raise_for_status()
        results = []
        for entry in resp.json().get("results", []):
            name_obj = entry.get("proteinDescription", {})
            rec_name = name_obj.get("recommendedName", {})
            full_name = (rec_name.get("fullName") or {}).get("value", "Unknown")

            comments = entry.get("comments", [])
            function_text = next(
                (c["texts"][0]["value"] for c in comments
                 if c.get("commentType") == "FUNCTION" and c.get("texts")),
                None
            )
            results.append({
                "accession": entry.get("primaryAccession"),
                "name":      full_name,
                "organism":  entry.get("organism", {}).get("scientificName"),
                "function":  (function_text or "")[:500],
                "url":       f"https://www.uniprot.org/uniprotkb/{entry.get('primaryAccession')}",
            })
        return results
    except Exception as e:
        logger.warning("UniProt lookup failed: %s", e)
        return []


def lookup_enzyme(name: str, include_uniprot: bool = True) -> dict:
    """
    Look up an enzyme by commercial name or common name.

    Checks local ErgBio KB first (most relevant for ErgBio context),
    then optionally fetches protein-level details from UniProt.

    Returns dict with:
        success          bool
        source           "local_kb" | "uniprot" | "both" | "not_found"
        local_entry      dict from ErgBio KB (if found)
        uniprot_entries  list of UniProt hits (if requested)
        error            str (only on failure)
    """
    local = _kb_lookup(name)
    uniprot = []
    if include_uniprot:
        uniprot = _uniprot_lookup(name, limit=2)

    if not local and not uniprot:
        return {
            "success": False,
            "source":  "not_found",
            "error":   f"No information found for '{name}'. "
                       f"Try the commercial name (e.g. 'Cellic CTec3') or EC number.",
        }

    source = "both" if (local and uniprot) else ("local_kb" if local else "uniprot")

    return {
        "success":         True,
        "source":          source,
        "local_entry":     local,
        "uniprot_entries": uniprot,
    }


def get_biomass_info(biomass_code: str) -> dict:
    """
    Return biomass composition data from local KB.

    Args:
        biomass_code: "SB", "RS", "CS", "ALB" etc.

    Returns dict with composition data or error.
    """
    kb = _load_kb()
    code = biomass_code.upper().strip()
    entry = kb.get("biomass_types", {}).get(code)
    if not entry:
        available = list(kb.get("biomass_types", {}).keys())
        return {
            "success": False,
            "error":   f"Biomass '{biomass_code}' not in KB. Available: {available}",
        }
    return {"success": True, "code": code, **entry}


def list_enzymes() -> list[str]:
    """Return list of enzyme names in the local KB."""
    kb = _load_kb()
    return [e.get("commercial_name", "") for e in kb.get("enzymes", [])]


def format_enzyme_for_context(result: dict) -> str:
    """Format enzyme lookup result as readable string for LLM context."""
    if not result.get("success"):
        return f"Enzyme lookup: {result.get('error', 'Not found')}"

    lines = []
    local = result.get("local_entry")
    if local:
        lines.append(f"=== {local['commercial_name']} ({local['manufacturer']}) ===")
        lines.append(f"Type: {local['type']}")
        lines.append(f"Substrates: {', '.join(local['primary_substrates'])}")
        lines.append(f"Products: {', '.join(local['products'])}")
        lines.append(f"Optimal conditions: {local['optimal_temp_c']}°C, pH {local['optimal_ph']}")
        lines.append(f"pH range: {local['ph_range']} | Temp range: {local['temp_range_c']}°C")
        lines.append(f"Typical loading: {local['typical_loading_mg_per_g_biomass']} mg/g biomass")
        lines.append(f"Inhibitors: {', '.join(local['inhibitors'])}")
        lines.append(f"Strengths: {local['known_strengths']}")
        lines.append(f"Limitations: {local['known_limitations']}")
        if local.get("ergbio_notes"):
            lines.append(f"ErgBio notes: {local['ergbio_notes']}")
        if local.get("lot_numbers_used"):
            lines.append(f"Lots used at ErgBio: {', '.join(local['lot_numbers_used'])}")

    for u in result.get("uniprot_entries", []):
        lines.append(f"\n[UniProt {u['accession']}] {u['name']} ({u.get('organism', '')})")
        if u.get("function"):
            lines.append(f"  Function: {u['function'][:300]}")
        lines.append(f"  URL: {u['url']}")

    return "\n".join(lines)
