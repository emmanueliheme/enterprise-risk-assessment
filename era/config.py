"""Every assumption the model uses, in one place.

Change a value here (or in the app's sidebar) and every score downstream follows.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BANK_NAME = "Sample Bank Plc"   # fictional institution used for the public demo
ASSESSMENT_PERIOD = "FY 2025"

SCORE_MIN, SCORE_MAX = 1, 5
MAX_SCORE = SCORE_MAX * SCORE_MAX  # 25 on the likelihood x impact scale

LIKELIHOOD_SCALE = {
    1: ("Rare", "Not expected within 3 years; only in exceptional circumstances"),
    2: ("Unlikely", "Not expected more than once in 2 to 3 years"),
    3: ("Possible", "Likely to occur within 1 to 2 years"),
    4: ("Likely", "Will probably occur in the next 12 months"),
    5: ("Almost certain", "Expected to occur, possibly several times, within 12 months"),
}
IMPACT_SCALE = {
    1: ("Insignificant", "Loss under ₦50m; no media coverage"),
    2: ("Minor", "₦50m to ₦300m; isolated compliance issue or limited local coverage"),
    3: ("Moderate", "₦300m to ₦500m; serious isolated issue or large-scale complaints"),
    4: ("Major", "₦500m to ₦1bn; formal regulatory enquiry or sustained coverage"),
    5: ("Severe", "Over ₦1bn; regulatory sanction or threat to licence"),
}
VELOCITY_SCALE = {
    1: ("Very slow", "Months to years before impact"),
    2: ("Slow", "Weeks to months"),
    3: ("Moderate", "Days to weeks"),
    4: ("Fast", "Hours to days"),
    5: ("Immediate", "Within hours"),
}
CONTROL_SCALE = {
    1: ("Ineffective", "Controls exist on paper only; rarely tested or enforced"),
    2: ("Partially effective", "Some controls in place but significant gaps remain"),
    3: ("Moderately effective", "In place and periodically tested, with minor gaps"),
    4: ("Effective", "Consistently applied, with minor improvement areas"),
    5: ("Highly effective", "Robust, regularly tested and automated where possible"),
}

LEVELS = ("Low", "Medium", "High")
LEVEL_ACTIONS = {
    "Low": "Within appetite. Monitor and review quarterly.",
    "Medium": "Enhanced monitoring. Report monthly to the risk committee.",
    "High": "Outside appetite. Escalate to ExCo and the Board with a mitigation plan.",
}
KRI_STATUSES = ("Red", "Amber", "Green", "Not measured")


@dataclass
class ModelConfig:
    # Score at each control rating that is mitigated. 5 stops at 90% so residual risk never reaches zero.
    control_effectiveness: dict[int, float] = field(
        default_factory=lambda: {1: 0.00, 2: 0.25, 3: 0.50, 4: 0.75, 5: 0.90})
    # Residual-score bands on the 1-25 scale: Low <= low_max < Medium <= medium_max < High
    low_max: float = 8.0
    medium_max: float = 15.0
    # How impact and velocity combine upward: "max" (worst case, per the methodology) or "weighted"
    impact_aggregation: str = "max"
    velocity_aggregation: str = "max"
    # Optional KRI overlay: shift each driver's likelihood and control score by its KRI status
    kri_overlay: bool = False
    kri_adjustment: dict[str, tuple[float, float]] = field(default_factory=lambda: {
        "Red": (+0.50, -0.50),      # (likelihood shift, control shift)
        "Amber": (0.00, 0.00),
        "Green": (-0.25, +0.25),
        "Not measured": (0.00, 0.00),
    })
    # Optional override of category weights, e.g. {"Financial Risk": 0.30, ...}; None uses the input workbook
    category_weights: dict[str, float] | None = None

    def validate(self) -> None:
        ce = [self.control_effectiveness[k] for k in range(SCORE_MIN, SCORE_MAX + 1)]
        if any(not 0 <= v <= 1 for v in ce):
            raise ValueError("Control effectiveness must be between 0% and 100%.")
        if any(b < a for a, b in zip(ce, ce[1:])):
            raise ValueError("Control effectiveness must not fall as the control score rises.")
        if not 0 < self.low_max < self.medium_max < MAX_SCORE:
            raise ValueError("Thresholds must satisfy 0 < Low max < Medium max < 25.")
        for name in ("impact_aggregation", "velocity_aggregation"):
            if getattr(self, name) not in ("max", "weighted"):
                raise ValueError(f"{name} must be 'max' or 'weighted'.")
