from d20.db import get_db


# Game Functions
def create_game(name, symbol, genre=None, min_players=None, max_players=None,
                complexity_rating=None, avg_duration=None, description=None,
                publisher=None, strategy_rating=None, luck_rating=None,
                interaction_rating=None):
    db = get_db()
    cursor = db.execute(
        "insert into Game (name, publisher, symbol, genre, min_players, max_players,"
        " avg_duration, complexity_rating, strategy_rating, luck_rating, interaction_rating, description)"
        " values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name, publisher, symbol, genre, min_players, max_players,
         avg_duration, complexity_rating, strategy_rating, luck_rating, interaction_rating, description),
    )
    db.commit()
    return cursor.lastrowid


def get_games():
    return get_db().execute("select * from Game").fetchall()


def get_game(game_id):
    return get_db().execute("select * from Game where id = ?", (game_id,)).fetchone()


def get_game_by_name(name):
    return get_db().execute("select * from Game where name = ?", (name,)).fetchone()


def get_game_id_by_symbol(symbol):
    game = get_game_by_symbol(symbol)
    if not game:
        raise InvalidSymbolError(symbol)
    return game["id"]


class InvalidSymbolError(Exception):
    def __init__(self, symbol):
        self.symbol = symbol
        super().__init__(f"Symbol not found: {symbol}")


def get_game_by_symbol(symbol):
    return get_db().execute("select * from Game where symbol = ?", (symbol,)).fetchone()


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
        "insert into GameCopy (game_id, store_id, copy_num) values (?, ?, ?)",
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
            select Game.*,
                   count(GameCopy.copy_num) as total_copies,
                   coalesce(sum(
                       case when GameCopy.is_available = 1
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
                       then 1 else 0 end
                   ), 0) as available_copies
            from Game
            join GameCopy on (Game.id = GameCopy.game_id and GameCopy.store_id = ?)
            group by Game.id
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
            select Game.*,
                   count(GameCopy.copy_num) as total_copies,
                   coalesce(sum(
                       case when GameCopy.is_available = 1
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
                       then 1 else 0 end
                   ), 0) as available_copies
            from Game
            join GameCopy on (Game.id = GameCopy.game_id and GameCopy.store_id = ?)
            group by Game.id
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


# Game Library / Browse Functions

def get_games_filtered(store_id, genre=None, min_players=None, max_players=None,
                       user_rating=None, complexity_rating=None, strategy_rating=None,
                       luck_rating=None, interaction_rating=None, max_avg_duration=None,
                       available_only=False, search=None):
    """Get games at a store with optional filters."""
    query = """
        select distinct Game.*
        from Game
        join GameCopy on (Game.id = GameCopy.game_id and GameCopy.store_id = ?)
        where 1=1
    """
    params = [store_id]

    if genre is not None:
        query += " and Game.genre = ?"
        params.append(genre)
    if min_players is not None:
        query += " and Game.min_players >= ?"
        params.append(min_players)
    if max_players is not None:
        query += " and Game.max_players <= ?"
        params.append(max_players)
    if user_rating is not None:
        query += " and Game.avg_rating >= ?"
        params.append(user_rating)
    if complexity_rating is not None:
        query += " and Game.complexity_rating = ?"
        params.append(complexity_rating)
    if strategy_rating is not None:
        query += " and Game.strategy_rating = ?"
        params.append(strategy_rating)
    if luck_rating is not None:
        query += " and Game.luck_rating = ?"
        params.append(luck_rating)
    if interaction_rating is not None:
        query += " and Game.interaction_rating = ?"
        params.append(interaction_rating)
    if max_avg_duration is not None:
        query += " and Game.avg_duration <= ?"
        params.append(max_avg_duration)
    if available_only:
        query += """
            and Game.id in (
                select GameCopy.game_id
                from GameCopy
                where GameCopy.store_id = ?
                and GameCopy.is_available = 1
                group by GameCopy.game_id
            )
        """
        params.append(store_id)
    if search is not None:
        query += " and (Game.name like ? or Game.description like ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    query += " order by Game.name"
    return get_db().execute(query, params).fetchall()


def get_game_detail(game_id):
    return get_db().execute("select * from Game where id = ?", (game_id,)).fetchone()


