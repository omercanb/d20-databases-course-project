from d20.db import get_db

MAX_RESERVATIONS = 2


def get_reservation_count(user_id):
    row = get_db().execute(
        "select count(*) as cnt from Session where user_id = ? and (day > date('now') or (day = date('now') and end_time > cast(strftime('%H', 'now', 'localtime') as integer)))",
        (user_id,)
    ).fetchone()
    return row["cnt"]


def create_session(
    user_id, store_id, table_num, day, start_time, end_time, game_ids=None
):
    db = get_db()
    occupied_table = db.execute(
        """
        select 1 from Session
        where store_id = ?
        and table_num = ?
        and day = ?
        and start_time < ?
        and end_time > ?
        limit 1
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
                select copy_num from GameCopy
                where game_id = ?
                and store_id = ?
                and is_available = 1
                and not exists (
                    select 1
                    from SessionGameCopy
                    join Session on (SessionGameCopy.session_id = Session.id)
                    where SessionGameCopy.game_id = GameCopy.game_id
                    and SessionGameCopy.store_id = GameCopy.store_id
                    and SessionGameCopy.copy_num = GameCopy.copy_num
                    and Session.day = ?
                    and Session.start_time < ?
                    and Session.end_time > ?
                )
                order by copy_num
                limit 1
                """,
                (game_id, store_id, day, end_time, start_time),
            ).fetchone()

            if not copy:
                raise ValueError(
                    "The game you selected has no available copies at the selected time slot."
                )
            game_copies.append((game_id, copy["copy_num"]))

    cursor = db.execute(
        "insert into Session (user_id, store_id, table_num, day, start_time, end_time)"
        " values (?, ?, ?, ?, ?, ?)",
        (user_id, store_id, table_num, day, start_time, end_time),
    )
    session_id = cursor.lastrowid

    for game_id, copy_num in game_copies:
        db.execute(
            "insert into SessionGameCopy (session_id, game_id, store_id, copy_num)"
            " values (?, ?, ?, ?)",
            (session_id, game_id, store_id, copy_num),
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
