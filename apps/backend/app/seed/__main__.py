"""Seed the database:  python -m app.seed [--reset] [--no-demo] [--no-demo-factors]

--reset            drop and recreate all tables first (refused in production)
--no-demo          only the knowledge base, matching configuration and admin account
--no-demo-factors  do not load the illustrative emission factors
"""

import os

# Run event handlers inline so matching finishes before the command exits.
os.environ.setdefault("JOBS_MODE", "eager")

import argparse  # noqa: E402
import sys  # noqa: E402

from app import models  # noqa: E402, F401
from app.core.config import get_settings  # noqa: E402
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.impact import handlers as impact_handlers  # noqa: E402
from app.matching import handlers as matching_handlers  # noqa: E402
from app.notifications import handlers as notification_handlers  # noqa: E402
from app.seed.configuration import seed_demo_emission_factors, seed_matching_config  # noqa: E402
from app.seed.demo import DOMAIN, seed_admin, seed_demo  # noqa: E402
from app.seed.knowledge_base import seed_knowledge_base  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.seed")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--no-demo", action="store_true")
    parser.add_argument("--no-demo-factors", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if args.reset:
        if settings.app_env == "production":
            sys.exit("Refusing to reset a production database.")
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    elif settings.is_sqlite:
        Base.metadata.create_all(engine)  # convenience for local SQLite; PostgreSQL uses `alembic upgrade head`

    matching_handlers.register()
    notification_handlers.register()
    impact_handlers.register()
    with SessionLocal() as db:
        seed_knowledge_base(db)
        seed_matching_config(db)
        if not args.no_demo_factors:
            seed_demo_emission_factors(db)
        if args.no_demo:
            seed_admin(db)
            print("Seeded knowledge base, matching configuration and admin account.")
            return
        summary = seed_demo(db)
    print(f"Seeded {summary['organizations']} organizations and {summary['matches']} matches.")
    print(f"Demo accounts: <org>@{DOMAIN} (e.g. abc@{DOMAIN}, xyz@{DOMAIN}), admin@{DOMAIN}; "
          "password = SEED_DEMO_PASSWORD")


if __name__ == "__main__":
    main()
