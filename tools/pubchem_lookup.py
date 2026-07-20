"""
pubchem_lookup.py — PubChem chemical compound lookup for the Penny Agent.

Free REST API, no authentication required.
Useful for: inhibitor properties (acetic acid, furfural, HMF, formic acid),
molecular weights, boiling/melting points, solubility, chemical safety.

API docs: https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest
"""

import requests
import logging

logger = logging.getLogger(__name__)

BASE   = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
TIMEOUT = 12

# Properties most relevant to fermentation inhibitor analysis
PROPERTIES = ",".join([
    "MolecularFormula",
    "MolecularWeight",
    "IUPACName",
    "IsomericSMILES",
    "XLogP",
    "TPSA",
    "Complexity",
    "HBondDonorCount",
    "HBondAcceptorCount",
])


def lookup_compound(name: str) -> dict:
    """
    Look up a chemical compound by name.

    Returns dict with:
        success          bool
        cid              PubChem Compound ID
        name             canonical name
        formula          molecular formula
        molecular_weight g/mol
        iupac_name       systematic name
        description      bioactivity/function summary
        url              PubChem page URL
        error            str (only on failure)
    """
    try:
        # Step 1: resolve name → CID
        cid_resp = requests.get(
            f"{BASE}/compound/name/{requests.utils.quote(name)}/cids/JSON",
            timeout=TIMEOUT
        )
        if cid_resp.status_code == 404:
            return {"success": False, "error": f"Compound '{name}' not found in PubChem"}
        cid_resp.raise_for_status()
        cid = cid_resp.json()["IdentifierList"]["CID"][0]

        # Step 2: get properties
        prop_resp = requests.get(
            f"{BASE}/compound/cid/{cid}/property/{PROPERTIES}/JSON",
            timeout=TIMEOUT
        )
        prop_resp.raise_for_status()
        props = prop_resp.json()["PropertyTable"]["Properties"][0]

        # Step 3: get description/bioactivity
        desc_resp = requests.get(
            f"{BASE}/compound/cid/{cid}/description/JSON",
            timeout=TIMEOUT
        )
        description = ""
        if desc_resp.ok:
            sections = desc_resp.json().get("InformationList", {}).get("Information", [])
            for s in sections:
                if s.get("Description"):
                    description = s["Description"][:600]
                    break

        return {
            "success":          True,
            "cid":              cid,
            "name":             name,
            "formula":          props.get("MolecularFormula"),
            "molecular_weight": props.get("MolecularWeight"),
            "iupac_name":       props.get("IUPACName"),
            "xlogp":            props.get("XLogP"),
            "description":      description,
            "url":              f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
        }

    except Exception as e:
        logger.warning("PubChem lookup failed for '%s': %s", name, e)
        return {"success": False, "error": str(e)}


def get_fermentation_inhibitor_profile(compound_name: str) -> dict:
    """
    Convenience wrapper focused on fermentation inhibitor context.
    Also searches for known inhibition concentration data from literature context.
    """
    result = lookup_compound(compound_name)
    if not result["success"]:
        return result

    # Add fermentation-specific context for known inhibitors
    inhibitor_context = {
        "acetic acid": {
            "inhibition_threshold_g_l": "3–5 g/L begins inhibiting most yeast strains; >10 g/L severely inhibits",
            "mechanism": "Undissociated form crosses cell membrane, acidifies cytoplasm, uncouples membrane potential",
            "note": "ErgBio target: keep below 5 g/L at 96h"
        },
        "formic acid": {
            "inhibition_threshold_g_l": ">1 g/L inhibitory; >3 g/L severely toxic to yeast",
            "mechanism": "Inhibits mitochondrial respiration; more toxic than acetic acid per mole",
            "note": "ErgBio: FR003 Formic_Acid R²=0.9647 (unreliable measurement — interpret with caution)"
        },
        "furfural": {
            "inhibition_threshold_g_l": ">1 g/L inhibitory to Saccharomyces cerevisiae",
            "mechanism": "Inhibits glycolytic enzymes (alcohol dehydrogenase, aldehyde dehydrogenase)",
            "note": "Produced during hemicellulose degradation in pretreatment; not currently measured in ErgBio HPLC panel"
        },
        "hydroxymethylfurfural": {
            "inhibition_threshold_g_l": ">2 g/L inhibitory",
            "mechanism": "Similar to furfural; synergistic inhibition when combined with weak acids",
            "note": "HMF; from cellulose degradation in pretreatment"
        },
        "ethanol": {
            "inhibition_threshold_g_l": ">40 g/L inhibitory to most yeast; tolerance varies by strain",
            "mechanism": "Membrane fluidity disruption at high concentrations",
            "note": "ErgBio current range (8–10 g/L) well below inhibition threshold"
        },
    }

    key = compound_name.lower().strip()
    context = inhibitor_context.get(key, {})
    result["fermentation_context"] = context

    return result


def format_for_context(result: dict) -> str:
    """Format PubChem result as readable string for LLM context."""
    if not result["success"]:
        return f"PubChem lookup failed: {result.get('error')}"

    lines = [
        f"=== {result['name']} (PubChem CID: {result['cid']}) ===",
        f"Formula: {result.get('formula')} | MW: {result.get('molecular_weight')} g/mol",
        f"IUPAC name: {result.get('iupac_name', 'N/A')}",
    ]
    if result.get("description"):
        lines.append(f"Description: {result['description']}")

    ctx = result.get("fermentation_context", {})
    if ctx:
        lines.append("\n[Fermentation Inhibitor Context]")
        if ctx.get("inhibition_threshold_g_l"):
            lines.append(f"  Inhibition threshold: {ctx['inhibition_threshold_g_l']}")
        if ctx.get("mechanism"):
            lines.append(f"  Mechanism: {ctx['mechanism']}")
        if ctx.get("note"):
            lines.append(f"  ErgBio note: {ctx['note']}")

    lines.append(f"URL: {result.get('url')}")
    return "\n".join(lines)
