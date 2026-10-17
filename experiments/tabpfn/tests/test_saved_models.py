"""Save boundary integrity and all-data versus evaluation scope separation."""

import pandas as pd
import pytest

from experiments.tabpfn.learnability import datasets, target_tables
from experiments.tabpfn.saved_models import artifact, verify_files


def test_checksum_and_path_checks_happen_before_model_deserialization(tmp_path):
    path = tmp_path / "trusted.joblib"
    path.write_bytes(b"fixture bytes, not a pickle")
    record = artifact(path)
    verify_files(tmp_path, [record])
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        verify_files(tmp_path, [record])
    outside = tmp_path.parent / "outside-model-fixture"
    outside.write_bytes(b"fixture")
    with pytest.raises(ValueError, match="path"):
        verify_files(
            tmp_path,
            [
                {
                    "filename": "../outside-model-fixture",
                    "sha256": artifact(outside)["sha256"],
                }
            ],
        )


def test_full_target_table_contains_holdout_but_evaluation_train_does_not():
    rows = []
    for i in range(4):
        for op in range(2):
            start = pd.Timestamp("2024-01-01") + pd.Timedelta(days=i, minutes=op * 10)
            rows.append(
                {
                    "Case ID": f"c{i}",
                    "Activity": f"op{op}",
                    "Resource": f"Machine {op + 1} - Grinding",
                    "Start Timestamp": str(start),
                    "Complete Timestamp": str(start + pd.Timedelta(minutes=1)),
                    "Part Desc.": "part",
                    "Work Order  Qty": 10,
                }
            )
    raw = pd.DataFrame(rows)
    manifest = pd.DataFrame(
        {
            "group_id": [f"c{i}" for i in range(4)],
            "split": ["train", "validation", "test", "boundary_quarantine"],
        }
    )
    full, _, _ = target_tables(raw, manifest)
    evaluated, _ = datasets(raw, manifest)
    for task in full:
        assert set(full[task][0].case) == {"c0", "c1", "c2", "c3"}
        assert set(evaluated[task][0].case) == {"c0"}
        assert set(evaluated[task][1].case) == {"c1"}
