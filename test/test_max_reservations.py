"""Tests for the maximum concurrent reservations feature."""
from datetime import date, timedelta

import pytest

from d20.db import get_db
from d20.db.session import MAX_RESERVATIONS, get_reservation_count


def _insert_store_and_table(db):
    """Insert a test store and table, return (store_id, table_num)."""
    db.execute(
        "INSERT INTO Store (username, password, name) VALUES (%s, %s, %s)",
        ("storeuser", "storehash", "Test Store"),
    )
    db.commit()
    store_id = db.execute(
        "SELECT id FROM Store WHERE username = %s", ("storeuser",)
    ).fetchone()["id"]
    db.execute(
        'INSERT INTO "Table" (store_id, table_num, capacity) VALUES (%s, %s, %s)',
        (store_id, 1, 4),
    )
    db.commit()
    return store_id, 1


def _insert_session(db, user_id, store_id, table_num, day, start_time, end_time):
    """Insert a session row directly into the DB."""
    db.execute(
        "INSERT INTO Session (user_id, store_id, table_num, day, start_time, end_time)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
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
        user_id = db.execute(
            'SELECT id FROM "User" WHERE username = %s', ("test",)
        ).fetchone()["id"]
        assert get_reservation_count(user_id) == 0


def test_get_reservation_count_increments(app):
    """Count increases as sessions are added."""
    with app.app_context():
        db = get_db()
        user_id = db.execute(
            'SELECT id FROM "User" WHERE username = %s', ("test",)
        ).fetchone()["id"]
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


def _post_booking(
    client, store_id, table_num, day=None, start_time=9, end_time=11, game_ids=None
):
    if day is None:
        day = str(date.today() + timedelta(days=30))
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
        user_id = db.execute(
            'SELECT id FROM "User" WHERE username = %s', ("test",)
        ).fetchone()["id"]
        store_id, table_num = _insert_store_and_table(db)
        # Add a game copy so the booking has something to select
        db.execute(
            "INSERT INTO GameCopy (game_id, store_id, copy_num) VALUES (%s, %s, %s)",
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
        user_id = db.execute(
            'SELECT id FROM "User" WHERE username = %s', ("test",)
        ).fetchone()["id"]
        assert get_reservation_count(user_id) == 1


def test_booking_blocked_at_limit(app, client):
    """Booking is blocked when the user already has MAX_RESERVATIONS sessions."""
    with app.app_context():
        db = get_db()
        user_id = db.execute(
            'SELECT id FROM "User" WHERE username = %s', ("test",)
        ).fetchone()["id"]
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
            "INSERT INTO GameCopy (game_id, store_id, copy_num) VALUES (%s, %s, %s)",
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
        user_id = db.execute(
            'SELECT id FROM "User" WHERE username = %s', ("test",)
        ).fetchone()["id"]
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


def test_booking_in_past_is_rejected(app, client):
    """A booking whose end time is already in the past must be rejected."""
    with app.app_context():
        db = get_db()
        user_id = db.execute(
            'SELECT id FROM "User" WHERE username = %s', ("test",)
        ).fetchone()["id"]
        store_id, table_num = _insert_store_and_table(db)
        db.execute(
            "INSERT INTO GameCopy (game_id, store_id, copy_num) VALUES (%s, %s, %s)",
            (1, store_id, 1),
        )
        db.commit()

    _login(client)
    response = _post_booking(
        client, store_id, table_num, day="2000-01-01", start_time=9, end_time=11, game_ids=[1]
    )

    assert response.status_code == 302
    assert "select-games" in response.headers["Location"] or "select_games" in response.headers["Location"]

    with app.app_context():
        assert get_reservation_count(user_id) == 0


def test_booking_flow_from_book_page_to_confirm_works_for_future_date(app, client):
    """End-to-end route flow: /book -> /select-games -> /confirm-booking."""
    future_day = str(date.today() + timedelta(days=30))

    with app.app_context():
        db = get_db()
        user_id = db.execute(
            'SELECT id FROM "User" WHERE username = %s', ("test",)
        ).fetchone()["id"]
        store_id, table_num = _insert_store_and_table(db)
        db.execute(
            "INSERT INTO GameCopy (game_id, store_id, copy_num) VALUES (%s, %s, %s)",
            (1, store_id, 1),
        )
        db.commit()

    _login(client)

    browse_resp = client.get(
        f"/store/{store_id}/book?day={future_day}&start_time=9&end_time=11"
    )
    assert browse_resp.status_code == 200

    select_resp = client.get(
        f"/store/{store_id}/table/{table_num}/select-games?day={future_day}&start_time=9&end_time=11"
    )
    assert select_resp.status_code == 200

    confirm_resp = client.post(
        f"/store/{store_id}/table/{table_num}/confirm-booking",
        data={
            "day": future_day,
            "start_time": "9",
            "end_time": "11",
            "selected_games": ["1"],
        },
    )
    assert confirm_resp.status_code == 302
    assert confirm_resp.headers["Location"] == "/"

    with app.app_context():
        assert get_reservation_count(user_id) == 1


def test_booking_with_zero_duration_is_rejected(app, client):
    """start_time == end_time should not create a reservation."""
    future_day = str(date.today() + timedelta(days=30))

    with app.app_context():
        db = get_db()
        user_id = db.execute(
            'SELECT id FROM "User" WHERE username = %s', ("test",)
        ).fetchone()["id"]
        store_id, table_num = _insert_store_and_table(db)
        db.execute(
            "INSERT INTO GameCopy (game_id, store_id, copy_num) VALUES (%s, %s, %s)",
            (1, store_id, 1),
        )
        db.commit()

    _login(client)
    response = client.post(
        f"/store/{store_id}/table/{table_num}/confirm-booking",
        data={
            "day": future_day,
            "start_time": "0",
            "end_time": "0",
            "selected_games": ["1"],
        },
    )
    assert response.status_code == 302
    assert "select-games" in response.headers["Location"] or "select_games" in response.headers["Location"]

    with app.app_context():
        assert get_reservation_count(user_id) == 0
