import os

import psycopg2
import pytest

from d20 import create_app
from d20.db import get_db, init_db

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://d20:d20@localhost:5433/d20_test"
)

with open(os.path.join(os.path.dirname(__file__), "data.sql"), "rb") as f:
    _data_sql = f.read().decode("utf8")


def pytest_addoption(parser):
    parser.addoption(
        "--pg",
        action="store_true",
        default=False,
        help="Run tests against PostgreSQL (requires DB at TEST_DATABASE_URL)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "pg: mark test as requiring a live PostgreSQL connection"
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--pg"):
        return
    skip_pg = pytest.mark.skip(reason="pass --pg to run against PostgreSQL")
    for item in items:
        # all tests use the `app` fixture which needs PG — skip unless --pg passed
        if "app" in item.fixturenames or "client" in item.fixturenames or "runner" in item.fixturenames or "auth" in item.fixturenames:
            item.add_marker(skip_pg)


@pytest.fixture
def app():
    try:
        conn = psycopg2.connect(TEST_DATABASE_URL)
        conn.close()
    except psycopg2.OperationalError as e:
        pytest.skip(f"PostgreSQL not reachable: {e}")

    app = create_app(
        {
            "TESTING": True,
            "DATABASE_URL": TEST_DATABASE_URL,
        }
    )

    with app.app_context():
        init_db()
        db = get_db()
        with db.cursor() as cur:
            cur.execute(_data_sql)
        db.commit()

    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


class AuthActions(object):
    def __init__(self, client):
        self._client = client

    def login(self, username="test", password="test"):
        return self._client.post(
            "/auth/login", data={"username": username, "password": password}
        )

    def logout(self):
        return self._client.get("/auth/logout")


@pytest.fixture
def auth(client):
    return AuthActions(client)
