"""Load and validate the input workbook."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

import pandas as pd

DEFAULT_INPUTS = Path(__file__).resolve().parent.parent / "data" / "era_inputs.xlsx"
LEGACY_RESULTS = Path(__file__).resolve().parent.parent / "data" / "excel_v1_results.csv"

CATEGORY_COLS = ["category", "weight"]
RISK_TYPE_COLS = ["risk_type_id", "category", "risk_type", "enterprise_weight", "definition"]
DRIVER_COLS = ["driver_id", "risk_type_id", "driver", "control", "weight", "likelihood", "impact", "velocity",
               "control_score", "kri_name", "kri_actual", "amber_threshold", "red_threshold", "kri_direction"]
OPTIONAL_DRIVER_COLS = ["kri_calculation", "kri_reporting", "kri_owner"]
SCORE_COLS = ["likelihood", "impact", "velocity", "control_score"]
TOLERANCE = 1e-6


@dataclass
class Inputs:
    categories: pd.DataFrame
    risk_types: pd.DataFrame
    drivers: pd.DataFrame
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def copy(self) -> "Inputs":
        return Inputs(self.categories.copy(), self.risk_types.copy(), self.drivers.copy(),
                      list(self.errors), list(self.warnings))


def load_inputs(source: str | Path | BinaryIO = DEFAULT_INPUTS) -> Inputs:
    """Read the Categories, RiskTypes and Drivers sheets and check them."""
    try:
        book = pd.read_excel(source, sheet_name=None)
    except Exception as exc:  # unreadable file
        return Inputs(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), errors=[f"Could not read the workbook: {exc}"])

    errors: list[str] = []
    sheets = {}
    for name, cols in (("Categories", CATEGORY_COLS), ("RiskTypes", RISK_TYPE_COLS), ("Drivers", DRIVER_COLS)):
        if name not in book:
            errors.append(f"Sheet '{name}' is missing. Download the template from the sidebar to see the expected layout.")
            continue
        df = book[name].dropna(how="all")
        df.columns = [str(c).strip() for c in df.columns]
        missing = [c for c in cols if c not in df.columns]
        if missing:
            errors.append(f"Sheet '{name}' is missing column(s): {', '.join(missing)}.")
        sheets[name] = df
    if errors:
        return Inputs(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), errors=errors)

    drivers = sheets["Drivers"]
    for c in OPTIONAL_DRIVER_COLS:
        if c not in drivers.columns:
            drivers[c] = ""
    inputs = Inputs(sheets["Categories"][CATEGORY_COLS].reset_index(drop=True),
                    sheets["RiskTypes"][RISK_TYPE_COLS].reset_index(drop=True),
                    drivers[DRIVER_COLS + OPTIONAL_DRIVER_COLS].reset_index(drop=True))
    return validate(inputs)


def validate(inputs: Inputs) -> Inputs:
    """Check structure, scores and weights. Errors stop the model; warnings are shown but tolerated."""
    errors, warns = [], []
    cats, types, drv = inputs.categories, inputs.risk_types, inputs.drivers

    for col in ("weight",):
        cats[col] = pd.to_numeric(cats[col], errors="coerce")
    types["enterprise_weight"] = pd.to_numeric(types["enterprise_weight"], errors="coerce")
    for col in ["weight", *SCORE_COLS, "kri_actual", "amber_threshold", "red_threshold"]:
        drv[col] = pd.to_numeric(drv[col], errors="coerce")
    drv["kri_direction"] = drv["kri_direction"].astype(str).str.strip().str.lower()

    if cats["category"].duplicated().any():
        errors.append("Categories: each category name must appear once.")
    if cats["weight"].isna().any() or (cats["weight"] < 0).any():
        errors.append("Categories: every weight must be a number of 0 or more.")
    elif abs(cats["weight"].sum() - 1) > 1e-3:
        errors.append(f"Categories: weights sum to {cats['weight'].sum():.1%}; they must sum to 100%.")

    if types["risk_type_id"].duplicated().any():
        errors.append("RiskTypes: each risk_type_id must be unique.")
    unknown = sorted(set(types["category"]) - set(cats["category"]))
    if unknown:
        errors.append(f"RiskTypes: unknown category name(s) {unknown}; they must match the Categories sheet.")
    if types["enterprise_weight"].isna().any() or (types["enterprise_weight"] <= 0).any():
        errors.append("RiskTypes: every enterprise_weight must be a number above 0.")
    empty = sorted(set(cats["category"]) - set(types["category"]))
    if empty:
        errors.append(f"Categories with no risk types: {empty}.")

    if drv["driver_id"].duplicated().any():
        errors.append("Drivers: each driver_id must be unique.")
    orphan = sorted(set(drv["risk_type_id"]) - set(types["risk_type_id"]))
    if orphan:
        errors.append(f"Drivers: unknown risk_type_id(s) {orphan}.")
    no_drivers = sorted(set(types["risk_type_id"]) - set(drv["risk_type_id"]))
    if no_drivers:
        errors.append(f"Risk types with no drivers: {no_drivers}.")
    for col in SCORE_COLS:
        bad = drv[drv[col].isna() | (drv[col] % 1 != 0) | (drv[col] < 1) | (drv[col] > 5)]
        if len(bad):
            errors.append(f"Drivers: {col} must be a whole number from 1 to 5 (check {', '.join(bad['driver_id'].astype(str)[:5])}).")
    if drv["weight"].isna().any() or (drv["weight"] < 0).any():
        errors.append("Drivers: every weight must be a number of 0 or more.")
    else:
        sums = drv.groupby("risk_type_id")["weight"].sum()
        off = sums[(sums - 1).abs() > 1e-3]
        for rt, s in off.items():
            errors.append(f"Drivers: weights for {rt} sum to {s:.2f}; they must sum to 1.0.")
    bad_dir = drv[~drv["kri_direction"].isin(["lower_is_worse", "higher_is_worse"])]
    if len(bad_dir):
        errors.append(f"Drivers: kri_direction must be lower_is_worse or higher_is_worse (check {', '.join(bad_dir['driver_id'].astype(str)[:5])}).")
    lw = drv[(drv["kri_direction"] == "lower_is_worse") & (drv["amber_threshold"] < drv["red_threshold"])]
    hw = drv[(drv["kri_direction"] == "higher_is_worse") & (drv["amber_threshold"] > drv["red_threshold"])]
    for df, why in ((lw, "lower_is_worse needs amber ≥ red"), (hw, "higher_is_worse needs amber ≤ red")):
        if len(df):
            warns.append(f"KRI thresholds look reversed for {', '.join(df['driver_id'][:5])} ({why}).")
    if drv["kri_actual"].isna().any():
        warns.append(f"{int(drv['kri_actual'].isna().sum())} KRI(s) have no actual value and are shown as Not measured.")

    inputs.errors, inputs.warnings = errors, warns
    return inputs


def load_legacy_results() -> pd.DataFrame:
    """Risk-type figures from the v1.0 Excel model, kept for the reconciliation view."""
    return pd.read_csv(LEGACY_RESULTS)
