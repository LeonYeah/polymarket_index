from __future__ import annotations

import argparse

from backend.app.db.database import make_engine
from backend.app.db.migrations import SCHEMA_VERSION, apply_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply database schema migrations.")
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL.")
    args = parser.parse_args()

    engine = make_engine(args.database_url)
    apply_schema(engine)
    print(f"Applied schema migration: {SCHEMA_VERSION}")


if __name__ == "__main__":
    main()
