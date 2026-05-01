import pytest
from flask import g, session

from d20.db import get_db


def test_register(client, app):
    assert client.get("/auth/register").status_code == 200
    response = client.post("/auth/register", data={"username": "a", "password": "a"})
    assert response.headers["Location"] == "/auth/login"
    with app.app_context():
        with get_db().cursor() as cur:
            cur.execute('SELECT * FROM "User" WHERE username = %s', ("a",))
            assert cur.fetchone() is not None


@pytest.mark.parametrize(
    ("username", "password", "message"),
    (
        ("", "", b"Username is required."),
        ("a", "", b"Password is required."),
        ("test", "test", b"already registered"),
    ),
)
def test_register_validate_input(client, username, password, message):
    response = client.post(
        "/auth/register", data={"username": username, "password": password}
    )
    assert message in response.data


def test_login(client, auth):
    assert client.get("/auth/login").status_code == 200
    response = auth.login()
    assert response.headers["Location"] == "/"

    with client:
        client.get("/")
        assert session["user_id"] == 1
        assert g.user["username"] == "test"


@pytest.mark.parametrize(
    ("username", "password", "message"),
    (
        ("a", "test", b"Incorrect username."),
        ("test", "a", b"Incorrect password."),
    ),
)
def test_login_validate_input(auth, username, password, message):
    response = auth.login(username, password)
    assert message in response.data


def test_logout(client, auth):
    auth.login()

    with client:
        auth.logout()
        assert "user_id" not in session


def test_cancel_session_with_game_copies(client, auth, app):
    auth.login()

    with app.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO Store (username, password, name) VALUES (%s, %s, %s)",
            ("cancel_store_u", "x", "Cancel Store"),
        )
        store_id = db.execute(
            "SELECT id FROM Store WHERE username = %s", ("cancel_store_u",)
        ).fetchone()["id"]

        db.execute(
            'INSERT INTO "Table" (store_id, table_num, capacity) VALUES (%s, %s, %s)',
            (store_id, 1, 4),
        )
        db.execute(
            "INSERT INTO GameCopy (game_id, store_id, copy_num) VALUES (%s, %s, %s)",
            (1, store_id, 1),
        )
        cursor = db.execute(
            "INSERT INTO Session (user_id, store_id, table_num, day, start_time, end_time)"
            " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (1, store_id, 1, "2099-01-01", 10, 12),
        )
        session_id = cursor.fetchone()["id"]
        db.execute(
            "INSERT INTO SessionGameCopy (session_id, game_id, store_id, copy_num)"
            " VALUES (%s, %s, %s, %s)",
            (session_id, 1, store_id, 1),
        )
        db.commit()

    response = client.post(f"/auth/session/{session_id}/cancel")
    assert response.status_code == 302

    with app.app_context():
        db = get_db()
        session_row = db.execute(
            "SELECT id FROM Session WHERE id = %s", (session_id,)
        ).fetchone()
        link_row = db.execute(
            "SELECT session_id FROM SessionGameCopy WHERE session_id = %s", (session_id,)
        ).fetchone()

    assert session_row is None
    assert link_row is None
