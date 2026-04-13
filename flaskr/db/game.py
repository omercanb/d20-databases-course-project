from flaskr.db import get_db


# Game Functions
def create_game(name):
    db = get_db()
    cursor = db.execute(
        f"insert into Game (name) values (?)",
        (name,),
    )
    db.commit()
    return cursor.lastrowid


def get_games():
    return get_db().execute("select * from Game").fetchall()


def get_game(game_id):
    return get_db().execute("select * from Game where id = ?", (game_id,)).fetchone()


def get_game_by_name(name):
    return get_db().execute("select * from Game where name = ?", (name,)).fetchone()


def delete_game(game_id):
    db = get_db()
    db.execute("delete from Game where id = ?", (game_id,))
    db.commit()


# GameCopy Functions
def create_game_copy(game_id, store_id):
    db = get_db()
    next_num = db.execute(
        "select coalesce(max(copy_num), 0) + 1 from GameCopy where game_id = ? and store_id = ?",
        (game_id, store_id),
    ).fetchone()[0]
    db.execute(
        f"insert into GameCopy (game_id, store_id, copy_num) values (?, ?, ?)",
        (game_id, store_id, next_num),
    )
    db.commit()
    return next_num


def get_game_copies(store_id):
    return (
        get_db()
        .execute(
            "select * from GameCopy join Game on (game_id = id) where store_id = ?",
            (store_id,),
        )
        .fetchall()
    )


def get_game_copy_count(store_id):
    return (
        get_db()
        .execute("select count(*) from GameCopy where store_id = ?", (store_id,))
        .fetchone()[0]
    )


def get_game_copies_by_game(game_id, store_id):
    return (
        get_db()
        .execute(
            "select * from GameCopy where game_id = ? and store_id = ?",
            (game_id, store_id),
        )
        .fetchall()
    )


def delete_game_copy(game_id, store_id, copy_num):
    db = get_db()
    db.execute(
        "delete from GameCopy where game_id = ? and store_id = ? and copy_num = ?",
        (game_id, store_id, copy_num),
    )
    db.commit()


def get_available_games_during(store_id, day, start_time, end_time):
    """Get games with at least one available copy during the time interval."""
    return (
        get_db()
        .execute(
            """
            select Game.id, Game.name,
                   count(GameCopy.copy_num) as total_copies,
                   (count(GameCopy.copy_num) - coalesce(sum(
                       case when SessionGameCopy.session_id is not null
                            and Session.day = ?
                            and Session.start_time < ?
                            and Session.end_time > ?
                       then 1 else 0 end
                   ), 0)) as available_copies
            from Game
            join GameCopy on (Game.id = GameCopy.game_id and GameCopy.store_id = ?)
            left join SessionGameCopy on (GameCopy.game_id = SessionGameCopy.game_id
                                         and GameCopy.store_id = SessionGameCopy.store_id
                                         and GameCopy.copy_num = SessionGameCopy.copy_num)
            left join Session on (SessionGameCopy.session_id = Session.id)
            group by Game.id, Game.name
            having available_copies > 0
            order by Game.name
            """,
            (day, end_time, start_time, store_id),
        )
        .fetchall()
    )


def get_unavailable_games_during(store_id, day, start_time, end_time):
    """Get games with zero available copies during the time interval."""
    return (
        get_db()
        .execute(
            """
            select Game.id, Game.name,
                   count(GameCopy.copy_num) as total_copies,
                   (count(GameCopy.copy_num) - coalesce(sum(
                       case when SessionGameCopy.session_id is not null
                            and Session.day = ?
                            and Session.start_time < ?
                            and Session.end_time > ?
                       then 1 else 0 end
                   ), 0)) as available_copies
            from Game
            join GameCopy on (Game.id = GameCopy.game_id and GameCopy.store_id = ?)
            left join SessionGameCopy on (GameCopy.game_id = SessionGameCopy.game_id
                                         and GameCopy.store_id = SessionGameCopy.store_id
                                         and GameCopy.copy_num = SessionGameCopy.copy_num)
            left join Session on (SessionGameCopy.session_id = Session.id)
            group by Game.id, Game.name
            having available_copies = 0
            order by Game.name
            """,
            (day, end_time, start_time, store_id),
        )
        .fetchall()
    )


def get_available_games_with_counts(store_id):
    return (
        get_db()
        .execute(
            """
            select Game.id, Game.name, count(*) as copy_count
            from Game
            join GameCopy on (Game.id = GameCopy.game_id)
            where GameCopy.store_id = ?
            group by Game.id, Game.name
            """,
            (store_id,),
        )
        .fetchall()
    )


# GameDamage Functions
def report_damage(session_id, game_id, store_id, copy_num, description):
    db = get_db()
    db.execute(
        "insert into GameDamage (session_id, game_id, store_id, copy_num, description)"
        " values (?, ?, ?, ?, ?)",
        (session_id, game_id, store_id, copy_num, description),
    )
    db.commit()


def get_damage_report(session_id, game_id, store_id, copy_num):
    return (
        get_db()
        .execute(
            "select * from GameDamage where session_id = ? and game_id = ? and store_id = ? and copy_num = ?",
            (session_id, game_id, store_id, copy_num),
        )
        .fetchone()
    )


def get_damage_reports_by_session(session_id):
    return (
        get_db()
        .execute(
            """
            select GameDamage.*, Game.name
            from GameDamage
            join Game on (GameDamage.game_id = Game.id)
            where GameDamage.session_id = ?
            """,
            (session_id,),
        )
        .fetchall()
    )


def get_damage_reports_by_game_copy(game_id, store_id, copy_num):
    return (
        get_db()
        .execute(
            "select * from GameDamage where game_id = ? and store_id = ? and copy_num = ?",
            (game_id, store_id, copy_num),
        )
        .fetchall()
    )


def delete_damage_report(session_id, game_id, store_id, copy_num):
    db = get_db()
    db.execute(
        "delete from GameDamage where session_id = ? and game_id = ? and store_id = ? and copy_num = ?",
        (session_id, game_id, store_id, copy_num),
    )
    db.commit()
