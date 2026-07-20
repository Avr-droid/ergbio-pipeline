"""
hplc_parser.py — Shimadzu LabSolutions XLS parser for ErgBio fermentation data.

File format (12 sheets, one per analyte):
  Sheet names : Cellobiose, Citric_Acid, Glucose, Xylose, Arabinose,
                Xylitol, Succinic_Acid, Glycerol, Formic_Acid,
                Acetic_Acid, Ethanol, Component
  Row 0       : title row (sheet/analyte name)
  Row 1       : calibration metadata — contains R² and equation
                e.g. ['Cellobiose','','Linear','Equal','Force',
                       'Y = 3127.71*X   R^2 = 0.9996', ...]
  Row 2       : blank
  Row 3       : column headers
                ['Filename','Sample Type','Sample Name','Integ. Type',
                 'Area','ISTD Area','Area','Amount','Amount',
                 '%Diff','%RSD-AMT','Peak Status']
  Row 4+      : data rows (one row per injection)

Sample types  : 'Std Bracket Sample', 'QC Sample',
                'Blank Sample', 'Unknown Sample'

Filename pattern for Unknown Samples (stored in col 0 of each row):
  YYYYMMDD_RunID_FermN_Timepoint[_Replicate]
  e.g. 20260709_FR009_1_24_1  →  FR009, fermenter=1, t=24h, rep=1

Column indices (0-based):
  0  Filename        7  Amount (primary concentration, g/L)
  1  Sample Type     8  Amount (duplicate / ISTD-corrected)
  2  Sample Name     9  %Diff
  3  Integ. Type    10  %RSD-AMT
  4  Area           11  Peak Status
  5  ISTD Area
  6  Area (ratio)

QC thresholds (placeholder — update when Ares confirms):
  R²     >= 0.995
  %Diff  <= 15 %   (QC samples only)
  CV     <= 10 %   (across replicates, computed in calculator)
"""

import re
import logging
from pathlib import Path
from typing import Optional

try:
    import xlrd
    HAS_XLRD = True
except ImportError:
    HAS_XLRD = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANALYTE_SHEETS = [
    "Cellobiose", "Citric_Acid", "Glucose", "Xylose", "Arabinose",
    "Xylitol", "Succinic_Acid", "Glycerol", "Formic_Acid",
    "Acetic_Acid", "Ethanol", "Component",
]

# Column indices within each data sheet
COL_FILENAME    = 0
COL_SAMPLE_TYPE = 1
COL_SAMPLE_NAME = 2
COL_AREA        = 4
COL_AMOUNT      = 7   # primary concentration (g/L)
COL_PCT_DIFF    = 9
COL_PEAK_STATUS = 11

SAMPLE_TYPE_UNKNOWN = "Unknown Sample"
SAMPLE_TYPE_QC      = "QC Sample"
SAMPLE_TYPE_STD     = "Std Bracket Sample"
SAMPLE_TYPE_BLANK   = "Blank Sample"

# QC thresholds — PLACEHOLDER, update once Ares confirms
QC_R2_MIN      = 0.995
QC_PCTDIFF_MAX = 15.0

# Filename regex: YYYYMMDD_RUNID_FERM_TIMEPOINT[_REP]
# Run IDs like FR009, FR003, etc.
_FILENAME_RE = re.compile(
    r'^(\d{8})_(FR\d+)_(\d+)_(\d+\+?)(?:_(\d+))?$',
    re.IGNORECASE,
)

# R² extraction from calibration row
_R2_RE = re.compile(r'R\^2\s*=\s*([\d.]+)', re.IGNORECASE)
_EQ_RE = re.compile(r'(Y\s*=\s*[\d.]+\*X(?:\s*[+-]\s*[\d.]+)?)', re.IGNORECASE)

