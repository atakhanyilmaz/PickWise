"""Experimental predictors must remain outside the default application import graph."""

import ast
from pathlib import Path


def test_application_does_not_import_experimental_predictors():
    forbidden = {
        "experiments",
        "ml_experiments",
        "torch",
        "tabpfn",
        "catboost",
        "sklearn",
        "joblib",
    }
    violations = []
    for directory in ("core", "benchmarks", "ui"):
        for path in Path(directory).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
                for name in names:
                    if name.split(".")[0] in forbidden:
                        violations.append(f"{path}:{node.lineno}: {name}")
    assert violations == []
