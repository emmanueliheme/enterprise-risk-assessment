"""Roll risk scores up four levels: driver -> risk type -> category -> enterprise.

No intermediate rounding: scores are carried at full precision and only rounded for display.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import MAX_SCORE, SCORE_MAX, SCORE_MIN, ModelConfig
from .data import Inputs


@dataclass
class Results:
    drivers: pd.DataFrame
    risk_types: pd.DataFrame
    categories: pd.DataFrame
    enterprise: dict
    config: ModelConfig


# ---------- building blocks ----------
def control_effectiveness(score, cfg: ModelConfig):
    """Map a 1-5 control score to % mitigated. Fractional scores (weighted averages) interpolate linearly."""
    xs = np.arange(SCORE_MIN, SCORE_MAX + 1)
    ys = np.array([cfg.control_effectiveness[int(x)] for x in xs])
    return np.interp(np.clip(score, SCORE_MIN, SCORE_MAX), xs, ys)


def risk_level(score, cfg: ModelConfig):
    score = np.asarray(score, dtype=float)
    out = np.where(score <= cfg.low_max, "Low", np.where(score <= cfg.medium_max, "Medium", "High"))
    return out.item() if out.ndim == 0 else out


def kri_status(actual, amber, red, direction) -> str:
    """Red / Amber / Green against thresholds, respecting which direction is bad."""
    if actual is None or pd.isna(actual):
        return "Not measured"
    if direction == "higher_is_worse":
        return "Red" if actual >= red else "Amber" if actual >= amber else "Green"
    return "Red" if actual <= red else "Amber" if actual <= amber else "Green"


def _combine(values: pd.Series, weights: pd.Series, how: str) -> float:
    return float(values.max()) if how == "max" else float((values * weights).sum())


# ---------- levels ----------
def score_drivers(inputs: Inputs, cfg: ModelConfig) -> pd.DataFrame:
    d = inputs.drivers.merge(inputs.risk_types[["risk_type_id", "risk_type", "category"]], on="risk_type_id", how="left")
    d["kri_status"] = [kri_status(a, am, r, dr) for a, am, r, dr in
                       zip(d.kri_actual, d.amber_threshold, d.red_threshold, d.kri_direction)]
    if cfg.kri_overlay:
        shift = d["kri_status"].map(cfg.kri_adjustment)
        d["L"] = (d["likelihood"] + shift.str[0]).clip(SCORE_MIN, SCORE_MAX)
        d["C"] = (d["control_score"] + shift.str[1]).clip(SCORE_MIN, SCORE_MAX)
    else:
        d["L"], d["C"] = d["likelihood"].astype(float), d["control_score"].astype(float)
    d["I"], d["V"] = d["impact"].astype(float), d["velocity"].astype(float)
    # Stand-alone scores describe the driver on its own; contributions add up to the risk type.
    d["inherent"] = d["L"] * d["I"]
    d["control_eff"] = control_effectiveness(d["C"], cfg)
    d["residual"] = d["inherent"] * (1 - d["control_eff"])
    d["weighted_likelihood"] = d["weight"] * d["L"]
    d["level"] = risk_level(d["residual"], cfg)
    return d


def score_risk_types(drivers: pd.DataFrame, inputs: Inputs, cfg: ModelConfig, cat_weights: pd.Series) -> pd.DataFrame:
    rows = []
    for rt_id, g in drivers.groupby("risk_type_id", sort=False):
        w = g["weight"]
        rows.append({
            "risk_type_id": rt_id,
            "likelihood": float((w * g["L"]).sum()),
            "impact": _combine(g["I"], w, cfg.impact_aggregation),
            "velocity": _combine(g["V"], w, cfg.velocity_aggregation),
            "control": float((w * g["C"]).sum()),
            "drivers": len(g),
            "kri_red": int((g["kri_status"] == "Red").sum()),
            "kri_amber": int((g["kri_status"] == "Amber").sum()),
            "kri_green": int((g["kri_status"] == "Green").sum()),
        })
    t = inputs.risk_types.merge(pd.DataFrame(rows), on="risk_type_id", how="left")
    # Within each category, enterprise weights are rescaled to shares that sum to 1.
    t["weight_in_category"] = t["enterprise_weight"] / t.groupby("category")["enterprise_weight"].transform("sum")
    t["effective_weight"] = t["weight_in_category"] * t["category"].map(cat_weights)
    _finish(t, cfg)
    return t


def score_categories(types: pd.DataFrame, cfg: ModelConfig, cat_weights: pd.Series) -> pd.DataFrame:
    rows = []
    for cat, g in types.groupby("category", sort=False):
        s = g["weight_in_category"]
        rows.append({
            "category": cat,
            "weight": float(cat_weights[cat]),
            "likelihood": float((s * g["likelihood"]).sum()),
            "impact": _combine(g["impact"], s, cfg.impact_aggregation),
            "velocity": _combine(g["velocity"], s, cfg.velocity_aggregation),
            "control": float((s * g["control"]).sum()),
            "risk_types": len(g),
            "high_risk_types": int((g["level"] == "High").sum()),
        })
    c = pd.DataFrame(rows)
    _finish(c, cfg)
    c["weighted_residual"] = c["weight"] * c["residual"]
    c["share_of_era"] = c["weighted_residual"] / c["weighted_residual"].sum()
    return c


def score_enterprise(cats: pd.DataFrame, cfg: ModelConfig) -> dict:
    W = cats["weight"]
    L = float((W * cats["likelihood"]).sum())
    I = _combine(cats["impact"], W, cfg.impact_aggregation)
    V = _combine(cats["velocity"], W, cfg.velocity_aggregation)
    C = float((W * cats["control"]).sum())
    inherent = L * I
    ce = float(control_effectiveness(C, cfg))
    residual = inherent * (1 - ce)
    return {
        "likelihood": L, "impact": I, "velocity": V, "control": C,
        "inherent": inherent, "velocity_adjusted": inherent * V / SCORE_MAX,
        "control_eff": ce, "residual": residual, "era": residual,
        "era_weighted": float(cats["weighted_residual"].sum()),
        "level": str(risk_level(residual, cfg)),
    }


def _finish(df: pd.DataFrame, cfg: ModelConfig) -> None:
    df["inherent"] = df["likelihood"] * df["impact"]
    df["velocity_adjusted"] = df["inherent"] * df["velocity"] / SCORE_MAX
    df["control_eff"] = control_effectiveness(df["control"], cfg)
    df["residual"] = df["inherent"] * (1 - df["control_eff"])
    df["level"] = risk_level(df["residual"], cfg)


def category_weights(inputs: Inputs, cfg: ModelConfig) -> pd.Series:
    w = inputs.categories.set_index("category")["weight"].astype(float)
    if cfg.category_weights:
        w = w.copy()
        for k, v in cfg.category_weights.items():
            if k in w.index:
                w[k] = v
        w = w / w.sum()
    return w


def run(inputs: Inputs, cfg: ModelConfig | None = None) -> Results:
    cfg = cfg or ModelConfig()
    cfg.validate()
    if not inputs.ok:
        raise ValueError("Inputs have errors: " + " ".join(inputs.errors))
    cw = category_weights(inputs, cfg)
    drivers = score_drivers(inputs, cfg)
    types = score_risk_types(drivers, inputs, cfg, cw)
    cats = score_categories(types, cfg, cw)
    ent = score_enterprise(cats, cfg)
    assert 0 <= ent["residual"] <= MAX_SCORE
    return Results(drivers, types, cats, ent, cfg)
