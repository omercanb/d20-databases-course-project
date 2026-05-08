"""Tests for the reservation advance days feature (loyalty-tier-based booking window)."""
from datetime import date, timedelta

import pytest

from d20.db import get_db
from d20.db.loyalty import get_user_advance_days


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
    db.commit()
    return store_id, 1


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


# ---------------------------------------------------------------------------
# Unit-level tests for get_user_advance_days
# ---------------------------------------------------------------------------


def test_get_user_advance_days_no_loyalty_record(app):
    """A user with no LoyaltyPoint row defaults to Bronze tier's advance days."""
    with app.app_context():
        db = get_db()
        user_id = db.execute(
            'SELECT id FROM "User" WHERE username = %s', ("test",)
        ).fetchone()["id"]
        store_id, _ = _insert_store_and_table(db)

        # Set to a known value so the assertion is explicit.
        db.execute(
            "UPDATE LoyaltyTier SET reservation_advance_days = %s "
            "WHERE store_id = %s AND code = %s",
            (7, store_id, "Bronze"),
        )
        db.commit()

        # No LoyaltyPoint row exists for this user/store, so COALESCE -> 'Bronze'
        assert get_user_advance_days(user_id, store_id) == 7


def test_get_user_advance_days_with_tier(app):
    """A user whose LoyaltyPoint row assigns Silver gets Silver's advance days."""
    with app.app_context():
        db = get_db()
        user_id = db.execute(
            'SELECT id FROM "User" WHERE username = %s', ("test",)
        ).fetchone()["id"]
        store_id, _ = _insert_store_and_table(db)

        # Configure Silver tier advance days
        db.execute(
            "UPDATE LoyaltyTier SET reservation_advance_days = %s "
            "WHERE store_id = %s AND code = %s",
            (14, store_id, "Silver"),
        )
        db.commit()

        # Give user enough current points to be auto-assigned Silver (>=500)
        db.execute(
            "INSERT INTO LoyaltyPoint (user_id, store_id, points, lifetime_points) "
            "VALUES (%s, %s, %s, %s)",
            (user_id, store_id, 600, 600),
        )
        db.commit()

        assert get_user_advance_days(user_id, store_id) == 14


# ---------------------------------------------------------------------------
# Route-level tests for confirm_booking advance-days enforcement
# ---------------------------------------------------------------------------


def test_booking_within_advance_days_succeeds(app, client):
    """Booking within the allowed advance window succeeds."""
    with app.app_context():
        db = get_db()
        store_id, table_num = _insert_store_and_table(db)

        # Allow Bronze to book up to 30 days ahead
        db.execute(
            "UPDATE LoyaltyTier SET reservation_advance_days = %s "
            "WHERE store_id = %s AND code = %s",
            (30, store_id, "Bronze"),
        )
        db.commit()

        # Add a game copy for the booking
        db.execute(
            "INSERT INTO GameCopy (game_id, store_id, copy_num) VALUES (%s, %s, %s)",
            (1, store_id, 1),
        )
        db.commit()

    _login(client)
    # Book 10 days ahead — well within the 30-day window
    booking_day = str(date.today() + timedelta(days=10))
    response = _post_booking(
        client, store_id, table_num, day=booking_day, game_ids=[1]
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/"


def test_booking_beyond_advance_days_rejected(app, client):
    """Booking beyond the allowed advance window is rejected."""
    with app.app_context():
        db = get_db()
        store_id, table_num = _insert_store_and_table(db)

        # Allow Bronze to book only 2 days ahead
        db.execute(
            "UPDATE LoyaltyTier SET reservation_advance_days = %s "
            "WHERE store_id = %s AND code = %s",
            (2, store_id, "Bronze"),
        )
        db.commit()

        db.execute(
            "INSERT INTO GameCopy (game_id, store_id, copy_num) VALUES (%s, %s, %s)",
            (1, store_id, 1),
        )
        db.commit()

    _login(client)
    # Try to book 10 days ahead — exceeds the 2-day limit
    booking_day = str(date.today() + timedelta(days=10))
    response = _post_booking(
        client, store_id, table_num, day=booking_day, game_ids=[1]
    )

    assert response.status_code == 302
    loc = response.headers["Location"]
    assert "select-games" in loc or "select_games" in loc


def test_booking_same_day_always_allowed(app, client):
    """Booking for today is always allowed even when advance_days is 0."""
    with app.app_context():
        db = get_db()
        store_id, table_num = _insert_store_and_table(db)

        # Bronze default is already 0, but be explicit
        db.execute(
            "UPDATE LoyaltyTier SET reservation_advance_days = %s "
            "WHERE store_id = %s AND code = %s",
            (0, store_id, "Bronze"),
        )
        db.commit()

        db.execute(
            "INSERT INTO GameCopy (game_id, store_id, copy_num) VALUES (%s, %s, %s)",
            (1, store_id, 1),
        )
        db.commit()

    _login(client)
    # Book for today with end_time=23 to minimise the risk of the
    # "session in the past" check failing (only fails if NOW() >= 23:00).
    response = _post_booking(
        client, store_id, table_num,
        day=str(date.today()), start_time=22, end_time=23, game_ids=[1],
    )

    assert response.status_code == 302
    # Same-day with advance_days=0 means days_ahead=0 which is <= 0, so it passes.
    assert response.headers["Location"] == "/"


def test_higher_tier_more_advance_days(app, client):
    """A Silver-tier user can book further ahead than Bronze allows."""
    with app.app_context():
        db = get_db()
        user_id = db.execute(
            'SELECT id FROM "User" WHERE username = %s', ("test",)
        ).fetchone()["id"]
        store_id, table_num = _insert_store_and_table(db)

        # Bronze: 2 days, Silver: 30 days
        db.execute(
            "UPDATE LoyaltyTier SET reservation_advance_days = %s "
            "WHERE store_id = %s AND code = %s",
            (2, store_id, "Bronze"),
        )
        db.execute(
            "UPDATE LoyaltyTier SET reservation_advance_days = %s "
            "WHERE store_id = %s AND code = %s",
            (30, store_id, "Silver"),
        )
        db.commit()

        # Promote user to Silver via current points
        db.execute(
            "INSERT INTO LoyaltyPoint (user_id, store_id, points, lifetime_points) "
            "VALUES (%s, %s, %s, %s)",
            (user_id, store_id, 600, 600),
        )
        db.commit()

        db.execute(
            "INSERT INTO GameCopy (game_id, store_id, copy_num) VALUES (%s, %s, %s)",
            (1, store_id, 1),
        )
        db.commit()

    _login(client)
    # Book 10 days ahead — exceeds Bronze(2) but within Silver(30)
    booking_day = str(date.today() + timedelta(days=10))
    response = _post_booking(
        client, store_id, table_num, day=booking_day, game_ids=[1]
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/"
