"""Write the FastAPI OpenAPI schema to packages/shared-types/openapi.json (run from apps/backend)."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///./var/openapi.db")

from app.main import app  # noqa: E402

target = Path(__file__).resolve().parents[3] / "packages" / "shared-types" / "openapi.json"
target.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
print(f"Wrote {target}")
