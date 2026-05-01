from datetime import date

from d20.db import get_db

MAX_RESERVATIONS = 2


def get_reservation_count(user_id):
    row = get_db().execute(
        "SELECT COUNT(*) AS cnt FROM Session WHERE user_id = %s"
        " AND (day::date + (end_time || ' hours')::interval) > NOW()",
        (user_id,)
    ).fetchone()
    return row["cnt"]


def create_session(
    user_id, store_id, table_num, day, start_time, end_time, game_ids=None
):
    if end_time <= start_time:
        raise ValueError("End time must be later than start time.")

    db = get_db()
    session_day = date.fromisoformat(day.strip())
    is_future = db.execute(
        "SELECT (%s::date + (%s || ' hours')::interval) > NOW() AS is_future",
        (session_day.isoformat(), end_time),
    ).fetchone()["is_future"]
    if not is_future:
        raise ValueError("Cannot book a session in the past.")

    occupied_table = db.execute(
        """
        SELECT 1 FROM Session
        WHERE store_id = %s
        AND table_num = %s
        AND day = %s
        AND start_time < %s
        AND end_time > %s
        LIMIT 1
        """,
        (store_id, table_num, day, end_time, start_time),
    ).fetchone()
    if occupied_table:
        raise ValueError("The table you selected is occupied at the selected time slot.")

    game_copies = []
    if game_ids:
        for game_id in game_ids:
            copy = db.execute(
                """
                SELECT copy_num FROM GameCopy
                WHERE game_id = %s
                AND store_id = %s
                AND is_available = TRUE
                AND NOT EXISTS (
                    SELECT 1
                    FROM SessionGameCopy
                    JOIN Session ON (SessionGameCopy.session_id = Session.id)
                    WHERE SessionGameCopy.game_id = GameCopy.game_id
                    AND SessionGameCopy.store_id = GameCopy.store_id
                    AND SessionGameCopy.copy_num = GameCopy.copy_num
                    AND Session.day = %s
                    AND Session.start_time < %s
                    AND Session.end_time > %s
                )
                ORDER BY copy_num
                LIMIT 1
                """,
                (game_id, store_id, day, end_time, start_time),
            ).fetchone()

            if not copy:
                raise ValueError(
                    "The game you selected has no available copies at the selected time slot."
                )
            game_copies.append((game_id, copy["copy_num"]))

    cursor = db.execute(
        "INSERT INTO Session (user_id, store_id, table_num, day, start_time, end_time)"
        " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (user_id, store_id, table_num, day, start_time, end_time),
    )
    session_id = cursor.fetchone()["id"]

    for game_id, copy_num in game_copies:
        db.execute(
            "INSERT INTO SessionGameCopy (session_id, game_id, store_id, copy_num)"
            " VALUES (%s, %s, %s, %s)",
            (session_id, game_id, store_id, copy_num),
        )

    db.commit()
    return session_id


def get_session(session_id):
    return (
        get_db().execute("SELECT * FROM Session WHERE id = %s", (session_id,)).fetchone()
    )


def get_session_games(session_id):
    return (
        get_db()
        .execute(
            """
            SELECT SessionGameCopy.*, Game.name
            FROM SessionGameCopy
            JOIN Game ON (SessionGameCopy.game_id = Game.id)
            WHERE SessionGameCopy.session_id = %s
            """,
            (session_id,),
        )
        .fetchall()
    )


def get_sessions_by_user(user_id):
    return (
        get_db()
        .execute("SELECT * FROM Session WHERE user_id = %s", (user_id,))
        .fetchall()
    )


def get_sessions_with_store_by_user(user_id):
    return (
        get_db()
        .execute(
            """
            SELECT Session.*, Store.name AS store_name
            FROM Session
            JOIN Store ON (Session.store_id = Store.id)
            WHERE Session.user_id = %s
            ORDER BY Session.day DESC, Session.start_time DESC
            """,
            (user_id,),
        )
        .fetchall()
    )


def get_sessions_by_store(store_id):
    return (
        get_db()
        .execute("SELECT * FROM Session WHERE store_id = %s", (store_id,))
        .fetchall()
    )


def get_upcoming_sessions_with_user_by_store(store_id, today):
    return (
        get_db()
        .execute(
            """
            SELECT Session.*, "User".username
            FROM Session
            JOIN "User" ON (Session.user_id = "User".id)
            WHERE Session.store_id = %s
            AND Session.day >= %s
            ORDER BY Session.day ASC, Session.start_time ASC
            """,
            (store_id, today),
        )
        .fetchall()
    )


def update_session(session_id, day, start_time, end_time):
    db = get_db()
    db.execute(
        "UPDATE Session SET day = %s, start_time = %s, end_time = %s WHERE id = %s",
        (day, start_time, end_time, session_id),
    )
    db.commit()


def delete_session(session_id):
    db = get_db()
    db.execute("DELETE FROM SessionGameCopy WHERE session_id = %s", (session_id,))
    db.execute("DELETE FROM Session WHERE id = %s", (session_id,))
    db.commit()


def get_available_tables(store_id, day, start_time, end_time):
    return (
        get_db()
        .execute(
            """
            SELECT * FROM "Table"
            WHERE store_id = %s
            AND (store_id, table_num) NOT IN (
                SELECT store_id, table_num FROM Session
                WHERE store_id = %s
                AND day = %s
                AND start_time < %s
                AND end_time > %s
            )
            """,
            (store_id, store_id, day, end_time, start_time),
        )
        .fetchall()
    )


def get_unavailable_tables(store_id, day, start_time, end_time):
    return (
        get_db()
        .execute(
            """
            SELECT * FROM "Table"
            WHERE store_id = %s
            AND (store_id, table_num) IN (
                SELECT store_id, table_num FROM Session
                WHERE store_id = %s
                AND day = %s
                AND start_time < %s
                AND end_time > %s
            )
            """,
            (store_id, store_id, day, end_time, start_time),
        )
        .fetchall()
    )
