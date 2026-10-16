from copy import deepcopy

import pytest

from core.cpsat_solver import baseline, read_instance, solve
from core.validation import validate


@pytest.fixture
def tiny(tmp_path):
    path = tmp_path / "tiny.fjs"
    path.write_text("2 2 1\n2 2 1 5 2 2 1 1 3\n1 1 1 2\n")
    return read_instance(path)


def test_hand_checkable_optimum(tiny):
    env, jobs, machines = tiny
    result = solve(env, 2)
    assert result["status"] == "OPTIMAL"
    assert result["makespan"] == 5
    assert validate(jobs, machines, result["schedule"]) == []
    first = next(r for r in result["schedule"] if (r["job"], r["operation"]) == (0, 0))
    assert first["machine"] == 1
    assert first["end"] - first["start"] == 2


def test_baseline_deterministic_and_preserves_input(tiny):
    _, jobs, machines = tiny
    original = deepcopy(jobs)
    assert baseline(jobs, machines)["schedule"] == baseline(jobs, machines)["schedule"]
    assert jobs == original
    assert validate(jobs, machines, baseline(jobs, machines)["schedule"]) == []


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "duplicate",
        "machine",
        "duration",
        "precedence",
        "overlap",
        "negative",
    ],
)
def test_validator_rejects_corruption(tiny, corruption):
    _, jobs, machines = tiny
    rows = [
        dict(job=0, operation=0, machine=1, start=0, end=2),
        dict(job=0, operation=1, machine=0, start=2, end=5),
        dict(job=1, operation=0, machine=0, start=0, end=2),
    ]
    assert validate(jobs, machines, rows) == []  # touching endpoints are legal
    if corruption == "missing":
        rows.pop()
    elif corruption == "duplicate":
        rows.append(rows[0].copy())
    elif corruption == "machine":
        rows[1]["machine"] = 1
    elif corruption == "duration":
        rows[0]["end"] = 1
    elif corruption == "precedence":
        rows[0].update(start=4, end=6)
    elif corruption == "overlap":
        rows[2].update(start=3, end=5)
    else:
        rows[0].update(start=-1, end=1)
    assert validate(jobs, machines, rows)


@pytest.mark.parametrize(
    "text",
    [
        "1 2 1\n1 1 3 2\n",
        "1 2 1\n1 1 1 0\n",
        "1 2 1\n1 2 1 2 1 3\n",
        "1 2 1\n2 1 1 2\n",
    ],
)
def test_bad_input(tmp_path, text):
    path = tmp_path / "bad.fjs"
    path.write_text(text)
    with pytest.raises(ValueError):
        read_instance(path)


def test_unknown_is_not_infeasible(tiny):
    env, _, _ = tiny
    result = solve(env, 1e-9)
    assert result["status"] == "UNKNOWN"
    assert result["schedule"] == []
    assert result["makespan"] is None


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf")])
def test_invalid_limits(tiny, limit):
    with pytest.raises(ValueError):
        solve(tiny[0], limit)
