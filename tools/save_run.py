import os, io, json, time
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

SHARED_FOLDER_ID     = os.getenv("SHARED_FOLDER_ID")
SHARED_DRIVE_ID      = os.getenv("SHARED_DRIVE_ID", "0AEwqgR6xKpf_Uk9PVA")
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    from google.oauth2 import service_account
    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False

# ── NREL BIOMASS PRESETS (§5) — all 10 composition fields ────────────────────
BIOMASS_PRESETS = {
    "SB": {
        "name": "Sugarcane Bagasse Pellets", "code": "SB", "date": "2026-01-26",
        "cellulose": 34.71, "xylan": 18.68, "arabinose": 1.61,
        "lignin": 20.94, "ash": 10.46, "extractives": 13.01,
        "water": 10.90, "ethanolSol": 2.09, "aceticAcid": 3.16,
        "massClosure": 92.13,
        "note": "NREL analysis — Bagasse Pellets (741ERG-VRD-SB).",
        "warning": None,
    },
    "RS": {
        "name": "Rice Straw", "code": "RS", "date": "2026-02-26",
        "cellulose": 28.25, "xylan": 14.33, "arabinose": 1.58,
        "lignin": 15.85, "ash": 17.60, "extractives": 15.48,
        "water": 13.75, "ethanolSol": 1.72, "aceticAcid": 1.49,
        "massClosure": 77.01,
        "note": "NREL analysis — Rice Straw.",
        "warning": "Mass closure 77.01 % — below 85 % QC threshold. Verify sample before interpreting results.",
    },
    "ALB": {
        "name": "Albizia", "code": "ALB", "date": "2026-03-19",
        "cellulose": 34.87, "xylan": 12.95, "arabinose": 0.51,
        "lignin": 29.21, "ash": 4.20, "extractives": 7.064,
        "water": 4.54, "ethanolSol": 2.52, "aceticAcid": 2.72,
        "massClosure": 87.34,
        "note": "NREL analysis — Albizia.", "warning": None,
    },
    "CS": {
        "name": "Corn Stover", "code": "CS", "date": "2026-03-18",
        "cellulose": 28.72, "xylan": 19.88, "arabinose": 4.29,
        "lignin": 19.91, "ash": 5.60, "extractives": 17.21,
        "water": 14.71, "ethanolSol": 2.50, "aceticAcid": 2.50,
        "massClosure": 92.53,
        "note": "NREL analysis — Corn Stover.", "warning": None,
    },
    "MN": {
        "name": "Mac Nut Shell", "code": "MN", "date": "2026-03-18",
        "cellulose": 21.95, "xylan": 16.51, "arabinose": 0.65,
        "lignin": 38.29, "ash": 0.39, "extractives": 13.96,
        "water": 9.15, "ethanolSol": 4.81, "aceticAcid": 3.27,
        "massClosure": 94.65,
        "note": "NREL analysis — Mac Nut Shell.", "warning": None,
    },
}

# Vessel type → default working volume in mL (§6.2)
VESSEL_VOLS = {
    "falcon50":     20,
    "falcon15":     5,
    "flask125":     50,
    "flask250":     100,
    "flask500":     200,
    "bioreactor1L": 700,
    "bioreactor2L": 1500,
    "other":        None,
}

VESSEL_LABELS = {
    "falcon50":     "50 mL Falcon",
    "falcon15":     "15 mL Falcon",
    "flask125":     "125 mL Flask",
    "flask250":     "250 mL Flask",
    "flask500":     "500 mL Flask",
    "bioreactor1L": "1 L Bioreactor",
    "bioreactor2L": "2 L Bioreactor",
    "other":        "Other",
}


def _drive_service():
    if not HAS_GOOGLE:
        raise RuntimeError("Run: pip install google-api-python-client google-auth")
    if not SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON not set in .env")
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_JSON,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds)


def _eff_colour(pct):
    """§6.1 — three-tier efficiency colour. Mirrors Diana's effCls()."""
    if pct is None or not isinstance(pct, (int, float)):
        return "neutral"
    if pct >= 80:
        return "green"
    if pct >= 60:
        return "amber"
    return "red"


