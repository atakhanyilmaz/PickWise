"""Explicit local database commands; simulations never call this CLI."""

import argparse
from pathlib import Path

from core.plan_exchange import import_seed, publish_seed
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
    publish = commands.add_parser("publish-seed")
    publish.add_argument("--seed", type=Path, required=True)
    publish.add_argument("--plan-id", required=True)
    publish.add_argument("--version")
    publish.add_argument("--confirm-publish", action="store_true", required=True)
    import_parser = commands.add_parser("import-seed")
    import_parser.add_argument("--seed", type=Path, required=True)
    import_mode = import_parser.add_mutually_exclusive_group(required=True)
    import_mode.add_argument("--dry-run", action="store_true")
    import_mode.add_argument("--confirm-import", action="store_true")
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
    elif args.command == "load":
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
    elif args.command == "publish-seed":
        added = publish_seed(repo, args.seed, args.plan_id, args.version)
        if added:
            print("Seed'e eklenen sürümler: " + ", ".join(added))
        else:
            print("Plan sürümü seed içinde zaten güncel.")
    else:
        result = import_seed(repo, args.seed, dry_run=args.dry_run)
        action = "Eklenecek" if args.dry_run else "Eklenen"
        count = sum(len(versions) for versions in result.imported.values())
        print(f"{action} plan sürümü sayısı: {count}")
        for plan_id, versions in result.imported.items():
            print(f"  {plan_id}: {', '.join(versions)}")
        for plan_id, version_id in result.local_ahead.items():
            print(f"  Yerel plan seed'den ileride: {plan_id}/{version_id}")


if __name__ == "__main__":
    main()
