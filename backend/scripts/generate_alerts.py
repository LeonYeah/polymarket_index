from __future__ import annotations

import argparse
import json

from backend.app.db.dashboard_repository import DashboardRepository
from backend.app.db.database import make_engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and upsert Week07 dashboard alerts.")
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL.")
    args = parser.parse_args()

    engine = make_engine(args.database_url)
    with engine.begin() as connection:
        counters = DashboardRepository(connection).generate_alerts()
    print(json.dumps({"generated": counters, "generated_total": sum(counters.values())}, sort_keys=True))


if __name__ == "__main__":
    main()