def _comp_from_data(data: dict) -> dict:
    """
    Return biomass composition fractions (0–1) from data dict.
    User-entered values take precedence over preset.
    Keys expected from UI: cellulose_pct, xylan_pct, arabinose_pct,
    lignin_pct, ash_pct, extractives_pct, water_pct, ethanolSol_pct,
    aceticAcid_pct, massClosure_pct.
    Falls back to preset values if UI values are absent/zero.
    """
    preset = BIOMASS_PRESETS.get(data.get("biomass_type", ""), {})

    def _v(key, preset_key):
        val = data.get(key)
        if val is not None and val != 0:
            return float(val)
        return float(preset.get(preset_key, 0))

    return {
        "cellulose":   _v("cellulose_pct",   "cellulose"),
        "xylan":       _v("xylan_pct",        "xylan"),
        "arabinose":   _v("arabinose_pct",    "arabinose"),
        "lignin":      _v("lignin_pct",       "lignin"),
        "ash":         _v("ash_pct",          "ash"),
        "extractives": _v("extractives_pct",  "extractives"),
        "water":       _v("water_pct",        "water"),
        "ethanolSol":  _v("ethanolSol_pct",   "ethanolSol"),
        "aceticAcid":  _v("aceticAcid_pct",   "aceticAcid"),
        "massClosure": _v("massClosure_pct",  "massClosure"),
    }


def _calc_theo(total_odw_kg: float, comp: dict) -> dict:
    """§4.2 — Theoretical Maximum (both experiment types)."""
    cel = comp["cellulose"] / 100
    xyl = comp["xylan"]     / 100
    ara = comp["arabinose"] / 100

    theo_glc = total_odw_kg * cel * 1.111   # §4.1 hydration factors
    theo_xyl = total_odw_kg * xyl * 1.136
    theo_ara = total_odw_kg * ara * 1.136
    theo_sug = theo_glc + theo_xyl + theo_ara
    theo_eth = theo_sug * 0.511              # §4.1 stoichiometric yield

    return {
        "glucose_kg":      round(theo_glc, 4),
        "xylose_kg":       round(theo_xyl, 4),
        "arabinose_kg":    round(theo_ara, 4),
        "total_sugars_kg": round(theo_sug, 4),
        "ethanol_kg":      round(theo_eth, 4),
    }


