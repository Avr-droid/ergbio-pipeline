"""
test_hplc_parser.py — Unit tests for the Shimadzu XLS parser.

Tests use a synthetic XLS file built with xlwt (install if needed).
Covers: filename parsing, R² extraction, sample type filtering,
        NF handling, empty sheet handling, QC flag generation.
"""

import sys
import os
import unittest
import tempfile

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.hplc_parser import (
    _parse_filename, _parse_r2, _parse_equation,
    parse_hplc_file, get_timeseries, get_value_at,
    ANALYTE_SHEETS, QC_R2_MIN,
)


# ---------------------------------------------------------------------------
# Pure-function tests (no file I/O needed)
# ---------------------------------------------------------------------------

class TestFilenameParser(unittest.TestCase):

    def test_full_pattern(self):
        r = _parse_filename("20260709_FR009_1_24_1")
        self.assertIsNotNone(r)
        self.assertEqual(r["run_id"],      "FR009")
        self.assertEqual(r["fermenter"],   1)
        self.assertEqual(r["timepoint_h"], 24)
        self.assertEqual(r["replicate"],   1)
        self.assertEqual(r["date"],        "2026-07-09")
        self.assertFalse(r["extended_tp"])

    def test_no_replicate(self):
        r = _parse_filename("20260709_FR009_2_48")
        self.assertIsNotNone(r)
        self.assertEqual(r["fermenter"],   2)
        self.assertEqual(r["timepoint_h"], 48)
        self.assertEqual(r["replicate"],   1)   # defaults to 1

    def test_extended_timepoint(self):
        r = _parse_filename("20260709_FR009_1_96+_2")
        self.assertIsNotNone(r)
        self.assertEqual(r["timepoint_h"], 96)
        self.assertTrue(r["extended_tp"])

    def test_t0(self):
        r = _parse_filename("20260629_FR003_1_0_1")
        self.assertIsNotNone(r)
        self.assertEqual(r["run_id"],      "FR003")
        self.assertEqual(r["timepoint_h"], 0)

    def test_invalid_pattern(self):
        self.assertIsNone(_parse_filename("random_filename"))
        self.assertIsNone(_parse_filename("20260709_FR009"))
        self.assertIsNone(_parse_filename(""))


class TestCalibrationParsing(unittest.TestCase):

    def test_r2_extraction(self):
        row = ["Cellobiose", "", "Linear", "Equal", "Force",
               "Y = 3127.71*X   R^2 = 0.9996", "", "", ""]
        self.assertAlmostEqual(_parse_r2(row), 0.9996, places=4)

    def test_r2_low(self):
        row = ["Formic_Acid", "", "Linear", "Equal", "Force",
               "Y = 812.3*X   R^2 = 0.9647", "", ""]
        r2 = _parse_r2(row)
        self.assertAlmostEqual(r2, 0.9647, places=4)
        self.assertLess(r2, QC_R2_MIN)   # should be flagged

    def test_equation_extraction(self):
        row = ["Glucose", "", "Linear", "Equal", "Force",
               "Y = 2456.12*X   R^2 = 0.9998", "", ""]
        eq = _parse_equation(row)
        self.assertIsNotNone(eq)
        self.assertIn("2456.12", eq)

    def test_r2_missing(self):
        self.assertIsNone(_parse_r2(["Cellobiose", "", "no calibration info"]))


# ---------------------------------------------------------------------------
# Integration tests with synthetic XLS file
# ---------------------------------------------------------------------------

