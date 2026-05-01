"""Tests for the maximum concurrent reservations feature."""
import pytest

from d20.db import get_db
from d20.db.session import MAX_RESERVATIONS, get_reservation_count


def _insert_store_and_table(db):
    """Insert a test store and table, return (store_id, table_num)."""
    db.execute(
        "INSERT INTO Store (username, password, name) VALUES (?, ?, ?)",
        ("storeuser", "storehash", "Test Store"),
    )
    store_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.execute(
        "INSERT INTO 'Table' (store_id, table_num, capacity) VALUES (?, ?, ?)",
        (store_id, 1, 4),
    )
    db.commit()
    return store_id, 1


def _insert_session(db, user_id, store_id, table_num, day, start_time, end_time):
    """Insert a session row directly into the DB."""
    db.execute(
        "INSERT INTO Session (user_id, store_id, table_num, day, start_time, end_time)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, store_id, table_num, day, start_time, end_time),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Unit-level tests for get_reservation_count
# ---------------------------------------------------------------------------


def test_get_reservation_count_zero(app):
    """A fresh user with no sessions has a count of 0."""
    with app.app_context():
        db = get_db()
        user_id = db.execute("SELECT id FROM User WHERE username = 'test'").fetchone()[
            "id"
        ]
        assert get_reservation_count(user_id) == 0


def test_get_reservation_count_increments(app):
    """Count increases as sessions are added."""
    with app.app_context():
        db = get_db()
        user_id = db.execute("SELECT id FROM User WHERE username = 'test'").fetchone()[
            "id"
        ]
        store_id, table_num = _insert_store_and_table(db)
        _insert_session(db, user_id, store_id, table_num, "2099-01-01", 9, 11)
        assert get_reservation_count(user_id) == 1
        _insert_session(db, user_id, store_id, table_num, "2099-01-02", 9, 11)
        assert get_reservation_count(user_id) == 2


# ---------------------------------------------------------------------------
# Route-level tests for confirm_booking
# ---------------------------------------------------------------------------


def _login(client, username="test", password="test"):
    client.post("/auth/login", data={"username": username, "password": password})


def _post_booking(client, store_id, table_num, day="2026-05-10", start_time=9, end_time=11, game_ids=None):
    data = {
        "day": day,
        "start_time": str(start_time),
        "end_time": str(end_time),
    }
    if game_ids:
        data["selected_games"] = [str(gid) for gid in game_ids]
    return client.post(
        f"/store/{store_id}/table/{table_num}/confirm-booking",
        data=data,
    )


def test_booking_succeeds_under_limit(app, client):
    """Booking succeeds when the user has fewer than MAX_RESERVATIONS sessions."""
    with app.app_context():
        db = get_db()
        user_id = db.execute("SELECT id FROM User WHERE username = 'test'").fetchone()[
            "id"
        ]
        store_id, table_num = _insert_store_and_table(db)
        # Add a game copy so the booking has something to select
        db.execute(
            "INSERT INTO GameCopy (game_id, store_id, copy_num) VALUES (?, ?, ?)",
            (1, store_id, 1),
        )
        db.commit()

    _login(client)
    response = _post_booking(client, store_id, table_num, game_ids=[1])

    # Should redirect to index (successful booking)
    assert response.status_code == 302
    assert response.headers["Location"] == "/"

    with app.app_context():
        db = get_db()
        user_id = db.execute("SELECT id FROM User WHERE username = 'test'").fetchone()[
            "id"
        ]
        assert get_reservation_count(user_id) == 1


def test_booking_blocked_at_limit(app, client):
    """Booking is blocked when the user already has MAX_RESERVATIONS sessions."""
    with app.app_context():
        db = get_db()
        user_id = db.execute("SELECT id FROM User WHERE username = 'test'").fetchone()[
            "id"
        ]
        store_id, table_num = _insert_store_and_table(db)
        # Pre-fill MAX_RESERVATIONS sessions
        for i in range(MAX_RESERVATIONS):
            _insert_session(
                db,
                user_id,
                store_id,
                table_num,
                f"2099-0{i + 1}-01",
                9,
                11,
            )
        db.execute(
            "INSERT INTO GameCopy (game_id, store_id, copy_num) VALUES (?, ?, ?)",
            (1, store_id, 1),
        )
        db.commit()

    _login(client)
    response = _post_booking(client, store_id, table_num, game_ids=[1])

    # Should redirect back to select_games (not to index)
    assert response.status_code == 302
    assert "select-games" in response.headers["Location"] or "select_games" in response.headers["Location"]

    with app.app_context():
        db = get_db()
        user_id = db.execute("SELECT id FROM User WHERE username = 'test'").fetchone()[
            "id"
        ]
        # Count should still be MAX_RESERVATIONS — no new session created
        assert get_reservation_count(user_id) == MAX_RESERVATIONS


def test_booking_redirects_unauthenticated(client, app):
    """An unauthenticated user is redirected to the login page."""
    with app.app_context():
        db = get_db()
        store_id, table_num = _insert_store_and_table(db)

    response = _post_booking(client, store_id, table_num, game_ids=[1])

    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]