# Values that mean "not detected / not applicable"
_NULL_VALUES = {"nf", "n/a", "na", "none", "", "nd"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cell_str(sheet, row: int, col: int) -> str:
    """Return string value of a cell, empty string if out of range."""
    try:
        val = sheet.cell_value(row, col)
        return str(val).strip() if val is not None else ""
    except IndexError:
        return ""


def _cell_float(sheet, row: int, col: int) -> Optional[float]:
    """Return float value of a cell, None if missing/NF/blank."""
    try:
        val = sheet.cell_value(row, col)
    except IndexError:
        return None

    if val is None:
        return None
    s = str(val).strip()
    if s.lower() in _NULL_VALUES:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_r2(calib_row_values: list) -> Optional[float]:
    """Extract R² from the calibration row (row index 1)."""
    for cell in calib_row_values:
        s = str(cell).strip()
        m = _R2_RE.search(s)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    return None


def _parse_equation(calib_row_values: list) -> Optional[str]:
    """Extract calibration equation string from row index 1."""
    for cell in calib_row_values:
        s = str(cell).strip()
        m = _EQ_RE.search(s)
        if m:
            return m.group(1).replace(" ", "")
    return None


def _parse_filename(fname: str) -> Optional[dict]:
    """
    Parse a Shimadzu sample filename into structured metadata.

    Returns dict with keys: run_id, fermenter, timepoint_h, replicate, date
    Returns None if the filename doesn't match the expected pattern.
    """
    m = _FILENAME_RE.match(fname.strip())
    if not m:
        return None

    date_str, run_id, ferm, tp_str, rep_str = m.groups()
    # Convert timepoint — strip trailing '+' if present, treat as int hours
    tp_str_clean = tp_str.rstrip('+')
    try:
        tp_h = int(tp_str_clean)
    except ValueError:
        tp_h = None

    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    return {
        "run_id":      run_id.upper(),
        "fermenter":   int(ferm),
        "timepoint_h": tp_h,
        "replicate":   int(rep_str) if rep_str else 1,
        "date":        date_fmt,
        "extended_tp": tp_str.endswith('+'),
    }


# ---------------------------------------------------------------------------
# Sheet parser
# ---------------------------------------------------------------------------

def _parse_sheet(sheet, analyte: str) -> dict:
    """
    Parse one analyte sheet.  Returns:
        r_squared    : float or None
        equation     : str or None
        qc_pass      : bool or None (None = no calibration data)
        rows         : list of row dicts (all sample types)
        empty        : True if the sheet has no data rows
        warnings     : list of warning strings
    """
    warnings = []

    if sheet.nrows < 5:
        return {"r_squared": None, "equation": None, "qc_pass": None,
                "rows": [], "empty": True, "warnings": [f"{analyte}: sheet has fewer than 5 rows — skipped"]}

    # --- Calibration row (index 1) ---
    calib_vals = [sheet.cell_value(1, c) for c in range(sheet.ncols)]
    r2       = _parse_r2(calib_vals)
    equation = _parse_equation(calib_vals)

    if r2 is None:
        warnings.append(f"{analyte}: R² not found in calibration row")
        qc_pass = None
    else:
        qc_pass = r2 >= QC_R2_MIN
        if not qc_pass:
            warnings.append(f"{analyte}: R²={r2:.4f} below threshold {QC_R2_MIN}")

    # --- Data rows (index 4 onward) ---
    rows = []
    for row_idx in range(4, sheet.nrows):
        sample_type = _cell_str(sheet, row_idx, COL_SAMPLE_TYPE)
        filename    = _cell_str(sheet, row_idx, COL_FILENAME)

        # Skip completely empty rows
        if not sample_type and not filename:
            continue

        amount      = _cell_float(sheet, row_idx, COL_AMOUNT)
        pct_diff    = _cell_float(sheet, row_idx, COL_PCT_DIFF)
        peak_status = _cell_str(sheet, row_idx, COL_PEAK_STATUS)
        sample_name = _cell_str(sheet, row_idx, COL_SAMPLE_NAME)

        # QC sample %Diff check
        if sample_type == SAMPLE_TYPE_QC and pct_diff is not None:
            if abs(pct_diff) > QC_PCTDIFF_MAX:
                warnings.append(
                    f"{analyte}: QC '{filename}' %Diff={pct_diff:.1f}% exceeds {QC_PCTDIFF_MAX}%"
                )

        rows.append({
            "filename":    filename,
            "sample_type": sample_type,
            "sample_name": sample_name,
            "amount":      amount,
            "pct_diff":    pct_diff,
            "peak_status": peak_status,
            "nf":          peak_status.upper() == "NF" or (amount is None and peak_status == ""),
        })

    empty = len(rows) == 0
    if empty:
        warnings.append(f"{analyte}: no data rows found — sheet may be empty")

    return {
        "r_squared": r2,
        "equation":  equation,
        "qc_pass":   qc_pass,
        "rows":      rows,
        "empty":     empty,
        "warnings":  warnings,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_hplc_file(file_path: str) -> dict:
    """
    Parse a Shimadzu LabSolutions XLS file into structured fermentation data.

    Returns a dict with:
        success        bool
        source_file    str
        run_ids        list[str]  — distinct run IDs found (e.g. ['FR009'])
        analyte_qc     dict       — per-analyte calibration info
        samples        dict       — per-sample-filename data (Unknown Samples only)
        all_rows       dict       — per-analyte, all row types (for debugging)
        qc_flags       list[str]  — all QC warnings accumulated
        error          str        — only present on failure
    """
    if not HAS_XLRD:
        return {"success": False, "error": "xlrd is not installed — run: pip install xlrd"}

    path = Path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}
    if path.suffix.upper() not in (".XLS",):
        return {"success": False, "error": f"Expected .XLS file, got: {path.suffix}"}

    try:
        wb = xlrd.open_workbook(str(path))
    except Exception as e:
        return {"success": False, "error": f"Could not open workbook: {e}"}

    sheet_names = wb.sheet_names()
    analyte_qc = {}
    all_rows   = {}
    qc_flags   = []

    # Accumulate per-sample, per-analyte data keyed by filename
    # sample_data[filename][analyte] = {amount, pct_diff, peak_status, nf}
    sample_data: dict = {}

    for analyte in ANALYTE_SHEETS:
        # Find sheet — name match is case-insensitive, ignoring spaces
        sheet = None
        for sname in sheet_names:
            if sname.replace(" ", "_").lower() == analyte.lower():
                sheet = wb.sheet_by_name(sname)
                break
        if sheet is None:
            logger.warning("Sheet '%s' not found in %s", analyte, path.name)
            analyte_qc[analyte] = {"r_squared": None, "equation": None,
                                   "qc_pass": None, "empty": True}
            qc_flags.append(f"{analyte}: sheet not found in workbook")
            continue

        result = _parse_sheet(sheet, analyte)
        qc_flags.extend(result["warnings"])

        analyte_qc[analyte] = {
            "r_squared": result["r_squared"],
            "equation":  result["equation"],
            "qc_pass":   result["qc_pass"],
            "empty":     result["empty"],
        }
        all_rows[analyte] = result["rows"]

        # Index Unknown Sample rows by filename
        for row in result["rows"]:
            if row["sample_type"] != SAMPLE_TYPE_UNKNOWN:
                continue
            fname = row["filename"]
            if fname not in sample_data:
                sample_data[fname] = {}
            sample_data[fname][analyte] = {
                "amount":      row["amount"],
                "pct_diff":    row["pct_diff"],
                "peak_status": row["peak_status"],
                "nf":          row["nf"],
            }

    # Build structured samples dict with parsed filename metadata
    samples = {}
    run_ids_seen = set()

    for fname, analytes in sample_data.items():
        meta = _parse_filename(fname)
        if meta is None:
            logger.warning("Could not parse filename: '%s' — included as-is", fname)
            meta = {
                "run_id":      "UNKNOWN",
                "fermenter":   None,
                "timepoint_h": None,
                "replicate":   1,
                "date":        None,
                "extended_tp": False,
            }
        run_ids_seen.add(meta["run_id"])
        samples[fname] = {
            "filename":    fname,
            "run_id":      meta["run_id"],
            "fermenter":   meta["fermenter"],
            "timepoint_h": meta["timepoint_h"],
            "replicate":   meta["replicate"],
            "date":        meta["date"],
            "extended_tp": meta["extended_tp"],
            "analytes":    analytes,
        }

    return {
        "success":     True,
        "source_file": path.name,
        "run_ids":     sorted(run_ids_seen),
        "analyte_qc":  analyte_qc,
        "samples":     samples,
        "all_rows":    all_rows,
        "qc_flags":    qc_flags,
    }


# ---------------------------------------------------------------------------
# Convenience accessors (used by extractor.py and calculator)
# ---------------------------------------------------------------------------

def get_timeseries(parsed: dict, run_id: str, fermenter: int, analyte: str) -> dict:
    """
    Extract {timepoint_h: mean_amount} for a specific run/fermenter/analyte.

    Averages across replicates at each timepoint.
    Returns {} if nothing found.
    """
    if not parsed.get("success"):
        return {}

    from collections import defaultdict
    tp_vals: dict = defaultdict(list)

    for sample in parsed["samples"].values():
        if sample["run_id"] != run_id or sample["fermenter"] != fermenter:
            continue
        tp = sample["timepoint_h"]
        if tp is None:
            continue
        analyte_data = sample["analytes"].get(analyte, {})
        amt = analyte_data.get("amount")
        if amt is not None:
            tp_vals[tp].append(amt)

    # Mean across replicates
    return {tp: sum(vals) / len(vals) for tp, vals in sorted(tp_vals.items())}


def get_value_at(parsed: dict, run_id: str, fermenter: int,
                 analyte: str, timepoint_h: int,
                 replicate: int = None) -> Optional[float]:
    """
    Return the concentration of an analyte at a specific timepoint.

    If replicate is None, returns the mean across all replicates.
    Returns None if not found.
    """
    if not parsed.get("success"):
        return None

    vals = []
    for sample in parsed["samples"].values():
        if (sample["run_id"] != run_id
                or sample["fermenter"] != fermenter
                or sample["timepoint_h"] != timepoint_h):
            continue
        if replicate is not None and sample["replicate"] != replicate:
            continue
        amt = sample["analytes"].get(analyte, {}).get("amount")
        if amt is not None:
            vals.append(amt)

    if not vals:
        return None
    return sum(vals) / len(vals)