def _calc_eh(data: dict) -> dict:
    """
    §4.3 — EH + Fermentation calculations.
    Required data keys:
      total_odw_kg, solid_loading_pct,
      eh_glc_gL, eh_xyl_gL, eh_arab_gL, eh_vol_l (optional → defaults to slurry vol),
      ferm_eth_gL, ferm_eth_kg (optional override), ferm_vol_l (optional → defaults to slurry vol),
      ferm_res_glc_gL, ferm_res_xyl_gL, ferm_res_arab_gL
    """
    comp       = _comp_from_data(data)
    total_odw  = data.get("total_odw_kg", 0)
    theo       = _calc_theo(total_odw, comp)

    # §4.2 Slurry Volume — auto-calc from solid loading if provided
    solid_load = data.get("solid_loading_pct") or 0
    if solid_load > 0:
        slurry_vol = total_odw / (solid_load / 100)
    else:
        slurry_vol = data.get("slurry_vol_l", 0) or 0

    # EH volumes default to slurry vol (§3.5)
    eh_vol   = data.get("eh_vol_l")   or slurry_vol or 0
    ferm_vol = data.get("ferm_vol_l") or slurry_vol or 0

    # §4.3 Actual sugars released
    eh_glc_kg  = (data.get("eh_glc_gL",  0) or 0) * eh_vol / 1000
    eh_xyl_kg  = (data.get("eh_xyl_gL",  0) or 0) * eh_vol / 1000
    eh_ara_kg  = (data.get("eh_arab_gL", 0) or 0) * eh_vol / 1000
    eh_sug_kg  = eh_glc_kg + eh_xyl_kg + eh_ara_kg

    # EH yields
    eh_glc_yield = (eh_glc_kg / theo["glucose_kg"]      * 100) if theo["glucose_kg"]      > 0 else 0
    eh_xyl_yield = (eh_xyl_kg / theo["xylose_kg"]       * 100) if theo["xylose_kg"]       > 0 else 0
    eh_overall   = (eh_sug_kg / theo["total_sugars_kg"] * 100) if theo["total_sugars_kg"] > 0 else 0

    # Theoretical ethanol FROM EH sugars (fermentation denominator)
    theo_eth_from_eh = eh_sug_kg * 0.511

    # §4.3 Actual Ethanol — direct kg overrides g/L × volume
    if data.get("ferm_eth_kg"):
        actual_eth_kg = float(data["ferm_eth_kg"])
    else:
        actual_eth_kg = (data.get("ferm_eth_gL", 0) or 0) * ferm_vol / 1000

    # Fermentation efficiency
    ferm_eff = (actual_eth_kg / theo_eth_from_eh * 100) if theo_eth_from_eh > 0 else 0

    # Residual sugars (all three)
    res_glc_kg  = (data.get("ferm_res_glc_gL",  0) or 0) * ferm_vol / 1000
    res_xyl_kg  = (data.get("ferm_res_xyl_gL",  0) or 0) * ferm_vol / 1000
    res_ara_kg  = (data.get("ferm_res_arab_gL", 0) or 0) * ferm_vol / 1000
    res_sug_kg  = res_glc_kg + res_xyl_kg + res_ara_kg

    # Overall process efficiency
    overall_eff = (actual_eth_kg / theo["ethanol_kg"] * 100) if theo["ethanol_kg"] > 0 else 0

    return {
        "type": "eh",
        "theoretical": {**theo, "slurry_vol_l": round(slurry_vol, 2)},
        "enzymatic_hydrolysis": {
            "glucose_yield_pct":   round(eh_glc_yield, 2),
            "xylose_yield_pct":    round(eh_xyl_yield, 2),
            "overall_yield_pct":   round(eh_overall, 2),
            "glucose_kg":          round(eh_glc_kg, 4),
            "xylose_kg":           round(eh_xyl_kg, 4),
            "arabinose_kg":        round(eh_ara_kg, 4),
            "total_sugars_kg":     round(eh_sug_kg, 4),
            "theo_eth_from_eh_kg": round(theo_eth_from_eh, 4),
            "efficiency_colour":   _eff_colour(eh_overall),
        },
        "fermentation": {
            "efficiency_pct":      round(ferm_eff, 2),
            "actual_ethanol_kg":   round(actual_eth_kg, 4),
            "residual_glucose_kg": round(res_glc_kg, 4),
            "residual_xylose_kg":  round(res_xyl_kg, 4),
            "residual_arabinose_kg": round(res_ara_kg, 4),
            "residual_sugars_kg":  round(res_sug_kg, 4),
            "efficiency_colour":   _eff_colour(ferm_eff),
        },
        "overall": {
            "efficiency_pct":      round(overall_eff, 2),
            "theoretical_eth_kg":  round(theo["ethanol_kg"], 4),
            "actual_ethanol_kg":   round(actual_eth_kg, 4),
            "efficiency_colour":   _eff_colour(overall_eff),
        },
    }


