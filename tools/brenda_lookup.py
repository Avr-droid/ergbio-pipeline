"""
brenda_lookup.py — BRENDA enzyme database lookup for the Penny Agent.

BRENDA (https://www.brenda-enzymes.org) is the world's most comprehensive
enzyme database — kinetic constants (Km, Vmax, kcat), inhibitor data,
substrate specificity, organism sources.

Setup (one-time, free):
  1. Register at https://www.brenda-enzymes.org/register.php
  2. Add to Streamlit secrets:
       BRENDA_EMAIL = "your@email.com"
       BRENDA_PASSWORD = "yourpassword"

Until credentials are configured, falls back to ExplorEnz (free, no auth)
which covers EC number lookups and basic enzyme classification.
"""

import os
import hashlib
import requests
import logging
try:
    import streamlit as st
    HAS_STREAMLIT = True
except ImportError:
    st = None
    HAS_STREAMLIT = False

logger = logging.getLogger(__name__)

EXPLORENZ_URL = "https://enzyme.expasy.org/EC/{ec}.txt"
TIMEOUT = 12


def _get_brenda_credentials():
    """Pull BRENDA credentials from Streamlit secrets or env."""
    try:
        if HAS_STREAMLIT and st:
            email    = st.secrets.get("BRENDA_EMAIL")
    
    
    



    except Exception:
        pass
    return os.getenv("BRENDA_EMAIL"), os.getenv("BRENDA_PASSWORD")


def _brenda_soap_query(email: str, password: str, enzyme_name: str) -> dict:
    """
    Query BRENDA via SOAP API.
    Requires: pip install zeep
    """
    try:
        from zeep import Client as SoapClient
        pw_hash = hashlib.sha256(f"{password}".encode()).hexdigest()
        client  = SoapClient("https://www.brenda-enzymes.org/soap/brenda_zeep.wsdl")
        params  = f"{email},{pw_hash},{enzyme_name},,,,"
        result  = client.service.getKmValue(params)
        return {"success": True, "source": "BRENDA", "data": str(result)[:2000]}
    except ImportError:
        return {"success": False, "error": "zeep not installed — run: pip install zeep"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _explorenz_lookup(ec_number: str) -> dict:
    """
    Free fallback: ExPASy enzyme lookup by EC number.
    e.g. ec_number = "3.2.1.4" (cellulase)
    """
    try:
        resp = requests.get(
            f"https://enzyme.expasy.org/EC/{ec_number}",
            timeout=TIMEOUT,
            headers={"Accept": "text/plain"}
        )
        if not resp.ok:
            return {"success": False, "error": f"EC {ec_number} not found"}
        return {
            "success": True,
            "source":  "ExPASy EnzymeDB",
            "ec":      ec_number,
            "data":    resp.text[:1500],
            "url":     f"https://enzyme.expasy.org/EC/{ec_number}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# Common EC numbers for ErgBio-relevant enzymes
ENZYME_EC_MAP = {
    "cellulase":               "3.2.1.4",
    "cellobiohydrolase":       "3.2.1.91",
    "beta-glucosidase":        "3.2.1.21",
    "xylanase":                "3.2.1.8",
    "beta-xylosidase":         "3.2.1.37",
    "arabinofuranosidase":     "3.2.1.55",
    "laccase":                 "1.10.3.2",
    "alcohol dehydrogenase":   "1.1.1.1",
    "pyruvate decarboxylase":  "4.1.1.1",
    "cellic ctec3":            "3.2.1.4",   # cellulase cocktail, use cellulase EC
    "cellic ctec2":            "3.2.1.4",
    "accellerase 1500":        "3.2.1.4",
}


def lookup_enzyme_kinetics(enzyme_name: str) -> dict:
    """
    Look up enzyme kinetics and substrate data.

    Tries BRENDA first (if credentials configured), falls back to ExPASy.

    Returns dict with kinetic data, substrate info, inhibitors, and source.
    """
    email, password = _get_brenda_credentials()

    # Try BRENDA if credentials available
    if email and password:
        result = _brenda_soap_query(email, password, enzyme_name)
        if result["success"]:
            return result

    # Fall back to ExPASy by EC number
    ec = ENZYME_EC_MAP.get(enzyme_name.lower().strip())
    if ec:
        result = _explorenz_lookup(ec)
        result["enzyme_name"] = enzyme_name
        result["ec_number"]   = ec
        result["note"] = (
            "Basic EC classification data from ExPASy. "
            "For full kinetic constants (Km, Vmax, inhibition data), "
            "configure BRENDA credentials in Streamlit secrets."
        )
        return result

    # Last resort: search by name in ExPASy
    try:
        search = requests.get(
            f"https://enzyme.expasy.org/cgi-bin/enzyme/enzyme-search-enzyme?field=DE&query={requests.utils.quote(enzyme_name)}",
            timeout=TIMEOUT
        )
        return {
            "success":     True,
            "source":      "ExPASy search",
            "enzyme_name": enzyme_name,
            "data":        search.text[:1000] if search.ok else "No results",
            "note":        "Configure BRENDA credentials for detailed kinetics data.",
            "setup_instructions": (
                "To enable full BRENDA access:\n"
                "1. Register free at https://www.brenda-enzymes.org/register.php\n"
                "2. Add to Streamlit secrets:\n"
                "   BRENDA_EMAIL = 'your@email.com'\n"
                "   BRENDA_PASSWORD = 'yourpassword'"
            )
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def format_for_context(result: dict) -> str:
    """Format BRENDA/ExPASy result for LLM context."""
    if not result.get("success"):
        return f"Enzyme kinetics lookup failed: {result.get('error')}"

    lines = [f"=== Enzyme Kinetics: {result.get('enzyme_name', '')} ==="]
    lines.append(f"Source: {result.get('source', 'Unknown')}")
    if result.get("ec_number"):
        lines.append(f"EC Number: {result['ec_number']}")
    if result.get("url"):
        lines.append(f"URL: {result['url']}")
    if result.get("data"):
        lines.append(f"\nData:\n{result['data'][:1200]}")
    if result.get("note"):
        lines.append(f"\nNote: {result['note']}")
    if result.get("setup_instructions"):
        lines.append(f"\n{result['setup_instructions']}")
    return "\n".join(lines)
