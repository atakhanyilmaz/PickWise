"""Explicit local database commands; simulations never call this CLI."""

import argparse
from pathlib import Path

from core.plan_contract import StoredPlanVersion
from core.sqlite_repository import SQLitePlanRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    save = commands.add_parser("save")
    save.add_argument("--record", type=Path, required=True)
    previous = save.add_mutually_exclusive_group(required=True)
    previous.add_argument("--first-version", action="store_true")
    previous.add_argument("--expected-current")
    save.add_argument("--confirm-save", action="store_true", required=True)
    load = commands.add_parser("load")
    load.add_argument("--plan-id", required=True)
    load.add_argument("--version")
    load.add_argument("--output", type=Path, required=True)
    load.add_argument("--snapshot-only", action="store_true")
    args = parser.parse_args()
    repo = SQLitePlanRepository(args.db)
    if args.command == "init":
        repo.initialize()
        print("Plan veritabanı hazır.")
    elif args.command == "save":
        record = StoredPlanVersion.model_validate_json(
            args.record.read_text(encoding="utf-8")
        )
        repo.save_approved_version(
            record, expected_current_version_id=args.expected_current
        )
        print("Seçilen plan yeni sürüm olarak kaydedildi.")
    else:
        record = (
            repo.load_version(args.plan_id, args.version)
            if args.version is not None
            else repo.load_current(args.plan_id)
        )
        # Refuse to silently overwrite a user's existing export.
        value = record.snapshot if args.snapshot_only else record
        with args.output.open("x", encoding="utf-8") as output:
            output.write(value.model_dump_json(indent=2))
        print("Doğrulanan plan dışa aktarıldı.")


if __name__ == "__main__":
    main()