def _calc_cbp(data: dict) -> dict:
    """
    §4.4 — CBP calculations.
    CRITICAL: All intermediate values stay in GRAMS.
    Working volume is converted mL→L only ONCE (÷1000). Do NOT divide by 1000 again.

    Required data keys:
      total_odw_kg, solid_loading_pct,
      biomass_per_vessel_g (optional — enables per-vessel theo ethanol),
      working_vol_ml, final_tp,
      conditions: list of {name, enzyme, reps, eth0, ethF, glc, xyl, ctrl}
    """
    comp      = _comp_from_data(data)
    total_odw = data.get("total_odw_kg", 0)
    theo      = _calc_theo(total_odw, comp)

    cel = comp["cellulose"] / 100
    xyl = comp["xylan"]     / 100
    ara = comp["arabinose"] / 100

    # Solid Loading → slurry vol (§4.2, recorded in params)
    solid_load = data.get("solid_loading_pct") or 0
    slurry_vol = (total_odw / (solid_load / 100)) if solid_load > 0 else data.get("slurry_vol_l", 0) or 0

    # Per-vessel theoretical ethanol (GRAMS) — §4.4
    # biomass_per_vessel_g is in grams per doc §3.6
    odm_v_g = data.get("biomass_per_vessel_g", 0) or 0
    if odm_v_g > 0:
        theo_eth_v_g = (odm_v_g * cel * 1.111 +
                        odm_v_g * xyl * 1.136 +
                        odm_v_g * ara * 1.136) * 0.511
    else:
        # Fallback: use total theoretical, converted to grams
        theo_eth_v_g = theo["ethanol_kg"] * 1000

    wv_mL = data.get("working_vol_ml", 0) or 0

    conditions_out = []
    for c in data.get("conditions", []):
        eth0  = c.get("eth0") or 0
        eth_f = c.get("ethF") or 0
        net_g_per_L = eth_f - eth0   # g/L

        # §4.4: Net EtOH per Vessel (g) = net (g/L) × working_vol (mL) ÷ 1000
        # ONE division only — result is grams
        net_g = net_g_per_L * wv_mL / 1000 if wv_mL > 0 else None

        # CBP efficiency (%)
        cbp_eff = (net_g / theo_eth_v_g * 100) if (theo_eth_v_g > 0 and net_g is not None) else None

        conditions_out.append({
            **c,
            "net_ethanol_gL":     round(net_g_per_L, 4),
            "net_ethanol_g":      round(net_g, 4) if net_g is not None else None,
            "theo_ethanol_g":     round(theo_eth_v_g, 4),
            "cbp_efficiency":     round(cbp_eff, 2) if cbp_eff is not None else None,
            "efficiency_colour":  _eff_colour(cbp_eff) if not c.get("ctrl") else "neutral",
            "below_threshold":    (cbp_eff is not None and cbp_eff < 60 and not c.get("ctrl")),
        })

    # Best efficiency among non-controls
    non_ctrl = [c for c in conditions_out if not c.get("ctrl") and c["cbp_efficiency"] is not None]
    best_eff = max(c["cbp_efficiency"] for c in non_ctrl) if non_ctrl else None

    # Ranked summary — best→worst (controls excluded) per Diana's pipeline spec
    ranked = sorted(non_ctrl, key=lambda c: c["cbp_efficiency"], reverse=True)
    ranked_summary = [
        {
            "rank": i + 1,
            "condition": c.get("name", "—"),
            "net_ethanol_gL": c["net_ethanol_gL"],
            "cbp_efficiency_pct": c["cbp_efficiency"],
            "below_threshold": c["below_threshold"],
            "colour": c["efficiency_colour"],
        }
        for i, c in enumerate(ranked)
    ]

    return {
        "type": "cbp",
        "theoretical": {**theo, "slurry_vol_l": round(slurry_vol, 2),
                        "theo_ethanol_per_vessel_g": round(theo_eth_v_g, 4)},
        "conditions":        conditions_out,
        "ranked_summary":    ranked_summary,
        "best_efficiency":   round(best_eff, 2) if best_eff is not None else None,
        "best_efficiency_colour": _eff_colour(best_eff),
    }


