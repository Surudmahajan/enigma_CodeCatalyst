import os

# Configure the test environment before the app is imported.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./var/test.db"
os.environ["JOBS_MODE"] = "eager"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["STORAGE_LOCAL_DIR"] = "./var/test-storage"
os.environ["AI_PROVIDER"] = "none"
os.environ["PUSH_PROVIDER"] = "none"
os.environ["JWT_SECRET"] = "test-access-secret-at-least-32-bytes-long-xx"
os.environ["JWT_REFRESH_SECRET"] = "test-refresh-secret-at-least-32-bytes-long-x"

import itertools  # noqa: E402
from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402, F401
from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

os.makedirs("./var", exist_ok=True)

PASSWORD = "Test-password-123"
_counter = itertools.count(1)


@pytest.fixture(scope="session")
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def fresh_database(_schema):
    """Empty every table (children first) — much faster than recreating the schema."""
    from app.core.rate_limit import limiter

    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    limiter.reset()
    yield


@pytest.fixture
def db(fresh_database):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(fresh_database):
    return TestClient(app)


class Api:
    """Thin authenticated client used by integration tests."""

    def __init__(self, client: TestClient, token: str, org_id: str | None = None):
        self.client = client
        self.token = token
        self.org_id = org_id

    def _headers(self):
        headers = {"Authorization": f"Bearer {self.token}"}
        if self.org_id:
            headers["X-Organization-Id"] = self.org_id
        return headers

    def get(self, path, **kw):
        return self.client.get(f"/api/v1{path}", headers=self._headers(), **kw)

    def post(self, path, json=None, **kw):
        return self.client.post(f"/api/v1{path}", json=json, headers=self._headers(), **kw)

    def patch(self, path, json=None, **kw):
        return self.client.patch(f"/api/v1{path}", json=json, headers=self._headers(), **kw)

    def delete(self, path, **kw):
        return self.client.delete(f"/api/v1{path}", headers=self._headers(), **kw)


def register_user(client: TestClient, email: str | None = None) -> dict:
    email = email or f"user{next(_counter)}@example.com"
    response = client.post("/api/v1/auth/register", json={
        "email": email, "password": PASSWORD, "first_name": "Test", "last_name": "User",
    })
    assert response.status_code == 201, response.text
    return response.json()


def make_org(client: TestClient, name: str = "ABC Steel", sector: str = "Steel manufacturing",
             lat: float = 18.52, lon: float = 73.85, city: str = "Pune", mode: str = "BOTH") -> Api:
    auth = register_user(client)
    api = Api(client, auth["access_token"])
    response = api.post("/organizations", json={
        "legal_name": f"{name} Pvt Ltd", "display_name": name, "industry_sector": sector, "operating_mode": mode,
        "headquarters": {"city": city, "state": "Maharashtra", "country": "India",
                         "address": "Plot 1, Industrial Area", "latitude": lat, "longitude": lon},
    })
    assert response.status_code == 201, response.text
    api.org_id = response.json()["id"]
    api.facility_id = response.json()["facilities"][0]["id"]
    return api


def future(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


@pytest.fixture
def kb(db):
    """Seed the curated material knowledge base; returns lookup helpers."""
    from sqlalchemy import select

    from app.materials.models import ApplicationType, Material
    from app.seed.configuration import seed_demo_emission_factors, seed_matching_config
    from app.seed.knowledge_base import seed_knowledge_base

    seed_knowledge_base(db)
    seed_matching_config(db)
    seed_demo_emission_factors(db)

    class KB:
        def material(self, name: str) -> str:
            return str(db.scalars(select(Material).where(Material.canonical_name == name)).one().id)

        def application(self, key: str) -> str:
            return str(db.scalars(select(ApplicationType).where(ApplicationType.key == key)).one().id)

    return KB()