def _make_test_xls(path: str):
    """
    Build a minimal Shimadzu-format XLS with 2 analyte sheets.
    Requires xlwt — skip test gracefully if not installed.
    """
    try:
        import xlwt
    except ImportError:
        return False

    wb = xlwt.Workbook()

    def add_sheet(analyte, r2_str, rows_data, empty=False):
        ws = wb.add_sheet(analyte)
        # Row 0: title
        ws.write(0, 0, analyte)
        # Row 1: calibration
        if not empty:
            ws.write(1, 5, f"Y = 1234.56*X   R^2 = {r2_str}")
        # Row 2: blank
        # Row 3: headers
        headers = ["Filename", "Sample Type", "Sample Name", "Integ. Type",
                   "Area", "ISTD Area", "Area", "Amount", "Amount",
                   "%Diff", "%RSD-AMT", "Peak Status"]
        for i, h in enumerate(headers):
            ws.write(3, i, h)
        # Row 4+: data
        for ri, row in enumerate(rows_data):
            for ci, val in enumerate(row):
                ws.write(4 + ri, ci, val)

    # Glucose sheet — good R², 3 Unknown Samples + 1 QC + 1 Std
    glucose_rows = [
        ["20260709_FR009_1_0_1",  "Unknown Sample", "S1", "Auto", 55000, "", "", 0.0,   0.0,   "",   "", "OK"],
        ["20260709_FR009_1_24_1", "Unknown Sample", "S2", "Auto", 45000, "", "", 10.2,  10.2,  "",   "", "OK"],
        ["20260709_FR009_1_48_1", "Unknown Sample", "S3", "Auto", 12000, "", "", 2.8,   2.8,   "",   "", "OK"],
        ["20260709_FR009_1_0_2",  "Unknown Sample", "S4", "Auto", 54500, "", "", 0.1,   0.1,   "",   "", "OK"],
        ["QC_Mid",                "QC Sample",      "QC", "Auto", 30000, "", "", 12.1,  12.1,  2.5,  "", "OK"],
        ["Std_1",                 "Std Bracket Sample", "Std", "Auto", 10000, "", "", 5.0, 5.0, "", "", "OK"],
    ]
    add_sheet("Glucose", "0.9998", glucose_rows)

    # Ethanol sheet — low R² (should flag), 2 Unknown Samples
    ethanol_rows = [
        ["20260709_FR009_1_0_1",  "Unknown Sample", "S1", "Auto", 1000, "", "", "NF", "NF", "", "", "NF"],
        ["20260709_FR009_1_24_1", "Unknown Sample", "S2", "Auto", 8000, "", "", 5.1,  5.1,  "", "", "OK"],
    ]
    add_sheet("Ethanol", "0.9647", ethanol_rows)

    # Fill remaining required sheets as empty
    for analyte in ANALYTE_SHEETS:
        if analyte not in ("Glucose", "Ethanol"):
            add_sheet(analyte, "0.9990", [], empty=True)

    wb.save(path)
    return True


class TestParseHplcFile(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".XLS", delete=False)
        cls.tmp.close()
        cls.has_xlwt = _make_test_xls(cls.tmp.name)

    def setUp(self):
        if not self.has_xlwt:
            self.skipTest("xlwt not installed — skipping file-based tests")

    def test_parse_success(self):
        result = parse_hplc_file(self.tmp.name)
        self.assertTrue(result["success"])
        self.assertEqual(result["run_ids"], ["FR009"])

    def test_glucose_qc_pass(self):
        result = parse_hplc_file(self.tmp.name)
        glu = result["analyte_qc"]["Glucose"]
        self.assertAlmostEqual(glu["r_squared"], 0.9998, places=4)
        self.assertTrue(glu["qc_pass"])

    def test_ethanol_r2_flag(self):
        result = parse_hplc_file(self.tmp.name)
        eth = result["analyte_qc"]["Ethanol"]
        self.assertFalse(eth["qc_pass"])
        # Should have a warning in qc_flags
        self.assertTrue(any("Ethanol" in f and "R²" in f for f in result["qc_flags"]))

    def test_unknown_samples_only(self):
        result = parse_hplc_file(self.tmp.name)
        # samples dict should contain only Unknown Samples
        for fname, sample in result["samples"].items():
            self.assertEqual(sample["run_id"], "FR009")
            self.assertIsNotNone(sample["timepoint_h"])

    def test_nf_handling(self):
        result = parse_hplc_file(self.tmp.name)
        # t0 Ethanol is NF — should be None
        eth_t0 = result["samples"].get("20260709_FR009_1_0_1", {}).get("analytes", {}).get("Ethanol", {})
        self.assertIsNone(eth_t0.get("amount"))
        self.assertTrue(eth_t0.get("nf", False))

    def test_get_timeseries(self):
        result = parse_hplc_file(self.tmp.name)
        ts = get_timeseries(result, "FR009", 1, "Glucose")
        # t0: mean of 0.0 and 0.1 = 0.05
        self.assertIn(0, ts)
        self.assertAlmostEqual(ts[0], 0.05, places=2)
        self.assertIn(24, ts)
        self.assertAlmostEqual(ts[24], 10.2, places=1)
        self.assertIn(48, ts)

    def test_get_value_at(self):
        result = parse_hplc_file(self.tmp.name)
        val = get_value_at(result, "FR009", 1, "Glucose", 48)
        self.assertAlmostEqual(val, 2.8, places=1)

    def test_invalid_file(self):
        result = parse_hplc_file("/nonexistent/path.XLS")
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_wrong_extension(self):
        result = parse_hplc_file("/some/file.xlsx")
        self.assertFalse(result["success"])

    @classmethod
    def tearDownClass(cls):
        import os
        try:
            os.unlink(cls.tmp.name)
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
