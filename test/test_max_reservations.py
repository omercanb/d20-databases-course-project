"""Tests for the maximum concurrent reservations feature."""
from datetime import date, datetime, timedelta

from psycopg2 import errors
import pytest

from d20.db import get_db
from d20.db.session import (
    MAX_RESERVATIONS,
    create_session,
    get_available_tables,
    get_reservation_count,
)
from d20.routes import stores as store_routes


def _insert_store_and_table(db):
    """Insert a test store and table, return (store_id, table_num)."""
    db.execute(
        "INSERT INTO Store (username, password, name, address) VALUES (%s, %s, %s, %s)",
        ("storeuser", "storehash", "Test Store", "Test Address"),
    )
    db.commit()
    store_id = db.execute(
        "SELECT id FROM Store WHERE username = %s", ("storeuser",)
    ).fetchone()["id"]
    db.execute(
        'INSERT INTO "Table" (store_id, table_num, capacity) VALUES (%s, %s, %s)',
        (store_id, 1, 4),
    )
    db.execute(
        "UPDATE LoyaltyTier SET reservation_advance_days = 365 WHERE store_id = %s",
        (store_id,),
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


def test_get_available_tables_filters_by_min_capacity(app):
    """Available table lookup can restrict results to tables with enough seats."""
    future_day = str(date.today() + timedelta(days=30))

    with app.app_context():
        db = get_db()
        store_id, _ = _insert_store_and_table(db)
        db.execute(
            'INSERT INTO "Table" (store_id, table_num, capacity) VALUES (%s, %s, %s)',
            (store_id, 2, 8),
        )
        db.commit()

        tables = get_available_tables(
            store_id, future_day, 9, 11, min_capacity=6
        )

    assert [table["table_num"] for table in tables] == [2]


def test_book_page_filters_tables_by_min_capacity(app, client):
    """The booking page only shows tables that satisfy the capacity filter."""
    future_day = str(date.today() + timedelta(days=30))

    with app.app_context():
        db = get_db()
        store_id, _ = _insert_store_and_table(db)
        db.execute(
            'INSERT INTO "Table" (store_id, table_num, capacity) VALUES (%s, %s, %s)',
            (store_id, 2, 8),
        )
        db.commit()

    response = client.get(
        f"/store/{store_id}/book?day={future_day}&start_time=9&end_time=11&min_capacity=6"
    )

    assert response.status_code == 200
    body = response.data.decode()
    assert 'value="6"' in body
    assert "Table 2" in body
    assert "Seats: 8" in body
    assert "Table 1" not in body
    assert "Seats: 4" not in body


def test_booking_in_past_is_rejected(app, client):
    """A booking whose start time is already in the past must be rejected."""
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


def test_same_day_booking_before_current_time_is_rejected(app, client):
    """A same-day booking cannot start before the current time."""
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
        client, store_id, table_num, day=str(date.today()), start_time=0, end_time=23, game_ids=[1]
    )

    assert response.status_code == 302
    assert "select-games" in response.headers["Location"] or "select_games" in response.headers["Location"]

    with app.app_context():
        assert get_reservation_count(user_id) == 0


def test_create_session_rejects_same_day_start_before_current_time(app):
    """The backend helper rejects a slot that has already started."""
    with app.app_context():
        db = get_db()
        store_id, table_num = _insert_store_and_table(db)
        db.execute(
            "INSERT INTO GameCopy (game_id, store_id, copy_num) VALUES (%s, %s, %s)",
            (1, store_id, 1),
        )
        db.commit()

        with pytest.raises(ValueError, match="Cannot book a session in the past."):
            create_session(1, store_id, table_num, str(date.today()), 0, 23, [1])


def test_session_table_rejects_active_past_start_time(app):
    """The database rejects direct active-session inserts that bypass route code."""
    with app.app_context():
        db = get_db()
        store_id, table_num = _insert_store_and_table(db)

        with pytest.raises(errors.CheckViolation) as exc_info:
            db.execute(
                "INSERT INTO Session (user_id, store_id, table_num, day, start_time, end_time)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (1, store_id, table_num, str(date.today()), 0, 23),
            )

        assert exc_info.value.diag.constraint_name == "session_start_time_not_past"
        db.rollback()


def test_book_page_clamps_today_slider_to_next_bookable_hour(app, client, monkeypatch):
    """The browser slider cannot choose hours that have already started today."""
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.combine(date.today(), datetime.min.time()).replace(hour=15, minute=30)

    monkeypatch.setattr(store_routes, "datetime", FixedDateTime)

    with app.app_context():
        db = get_db()
        store_id, _ = _insert_store_and_table(db)

    response = client.get(f"/store/{store_id}/book?day={date.today()}&start_time=9&end_time=20")

    assert response.status_code == 200
    body = response.data.decode()
    assert "const currentHour = 15;" in body
    assert "const initialStart = Math.max(16, initialMinStart);" in body


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
