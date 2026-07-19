"""
literature_search.py — Free scientific literature search for the Penny Agent.

Sources:
  Semantic Scholar  — 200M+ papers, no API key required
  PubMed (Entrez)   — NIH database, free, no API key required

Auto-falls back to PubMed if Semantic Scholar rate-limits (429).
"""

import requests
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

S2_SEARCH_URL  = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS      = "title,abstract,authors,year,externalIds,openAccessPdf,citationCount"
PUBMED_SEARCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_SUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
TIMEOUT = 15


def _semantic_scholar(query: str, limit: int = 5) -> tuple[list[dict], bool]:
    """Returns (results, rate_limited)."""
    try:
        resp = requests.get(
            S2_SEARCH_URL,
            params={"query": query, "limit": limit, "fields": S2_FIELDS},
            timeout=TIMEOUT,
            headers={"User-Agent": "ErgBio-Research-Agent/1.0"}
        )
        if resp.status_code == 429:
            logger.info("Semantic Scholar rate-limited — falling back to PubMed")
            return [], True
        resp.raise_for_status()
        results = []
        for paper in resp.json().get("data", []):
            doi = (paper.get("externalIds") or {}).get("DOI")
            pdf = (paper.get("openAccessPdf") or {}).get("url")
            results.append({
                "source":    "Semantic Scholar",
                "title":     paper.get("title", ""),
                "abstract":  (paper.get("abstract") or "")[:800],
                "authors":   ", ".join(a["name"] for a in (paper.get("authors") or [])[:3]),
                "year":      paper.get("year"),
                "doi":       doi,
                "url":       pdf or (f"https://doi.org/{doi}" if doi else None),
                "citations": paper.get("citationCount"),
            })
        return results, False
    except requests.exceptions.Timeout:
        return [], False
    except Exception as e:
        logger.warning("Semantic Scholar error: %s", e)
        return [], False


def _pubmed(query: str, limit: int = 5) -> list[dict]:
    try:
        search = requests.get(
            PUBMED_SEARCH,
            params={"db": "pubmed", "term": query, "retmax": limit,
                    "retmode": "json", "sort": "relevance"},
            timeout=TIMEOUT
        )
        search.raise_for_status()
        ids = search.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []

        time.sleep(0.35)

        summary = requests.get(
            PUBMED_SUMMARY,
            params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
            timeout=TIMEOUT
        )
        summary.raise_for_status()
        uid_data = summary.json().get("result", {})

        results = []
        for uid in ids:
            p = uid_data.get(uid, {})
            if not p:
                continue
            authors = ", ".join(a.get("name", "") for a in p.get("authors", [])[:3])
            doi = next((x["value"] for x in p.get("articleids", [])
                        if x.get("idtype") == "doi"), None)
            results.append({
                "source":    "PubMed",
                "title":     p.get("title", ""),
                "abstract":  p.get("sorttitle", ""),
                "authors":   authors,
                "year":      p.get("pubdate", "")[:4],
                "doi":       doi,
                "url":       f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                "citations": None,
            })
        return results
    except Exception as e:
        logger.warning("PubMed error: %s", e)
        return []


def search_papers(query: str, limit: int = 5, source: str = "semantic_scholar") -> dict:
    """
    Search scientific literature.

    Args:
        query  : Natural-language search string.
        limit  : Number of results (2–8 recommended).
        source : "semantic_scholar" (default), "pubmed", or "both".

    Returns dict: success, query, results, count, [error]
    """
    results = []

    if source == "pubmed":
        results = _pubmed(query, limit)

    elif source == "both":
        s2, rate_limited = _semantic_scholar(query, max(3, limit // 2))
        pm = _pubmed(query, limit - len(s2))
        results = s2 + pm

    else:  # semantic_scholar (default) with PubMed fallback
        s2, rate_limited = _semantic_scholar(query, limit)
        if rate_limited or not s2:
            results = _pubmed(query, limit)
        else:
            results = s2

    if not results:
        return {
            "success": False, "query": query, "results": [], "count": 0,
            "error": "No results found — try broader or different search terms",
        }

    return {"success": True, "query": query, "results": results, "count": len(results)}


def format_for_context(search_result: dict) -> str:
    """Format search results as readable string for LLM context."""
    if not search_result.get("success"):
        return f"Literature search returned no results for: '{search_result.get('query')}'"

    lines = [f"Literature search: '{search_result['query']}' ({search_result['count']} results)\n"]
    for i, p in enumerate(search_result["results"], 1):
        lines.append(f"[{i}] {p['title']} ({p.get('year', 'n.d.')})")
        if p.get("authors"):
            lines.append(f"    Authors: {p['authors']}")
        if p.get("abstract"):
            lines.append(f"    Abstract: {p['abstract'][:400]}...")
        if p.get("doi"):
            lines.append(f"    DOI: {p['doi']}")
        if p.get("url"):
            lines.append(f"    URL: {p['url']}")
        if p.get("citations") is not None:
            lines.append(f"    Citations: {p['citations']}")
        lines.append("")
    return "\n".join(lines)
