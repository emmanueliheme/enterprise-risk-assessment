"""Tables for display and an Excel export of the full results."""
from __future__ import annotations

import io

import pandas as pd

from .config import ASSESSMENT_PERIOD, BANK_NAME
from .data import load_legacy_results
from .model import Results


def risk_type_table(res: Results) -> pd.DataFrame:
    t = res.risk_types
    return pd.DataFrame({
        "ID": t.risk_type_id, "Category": t.category, "Risk type": t.risk_type,
        "Weight in category": t.weight_in_category, "Enterprise weight": t.effective_weight,
        "Likelihood": t.likelihood, "Impact": t.impact, "Velocity": t.velocity, "Control": t.control,
        "Inherent": t.inherent, "Control eff.": t.control_eff, "Residual": t.residual, "Level": t.level,
        "KRIs red": t.kri_red, "KRIs amber": t.kri_amber,
    })


def category_table(res: Results) -> pd.DataFrame:
    c = res.categories
    return pd.DataFrame({
        "Category": c.category, "Weight": c.weight, "Likelihood": c.likelihood, "Impact": c.impact,
        "Velocity": c.velocity, "Control": c.control, "Inherent": c.inherent, "Control eff.": c.control_eff,
        "Residual": c.residual, "Level": c.level, "Share of ERA": c.share_of_era,
    })


def driver_table(res: Results) -> pd.DataFrame:
    d = res.drivers
    return pd.DataFrame({
        "Driver ID": d.driver_id, "Category": d.category, "Risk type": d.risk_type, "Driver": d.driver,
        "Weight": d.weight, "Likelihood": d.L, "Impact": d.I, "Velocity": d.V, "Control": d.C,
        "Inherent": d.inherent, "Residual": d.residual, "Level": d.level,
        "KRI": d.kri_name, "KRI actual": d.kri_actual, "Amber": d.amber_threshold, "Red": d.red_threshold,
        "Direction": d.kri_direction.str.replace("_", " "), "KRI status": d.kri_status, "KRI owner": d.kri_owner,
    })


def reconciliation(res: Results) -> pd.DataFrame:
    """Compare risk-type scores with the v1.0 Excel model and explain the gap."""
    old = load_legacy_results().set_index("risk_type_id")
    t = res.risk_types.set_index("risk_type_id")
    out = pd.DataFrame({
        "Risk type": t.risk_type,
        "Likelihood (Excel)": old.likelihood, "Likelihood (drivers)": t.likelihood,
        "Impact (Excel)": old.impact, "Impact (app)": t.impact,
        "Residual (Excel)": old.residual, "Residual (app)": t.residual,
        "Level (Excel)": old.level.str.title(), "Level (app)": t.level,
    })
    out["Residual change"] = out["Residual (app)"] - out["Residual (Excel)"]
    reasons = []
    for _, r in out.iterrows():
        why = []
        if abs(r["Likelihood (Excel)"] - r["Likelihood (drivers)"]) >= 0.5:
            why.append(f"Excel likelihood was typed in as {r['Likelihood (Excel)']:.0f}; drivers give {r['Likelihood (drivers)']:.2f}")
        if abs(r["Impact (Excel)"] - r["Impact (app)"]) >= 0.5:
            why.append(f"impact {r['Impact (Excel)']:.0f} → {r['Impact (app)']:.0f}")
        reasons.append("; ".join(why) if why else "Rounding and control-effectiveness fix only")
    out["Main reason"] = reasons
    return out.reset_index(names="ID")


def export_excel(res: Results) -> bytes:
    buf = io.BytesIO()
    e = res.enterprise
    summary = pd.DataFrame({
        "Measure": ["Bank", "Period", "ERA (residual, 1-25)", "Risk level", "Enterprise inherent", "Enterprise likelihood",
                    "Enterprise impact", "Enterprise control score", "Control effectiveness", "Weighted ERA (check)",
                    "Impact aggregation", "KRI overlay", "Low ≤", "Medium ≤"],
        "Value": [BANK_NAME, ASSESSMENT_PERIOD, round(e["era"], 2), e["level"], round(e["inherent"], 2), round(e["likelihood"], 2),
                  round(e["impact"], 2), round(e["control"], 2), round(e["control_eff"], 3), round(e["era_weighted"], 2),
                  res.config.impact_aggregation, "On" if res.config.kri_overlay else "Off", res.config.low_max, res.config.medium_max],
    })
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        summary.to_excel(xw, sheet_name="Enterprise", index=False)
        category_table(res).round(3).to_excel(xw, sheet_name="Categories", index=False)
        risk_type_table(res).round(3).to_excel(xw, sheet_name="Risk types", index=False)
        driver_table(res).round(3).to_excel(xw, sheet_name="Drivers and KRIs", index=False)
        reconciliation(res).round(2).to_excel(xw, sheet_name="Reconciliation v1.0", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col[:60])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
            ws.freeze_panes = "A2"
    return buf.getvalue()
