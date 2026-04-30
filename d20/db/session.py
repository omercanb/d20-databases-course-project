from d20.db import get_db

MAX_RESERVATIONS = 2


def get_reservation_count(user_id):
    row = get_db().execute(
        "select count(*) as cnt from Session where user_id = ? and (day > date('now') or (day = date('now') and end_time > strftime('%H', 'now', 'localtime')))",
        (user_id,)
    ).fetchone()
    return row["cnt"]


def create_session(
    user_id, store_id, table_num, day, start_time, end_time, game_ids=None
):
    db = get_db()
    cursor = db.execute(
        "insert into Session (user_id, store_id, table_num, day, start_time, end_time)"
        " values (?, ?, ?, ?, ?, ?)",
        (user_id, store_id, table_num, day, start_time, end_time),
    )
    session_id = cursor.lastrowid

    if game_ids:
        for game_id in game_ids:
            # Get the first available copy of this game at this store
            copy = db.execute(
                "select copy_num from GameCopy where game_id = ? and store_id = ? limit 1",
                (game_id, store_id),
            ).fetchone()

            if copy:
                db.execute(
                    "insert into SessionGameCopy (session_id, game_id, store_id, copy_num)"
                    " values (?, ?, ?, ?)",
                    (session_id, game_id, store_id, copy["copy_num"]),
                )

    db.commit()
    return session_id


def get_session(session_id):
    return (
        get_db().execute("select * from Session where id = ?", (session_id,)).fetchone()
    )


def get_session_games(session_id):
    return (
        get_db()
        .execute(
            """
            select SessionGameCopy.*, Game.name
            from SessionGameCopy
            join Game on (SessionGameCopy.game_id = Game.id)
            where SessionGameCopy.session_id = ?
            """,
            (session_id,),
        )
        .fetchall()
    )


def get_sessions_by_user(user_id):
    return (
        get_db()
        .execute("select * from Session where user_id = ?", (user_id,))
        .fetchall()
    )


def get_sessions_with_store_by_user(user_id):
    return (
        get_db()
        .execute(
            """
            select Session.*, Store.name as store_name
            from Session
            join Store on (Session.store_id = Store.id)
            where Session.user_id = ?
            order by Session.day desc, Session.start_time desc
            """,
            (user_id,),
        )
        .fetchall()
    )


def get_sessions_by_store(store_id):
    return (
        get_db()
        .execute("select * from Session where store_id = ?", (store_id,))
        .fetchall()
    )


def get_upcoming_sessions_with_user_by_store(store_id, today):
    return (
        get_db()
        .execute(
            """
            select Session.*, User.username
            from Session
            join User on (Session.user_id = User.id)
            where Session.store_id = ?
            and Session.day >= ?
            order by Session.day asc, Session.start_time asc
            """,
            (store_id, today),
        )
        .fetchall()
    )


def update_session(session_id, day, start_time, end_time):
    db = get_db()
    db.execute(
        "update Session set day = ?, start_time = ?, end_time = ? where id = ?",
        (day, start_time, end_time, session_id),
    )
    db.commit()


def delete_session(session_id):
    db = get_db()
    db.execute("delete from Session where id = ?", (session_id,))
    db.commit()


def get_available_tables(store_id, day, start_time, end_time):
    return (
        get_db()
        .execute(
            """
        select * from "Table"
        where store_id = ?
        and (store_id, table_num) not in (
            select store_id, table_num from Session
            where store_id = ?
            and day = ?
            and start_time < ?
            and end_time > ?
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
        select * from "Table"
        where store_id = ?
        and (store_id, table_num) in (
            select store_id, table_num from Session
            where store_id = ?
            and day = ?
            and start_time < ?
            and end_time > ?
        )
        """,
            (store_id, store_id, day, end_time, start_time),
        )
        .fetchall()
    )
