import io

import numpy as np
import pandas as pd
import pytest

from era import ModelConfig, load_inputs, run
from era import reporting as rp
from era.model import control_effectiveness, kri_status, risk_level


@pytest.fixture(scope="module")
def inputs():
    i = load_inputs()
    assert i.ok, i.errors
    return i


@pytest.fixture(scope="module")
def res(inputs):
    return run(inputs.copy())


def test_sample_shape(inputs):
    assert len(inputs.categories) == 6
    assert len(inputs.risk_types) == 26
    assert len(inputs.drivers) == 126


def test_weights_sum(inputs):
    assert inputs.categories.weight.sum() == pytest.approx(1)
    assert np.allclose(inputs.drivers.groupby("risk_type_id").weight.sum(), 1)


def test_scores_in_range(res):
    for df in (res.risk_types, res.categories):
        assert df.inherent.between(1, 25).all()
        assert (df.residual <= df.inherent + 1e-12).all()
    assert 1 <= res.enterprise["era"] <= 25


def test_risk_type_hand_calc(res):
    d = res.drivers[res.drivers.risk_type_id == "R01"]
    rt = res.risk_types.set_index("risk_type_id").loc["R01"]
    L = (d.weight * d.likelihood).sum()
    C = (d.weight * d.control_score).sum()
    I = d.impact.max()
    ce = np.interp(C, [1, 2, 3, 4, 5], [0, 0.25, 0.5, 0.75, 0.9])
    assert rt.likelihood == pytest.approx(L)
    assert rt.impact == I
    assert rt.residual == pytest.approx(L * I * (1 - ce))


def test_category_shares_sum_to_one(res):
    assert np.allclose(res.risk_types.groupby("category").weight_in_category.sum(), 1)
    assert res.risk_types.effective_weight.sum() == pytest.approx(1)
    assert res.categories.share_of_era.sum() == pytest.approx(1)


def test_enterprise_hand_calc(res):
    c = res.categories
    L = (c.weight * c.likelihood).sum()
    C = (c.weight * c.control).sum()
    ce = np.interp(C, [1, 2, 3, 4, 5], [0, 0.25, 0.5, 0.75, 0.9])
    assert res.enterprise["era"] == pytest.approx(L * c.impact.max() * (1 - ce))
    assert res.enterprise["era_weighted"] == pytest.approx((c.weight * c.residual).sum())


def test_control_effectiveness_mapping():
    cfg = ModelConfig()
    assert control_effectiveness(1, cfg) == 0
    assert control_effectiveness(5, cfg) == 0.9
    assert control_effectiveness(3.5, cfg) == pytest.approx(0.625)


@pytest.mark.parametrize("actual,amber,red,direction,expected", [
    (90, 95, 90, "lower_is_worse", "Red"),
    (93, 95, 90, "lower_is_worse", "Amber"),
    (99, 95, 90, "lower_is_worse", "Green"),
    (91, 91, 121, "higher_is_worse", "Amber"),     # time to market: misrated Red in v1.0
    (5, 1, 3, "higher_is_worse", "Red"),           # incident count: misrated Green in v1.0
    (0, 1, 3, "higher_is_worse", "Green"),
    (np.nan, 1, 3, "higher_is_worse", "Not measured"),
])
def test_kri_status(actual, amber, red, direction, expected):
    assert kri_status(actual, amber, red, direction) == expected


def test_risk_levels():
    cfg = ModelConfig()
    assert list(risk_level([8, 8.01, 15, 15.01], cfg)) == ["Low", "Medium", "Medium", "High"]


def test_kri_overlay_moves_scores(inputs):
    base = run(inputs.copy(), ModelConfig())
    over = run(inputs.copy(), ModelConfig(kri_overlay=True))
    red = over.drivers.kri_status == "Red"
    assert (over.drivers.loc[red, "L"] >= base.drivers.loc[red, "L"]).all()
    assert over.enterprise["era"] != pytest.approx(base.enterprise["era"])


def test_weighted_aggregation_is_less_conservative(inputs):
    mx = run(inputs.copy(), ModelConfig())
    wt = run(inputs.copy(), ModelConfig(impact_aggregation="weighted", velocity_aggregation="weighted"))
    assert wt.enterprise["era"] <= mx.enterprise["era"]


def test_raising_a_driver_raises_its_risk_type(inputs):
    x = inputs.copy()
    idx = x.drivers.index[x.drivers.risk_type_id == "R22"][0]
    x.drivers.loc[idx, "likelihood"] = 5
    before = run(inputs.copy()).risk_types.set_index("risk_type_id").loc["R22", "residual"]
    after = run(x).risk_types.set_index("risk_type_id").loc["R22", "residual"]
    assert after >= before


def test_validation_catches_bad_weights(inputs):
    from era.data import validate
    x = inputs.copy()
    x.drivers.loc[0, "weight"] = 0.9
    assert any("sum to" in e for e in validate(x).errors)


def test_validation_catches_bad_score(inputs):
    from era.data import validate
    x = inputs.copy()
    x.drivers.loc[0, "likelihood"] = 7
    assert any("likelihood" in e for e in validate(x).errors)


def test_missing_sheet_is_reported():
    buf = io.BytesIO()
    pd.DataFrame({"a": [1]}).to_excel(buf, index=False)
    buf.seek(0)
    i = load_inputs(buf)
    assert not i.ok and any("missing" in e for e in i.errors)


def test_exports(res):
    assert len(rp.export_excel(res)) > 5000
    rec = rp.reconciliation(res)
    assert len(rec) == 26 and rec["Residual (app)"].notna().all()
