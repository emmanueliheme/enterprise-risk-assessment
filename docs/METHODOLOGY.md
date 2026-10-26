## Methodology

The model scores risk bottom-up across four levels, so the enterprise score can always be traced back to the
individual drivers behind it:

**Risk driver → risk type → risk category → enterprise**

The sample covers 6 categories, 26 risk types and 126 drivers, each driver monitored by one key risk indicator
(KRI). Each driver is scored from 1 to 5 on four dimensions: **likelihood** (L), **impact** (I), **velocity** (V)
and **control effectiveness** (C). All scores are carried at full precision and rounded only for display.

### 1. Risk drivers

Each driver has a weight within its risk type; the weights for a risk type sum to 1.

| Measure | Formula |
|---|---|
| Stand-alone inherent score | L × I |
| Control effectiveness (CE) | Looked up from the control score (table below) |
| Stand-alone residual score | L × I × (1 − CE) |
| Weighted likelihood | weight × L |

The stand-alone scores show which drivers are most serious on their own. They don't add up to the risk-type
score, because impact combines as a worst case, not a sum.

### 2. Risk types

| Measure | Formula | Why |
|---|---|---|
| Likelihood | Σ (driver weight × L) | Weighted average of how likely the drivers are |
| Impact | max(driver I) | A risk type is as severe as its most severe driver |
| Velocity | max(driver V) | The fastest-moving driver sets the pace |
| Control score | Σ (driver weight × C) | Weighted average control quality |
| Inherent score | Likelihood × Impact | 1–25 scale, before controls |
| Control effectiveness | CE(control score), interpolated | Fractional scores interpolate between table points |
| Residual score | Inherent × (1 − CE) | 1–25 scale, after controls |
| Velocity-adjusted inherent | Inherent × Velocity ÷ 5 | Shown for urgency; not used in the residual |

### 3. Risk categories

Each risk type carries an enterprise weight set by the risk committee. Within a category these are rescaled into
shares that sum to 1: *share = risk type weight ÷ sum of weights in the category*. Category likelihood and control
are share-weighted averages of the risk types; impact and velocity are the maximum. Inherent and residual follow
the same formulas as above.

### 4. Enterprise (ERA)

Category weights set each category's share of the enterprise (sample: Strategic 10%, Operational 22%,
Financial 28%, Compliance & Legal 16%, Technology & Cyber 18%, ESG, Health & Safety 6%).

| Measure | Formula |
|---|---|
| Enterprise likelihood | Σ (category weight × category likelihood) |
| Enterprise impact | max(category impact) |
| Enterprise control score | Σ (category weight × category control score) |
| Enterprise inherent | Enterprise likelihood × enterprise impact |
| **Enterprise risk score (ERA)** | **Enterprise inherent × (1 − CE(enterprise control score))** |
| Weighted ERA (check) | Σ (category weight × category residual) |

The weighted ERA is a cross-check: if it differs a lot from the ERA, one category is pulling the result.

### Control effectiveness

| Control score | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Share of risk mitigated | 0% | 25% | 50% | 75% | 90% |

A highly effective control stops at 90% so that residual risk never reaches zero.

### Risk levels

Residual scores (1–25) are banded as **Low ≤ 8**, **Medium ≤ 15**, **High > 15**.

| Level | Action |
|---|---|
| Low | Within appetite. Monitor and review quarterly. |
| Medium | Enhanced monitoring. Report monthly to the risk committee. |
| High | Outside appetite. Escalate to ExCo and the Board with a mitigation plan. |

### KRIs

Each KRI has an amber and a red threshold and a direction:

- **Lower is worse** (completion rates, coverage %): Red if actual ≤ red threshold, Amber if ≤ amber, otherwise Green.
- **Higher is worse** (incident counts, complaint growth, time to market): Red if actual ≥ red threshold, Amber if ≥ amber, otherwise Green.

With the optional **KRI overlay**, a red KRI raises its driver's likelihood by 0.5 and lowers its control score
by 0.5; a green KRI does the reverse by 0.25 (scores stay within 1–5). This turns the assessment from a
judgement made once a year into one that moves with the indicators.

### Design choices worth knowing

- **Worst-case impact saturates.** Most risk types have at least one driver with impact 5, so impact is 5 at
  category and enterprise level and the enterprise score is driven by likelihood and controls. The sidebar
  switch to weighted averages shows the less conservative alternative.
- **Weights are set, not derived.** Weighting a category by its own score would count its risk twice, so
  weights come from the risk committee's judgement.
- **No intermediate rounding.** Rounding a likelihood of 2.6 to 3 before multiplying can move a risk type across
  a threshold.

### Changes from the v1.0 Excel model

1. Risk-type likelihoods and impacts are calculated from the drivers. In v1.0 they were typed in, and all 26
   likelihoods were higher than the drivers supported.
2. The stated category and risk-type weights are used. v1.0 weighted each item by its own inherent score.
3. Impact and velocity use the worst case at every level, as the methodology states. v1.0 averaged them.
4. Enterprise control effectiveness is calculated. v1.0 fixed it at 50%.
5. A control score of 1 gives 0% effectiveness. v1.0 gave 25%, the same as a score of 2.
6. One set of risk-level thresholds. v1.0 used four different sets across its sheets.
7. KRI status respects direction. v1.0 treated every KRI as lower-is-worse, misrating 40 of the 50
   higher-is-worse KRIs.
8. KRI status can feed the scores through the overlay. v1.0's KRI adjustment sheet was broken.
9. One range error fixed (Regulatory Compliance Risk's weight included Financial Risk rows).
