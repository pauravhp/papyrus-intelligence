"""Run the migration parser against a fixture file.

Usage:
    python3 scripts/dev/run_migration_parser.py tests/fixtures/migration/notion_checkbox_export.txt
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.services.migration_parser import parse_migration_dump  # noqa: E402
from api.config import settings  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: run_migration_parser.py <fixture-file>")
        return 2
    path = Path(sys.argv[1])
    raw = path.read_text()
    result = parse_migration_dump(
        raw_text=raw,
        today=date.today(),
        anthropic_api_key=settings.ANTHROPIC_API_KEY,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
