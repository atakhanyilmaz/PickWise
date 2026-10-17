"""Historical scores cannot be mixed with changed validation data."""

import pandas as pd
import pytest

from experiments.tabpfn.compare_regressors import verified_previous_predictions


def frame():
    return pd.DataFrame(
        {
            "case": ["a", "b"],
            "y": [10.0, 20.0],
            "part": ["p1", "p2"],
            "quantity": [1, 2],
        }
    )


def stored(path, data):
    out = data.copy()
    out["tabpfn_v2"] = [12.0, 18.0]
    out["extra_trees"] = [11.0, 21.0]
    out.to_csv(path, index=False)


def test_previous_predictions_require_same_rows_and_order(tmp_path):
    path = tmp_path / "predictions.csv"
    data = frame()
    stored(path, data)
    predictions = verified_previous_predictions(path, data, ["part", "quantity"])
    assert predictions["tabpfn_v2"].tolist() == [12.0, 18.0]
    with pytest.raises(AssertionError):
        verified_previous_predictions(path, data.iloc[::-1], ["part", "quantity"])


@pytest.mark.parametrize(
    "column,value",
    [("y", 999.0), ("case", "another"), ("part", "new"), ("quantity", 50)],
)
def test_changed_target_or_feature_is_rejected(tmp_path, column, value):
    path = tmp_path / "predictions.csv"
    data = frame()
    stored(path, data)
    data.loc[0, column] = value
    with pytest.raises(AssertionError):
        verified_previous_predictions(path, data, ["part", "quantity"])