def save_run(extracted_data: dict) -> dict:
    """
    Main entry point. Runs calculations then saves to Drive.
    Returns structured result for the reporter agent.
    """
    exp_type = extracted_data.get("experiment_type", "cbp").lower()
    calcs    = _calc_eh(extracted_data) if exp_type == "eh" else _calc_cbp(extracted_data)

    preset = BIOMASS_PRESETS.get(extracted_data.get("biomass_type", ""), {})
    comp   = _comp_from_data(extracted_data)

    # §7 full JSON data model
    run = {
        "id":             int(time.time() * 1000),
        "type":           exp_type,
        "name":           extracted_data.get("run_name", "Unnamed Run"),
        "date":           extracted_data.get("date", datetime.today().strftime("%Y-%m-%d")),
        "vessel":         extracted_data.get("vessel", ""),
        "operator":       extracted_data.get("operator", ""),
        "notes":          extracted_data.get("notes", ""),
        "biomassType":    extracted_data.get("biomass_type", ""),
        "biomassLotsRef": extracted_data.get("biomass_lots_ref", ""),
        "compDate":       preset.get("date", ""),
        "comp":           comp,
        "lots":           extracted_data.get("lots", []),
        "totalODW":       extracted_data.get("total_odw_kg", 0),
        "params": {
            "solidLoad":       extracted_data.get("solid_loading_pct"),
            "slurryVol":       calcs.get("theoretical", {}).get("slurry_vol_l"),
            "fermTemp":        extracted_data.get("ferm_temp_c"),
            "fermDuration":    extracted_data.get("ferm_duration_hr"),
            "enzymeProduct":   extracted_data.get("enzyme_product"),
            "enzymeLoading":   extracted_data.get("enzyme_loading_mg_g"),
            "ehTemp":          extracted_data.get("eh_temp_c"),
            "ehDuration":      extracted_data.get("eh_duration_hr"),
        },
        "eh":  {
            "glucose_gL":  extracted_data.get("eh_glc_gL"),
            "xylose_gL":   extracted_data.get("eh_xyl_gL"),
            "arabinose_gL":extracted_data.get("eh_arab_gL"),
            "volume_L":    extracted_data.get("eh_vol_l"),
        } if exp_type == "eh" else None,
        "ferm": {
            "ethanol_gL":      extracted_data.get("ferm_eth_gL"),
            "ethanol_kg":      extracted_data.get("ferm_eth_kg"),
            "volume_L":        extracted_data.get("ferm_vol_l"),
            "resGlucose_gL":   extracted_data.get("ferm_res_glc_gL"),
            "resXylose_gL":    extracted_data.get("ferm_res_xyl_gL"),
            "resArabinose_gL": extracted_data.get("ferm_res_arab_gL"),
        } if exp_type == "eh" else None,
        "cbp": {
            "vesselType":        extracted_data.get("vessel_type"),
            "workingVolMl":      extracted_data.get("working_vol_ml"),
            "finalTp":           extracted_data.get("final_tp"),
            "seedStages":        extracted_data.get("seed_stages"),
            "inoculumDetails":   extracted_data.get("inoculum_details"),
            "biomassPerVesselG": extracted_data.get("biomass_per_vessel_g"),
            "conditions":        extracted_data.get("conditions", []),
        } if exp_type == "cbp" else None,
        "calcs":    calcs,
        "source":   "python_pipeline",
        "savedAt":  datetime.utcnow().isoformat() + "Z",
    }

    # Save to Drive
    try:
        service   = _drive_service()
        safe_name = "".join(c if c.isalnum() else "_" for c in run["name"])[:60]
        file_name = f"{safe_name}_{run['id']}.json"
        content   = json.dumps(run, indent=2).encode("utf-8")
        media     = MediaIoBaseUpload(io.BytesIO(content), mimetype="application/json")
        file_meta = {"name": file_name, "parents": [SHARED_FOLDER_ID], "driveId": SHARED_DRIVE_ID}
        uploaded  = service.files().create(body=file_meta, media_body=media, fields="id", supportsAllDrives=True).execute()
        drive_file_id = uploaded.get("id")
    except Exception as e:
        return {"success": False, "error": f"Drive save failed: {e}", "calcs": calcs}

    return {
        "success":         True,
        "drive_file_id":   drive_file_id,
        "run_name":        run["name"],
        "date":            run["date"],
        "experiment_type": exp_type,
        "biomass_type":    run["biomassType"],
        "biomass_warning": preset.get("warning"),
        "calcs":           calcs,
        # Full §7 run record — available for downstream verification
        **{k: v for k, v in run.items() if k not in ("calcs",)},
    }