def _rating_similarity(game, other, column, weight):
    if game[column] is None or other[column] is None:
        return 0
    diff = abs(game[column] - other[column])
    if diff >= 4:
        return 0
    return weight * (1 - (diff * 0.25))


def _duration_similarity(game, other):
    if game["avg_duration"] is None or other["avg_duration"] is None:
        return 0
    diff = abs(game["avg_duration"] - other["avg_duration"])
    if diff <= 15:
        return 10
    if diff <= 30:
        return 7.5
    if diff <= 60:
        return 5
    if diff <= 90:
        return 2.5
    return 0


def _player_similarity(game, other):
    if (
        game["min_players"] is None
        or game["max_players"] is None
        or other["min_players"] is None
        or other["max_players"] is None
    ):
        return 0

    overlap = min(game["max_players"], other["max_players"]) - max(
        game["min_players"], other["min_players"]
    ) + 1
    if overlap <= 0:
        return 0

    game_range = game["max_players"] - game["min_players"] + 1
    other_range = other["max_players"] - other["min_players"] + 1
    return 20 * (overlap / max(game_range, other_range))


def _similarity_score(game, other):
    score = 0
    if game["genre"] is not None and game["genre"] == other["genre"]:
        score += 35
    score += _player_similarity(game, other)
    score += _rating_similarity(game, other, "complexity_rating", 10)
    score += _rating_similarity(game, other, "strategy_rating", 10)
    score += _rating_similarity(game, other, "interaction_rating", 10)
    score += _rating_similarity(game, other, "luck_rating", 5)
    score += _duration_similarity(game, other)
    return round(score, 2)


def refresh_game_similarities():
    db = get_db()
    games = db.execute("select * from Game").fetchall()
    db.execute("delete from GameSimilarity")
    for game in games:
        for other in games:
            if game["id"] != other["id"]:
                db.execute(
                    "insert into GameSimilarity (id1, id2, score) values (?, ?, ?)",
                    (game["id"], other["id"], _similarity_score(game, other)),
                )
    db.commit()


def get_similar_games(game_id, store_id, limit=3):
    return (
        get_db()
        .execute(
            """
            select distinct Game.*, GameSimilarity.score as similarity_score
            from GameSimilarity
            join Game on (GameSimilarity.id2 = Game.id)
            join GameCopy on (Game.id = GameCopy.game_id and GameCopy.store_id = ?)
            where GameSimilarity.id1 = ?
            order by GameSimilarity.score desc, Game.name
            limit ?
            """,
            (store_id, game_id, limit),
        )
        .fetchall()
    )


def get_store_genres(store_id):
    return get_db().execute(
        """
        select distinct Game.genre
        from Game
        join GameCopy on (Game.id = GameCopy.game_id and GameCopy.store_id = ?)
        where Game.genre is not null
        order by Game.genre
        """,
        (store_id,),
    ).fetchall()


def get_game_copies_with_condition(game_id, store_id):
    """Return all GameCopy rows for a game at a store (includes condition column)."""
    return (
        get_db()
        .execute(
            "select * from GameCopy where game_id = ? and store_id = ?",
            (game_id, store_id),
        )
        .fetchall()
    )


def rate_game(user_id, game_id, rating, comment=None):
    """Insert or replace a rating, then recompute avg_rating on the Game row."""
    db = get_db()
    db.execute(
        "insert or replace into GameRating (user_id, game_id, rating, comment) values (?, ?, ?, ?)",
        (user_id, game_id, rating, comment),
    )
    db.execute(
        "update Game set avg_rating = (select avg(rating) from GameRating where game_id = ?) where id = ?",
        (game_id, game_id),
    )
    db.commit()


def get_user_rating(user_id, game_id):
    """Return the GameRating row for this user/game pair, or None."""
    return (
        get_db()
        .execute(
            "select * from GameRating where user_id = ? and game_id = ?",
            (user_id, game_id),
        )
        .fetchone()
    )


def get_game_ratings(game_id):
    """Return all user ratings for a game."""
    return (
        get_db()
        .execute(
            """
            select GameRating.*, User.username
            from GameRating
            join User on (GameRating.user_id = User.id)
            where GameRating.game_id = ?
            order by User.username
            """,
            (game_id,),
        )
        .fetchall()
    )
