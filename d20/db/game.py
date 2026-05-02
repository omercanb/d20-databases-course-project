from d20.db import get_db


# Game Functions
def create_game(name, symbol, genre=None, min_players=None, max_players=None,
                complexity_rating=None, avg_duration=None, description=None,
                publisher=None, strategy_rating=None, luck_rating=None,
                interaction_rating=None):
    db = get_db()
    cursor = db.execute(
        "INSERT INTO Game (name, publisher, symbol, genre, min_players, max_players,"
        " avg_duration, complexity_rating, strategy_rating, luck_rating, interaction_rating, description)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (name, publisher, symbol, genre, min_players, max_players,
         avg_duration, complexity_rating, strategy_rating, luck_rating, interaction_rating, description),
    )
    db.commit()
    return cursor.fetchone()["id"]


def get_games():
    return get_db().execute("SELECT * FROM Game").fetchall()


def get_game(game_id):
    return get_db().execute("SELECT * FROM Game WHERE id = %s", (game_id,)).fetchone()


def get_game_by_name(name):
    return get_db().execute("SELECT * FROM Game WHERE name = %s", (name,)).fetchone()


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
    return get_db().execute("SELECT * FROM Game WHERE symbol = %s", (symbol,)).fetchone()


def delete_game(game_id):
    db = get_db()
    db.execute("DELETE FROM Game WHERE id = %s", (game_id,))
    db.commit()


# GameCopy Functions
def create_game_copy(game_id, store_id):
    db = get_db()
    next_num = db.execute(
        "SELECT COALESCE(MAX(copy_num), 0) + 1 AS next_num FROM GameCopy WHERE game_id = %s AND store_id = %s",
        (game_id, store_id),
    ).fetchone()["next_num"]
    db.execute(
        "INSERT INTO GameCopy (game_id, store_id, copy_num) VALUES (%s, %s, %s)",
        (game_id, store_id, next_num),
    )
    db.commit()
    return next_num


def get_game_copies(store_id):
    return (
        get_db()
        .execute(
            "SELECT * FROM GameCopy JOIN Game ON (game_id = id) WHERE store_id = %s",
            (store_id,),
        )
        .fetchall()
    )


def get_game_copy_count(store_id):
    return (
        get_db()
        .execute("SELECT COUNT(*) AS cnt FROM GameCopy WHERE store_id = %s", (store_id,))
        .fetchone()["cnt"]
    )


def get_game_copies_by_game(game_id, store_id):
    return (
        get_db()
        .execute(
            "SELECT * FROM GameCopy WHERE game_id = %s AND store_id = %s",
            (game_id, store_id),
        )
        .fetchall()
    )


def get_latest_game_copy(game_id, store_id):
    """Return the GameCopy row with the highest copy_num for a game at a store, or None."""
    return (
        get_db()
        .execute(
            "SELECT copy_num FROM GameCopy WHERE game_id = %s AND store_id = %s ORDER BY copy_num DESC LIMIT 1",
            (game_id, store_id),
        )
        .fetchone()
    )


def delete_game_copy(game_id, store_id, copy_num):
    db = get_db()
    db.execute(
        "DELETE FROM GameCopy WHERE game_id = %s AND store_id = %s AND copy_num = %s",
        (game_id, store_id, copy_num),
    )
    db.commit()


def get_available_games_during(store_id, day, start_time, end_time):
    """Get games with at least one available copy during the time interval."""
    return (
        get_db()
        .execute(
            """
            SELECT Game.*,
                   COUNT(GameCopy.copy_num) AS total_copies,
                   COALESCE(SUM(
                       CASE WHEN GameCopy.is_available = TRUE
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
                       THEN 1 ELSE 0 END
                   ), 0) AS available_copies
            FROM Game
            JOIN GameCopy ON (Game.id = GameCopy.game_id AND GameCopy.store_id = %s)
            GROUP BY Game.id
            HAVING COALESCE(SUM(
                       CASE WHEN GameCopy.is_available = TRUE
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
                       THEN 1 ELSE 0 END
                   ), 0) > 0
            ORDER BY Game.name
            """,
            (day, end_time, start_time, store_id, day, end_time, start_time),
        )
        .fetchall()
    )


def get_unavailable_games_during(store_id, day, start_time, end_time):
    """Get games with zero available copies during the time interval."""
    return (
        get_db()
        .execute(
            """
            SELECT Game.*,
                   COUNT(GameCopy.copy_num) AS total_copies,
                   COALESCE(SUM(
                       CASE WHEN GameCopy.is_available = TRUE
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
                       THEN 1 ELSE 0 END
                   ), 0) AS available_copies
            FROM Game
            JOIN GameCopy ON (Game.id = GameCopy.game_id AND GameCopy.store_id = %s)
            GROUP BY Game.id
            HAVING COALESCE(SUM(
                       CASE WHEN GameCopy.is_available = TRUE
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
                       THEN 1 ELSE 0 END
                   ), 0) = 0
            ORDER BY Game.name
            """,
            (day, end_time, start_time, store_id, day, end_time, start_time),
        )
        .fetchall()
    )


def get_available_games_with_counts(store_id):
    return (
        get_db()
        .execute(
            """
            SELECT Game.id, Game.name, Game.image_url, COUNT(*) AS copy_count
            FROM Game
            JOIN GameCopy ON (Game.id = GameCopy.game_id)
            WHERE GameCopy.store_id = %s
            GROUP BY Game.id, Game.name, Game.image_url
            """,
            (store_id,),
        )
        .fetchall()
    )


# GameDamage Functions
def report_damage(session_id, game_id, store_id, copy_num, description):
    db = get_db()
    db.execute(
        "INSERT INTO GameDamage (session_id, game_id, store_id, copy_num, description)"
        " VALUES (%s, %s, %s, %s, %s)",
        (session_id, game_id, store_id, copy_num, description),
    )
    db.commit()


def get_damage_report(session_id, game_id, store_id, copy_num):
    return (
        get_db()
        .execute(
            "SELECT * FROM GameDamage WHERE session_id = %s AND game_id = %s AND store_id = %s AND copy_num = %s",
            (session_id, game_id, store_id, copy_num),
        )
        .fetchone()
    )


def get_damage_reports_by_session(session_id):
    return (
        get_db()
        .execute(
            """
            SELECT GameDamage.*, Game.name
            FROM GameDamage
            JOIN Game ON (GameDamage.game_id = Game.id)
            WHERE GameDamage.session_id = %s
            """,
            (session_id,),
        )
        .fetchall()
    )


def get_damage_reports_by_game_copy(game_id, store_id, copy_num):
    return (
        get_db()
        .execute(
            "SELECT * FROM GameDamage WHERE game_id = %s AND store_id = %s AND copy_num = %s",
            (game_id, store_id, copy_num),
        )
        .fetchall()
    )


def delete_damage_report(session_id, game_id, store_id, copy_num):
    db = get_db()
    db.execute(
        "DELETE FROM GameDamage WHERE session_id = %s AND game_id = %s AND store_id = %s AND copy_num = %s",
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
        SELECT DISTINCT Game.*
        FROM Game
        JOIN GameCopy ON (Game.id = GameCopy.game_id AND GameCopy.store_id = %s)
        WHERE 1=1
    """
    params = [store_id]

    if genre is not None:
        query += " AND Game.genre = %s"
        params.append(genre)
    if min_players is not None:
        query += " AND Game.min_players >= %s"
        params.append(min_players)
    if max_players is not None:
        query += " AND Game.max_players <= %s"
        params.append(max_players)
    if user_rating is not None:
        query += " AND Game.avg_rating >= %s"
        params.append(user_rating)
    if complexity_rating is not None:
        query += " AND Game.complexity_rating = %s"
        params.append(complexity_rating)
    if strategy_rating is not None:
        query += " AND Game.strategy_rating = %s"
        params.append(strategy_rating)
    if luck_rating is not None:
        query += " AND Game.luck_rating = %s"
        params.append(luck_rating)
    if interaction_rating is not None:
        query += " AND Game.interaction_rating = %s"
        params.append(interaction_rating)
    if max_avg_duration is not None:
        query += " AND Game.avg_duration <= %s"
        params.append(max_avg_duration)
    if available_only:
        query += """
            AND Game.id IN (
                SELECT GameCopy.game_id
                FROM GameCopy
                WHERE GameCopy.store_id = %s
                AND GameCopy.is_available = TRUE
                GROUP BY GameCopy.game_id
            )
        """
        params.append(store_id)
    if search is not None:
        query += " AND (Game.name ILIKE %s OR Game.description ILIKE %s)"
        params.extend([f"%{search}%", f"%{search}%"])

    query += " ORDER BY Game.name"
    return get_db().execute(query, params).fetchall()


def get_game_detail(game_id):
    return get_db().execute("SELECT * FROM Game WHERE id = %s", (game_id,)).fetchone()


def update_game_image_url(game_id, url):
    db = get_db()
    db.execute("UPDATE Game SET image_url = %s WHERE id = %s", (url, game_id))
    db.commit()


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
    games = db.execute("SELECT * FROM Game").fetchall()
    db.execute("DELETE FROM GameSimilarity")
    for game in games:
        for other in games:
            if game["id"] != other["id"]:
                db.execute(
                    "INSERT INTO GameSimilarity (id1, id2, score) VALUES (%s, %s, %s)",
                    (game["id"], other["id"], _similarity_score(game, other)),
                )
    db.commit()


def get_similar_games(game_id, store_id, limit=3):
    return (
        get_db()
        .execute(
            """
            SELECT DISTINCT Game.*, GameSimilarity.score AS similarity_score
            FROM GameSimilarity
            JOIN Game ON (GameSimilarity.id2 = Game.id)
            JOIN GameCopy ON (Game.id = GameCopy.game_id AND GameCopy.store_id = %s)
            WHERE GameSimilarity.id1 = %s
            ORDER BY GameSimilarity.score DESC, Game.name
            LIMIT %s
            """,
            (store_id, game_id, limit),
        )
        .fetchall()
    )


def get_store_genres(store_id):
    return get_db().execute(
        """
        SELECT DISTINCT Game.genre
        FROM Game
        JOIN GameCopy ON (Game.id = GameCopy.game_id AND GameCopy.store_id = %s)
        WHERE Game.genre IS NOT NULL
        ORDER BY Game.genre
        """,
        (store_id,),
    ).fetchall()


def get_game_copies_with_condition(game_id, store_id):
    """Return all GameCopy rows for a game at a store (includes condition column)."""
    return (
        get_db()
        .execute(
            "SELECT * FROM GameCopy WHERE game_id = %s AND store_id = %s",
            (game_id, store_id),
        )
        .fetchall()
    )


def rate_game(user_id, game_id, rating, comment=None):
    """Insert or update a rating, then recompute avg_rating on the Game row."""
    db = get_db()
    db.execute(
        "INSERT INTO GameRating (user_id, game_id, rating, comment) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (user_id, game_id) DO UPDATE SET rating = EXCLUDED.rating, comment = EXCLUDED.comment",
        (user_id, game_id, rating, comment),
    )
    db.execute(
        "UPDATE Game SET avg_rating = (SELECT AVG(rating) FROM GameRating WHERE game_id = %s) WHERE id = %s",
        (game_id, game_id),
    )
    db.commit()


def get_user_rating(user_id, game_id):
    """Return the GameRating row for this user/game pair, or None."""
    return (
        get_db()
        .execute(
            "SELECT * FROM GameRating WHERE user_id = %s AND game_id = %s",
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
            SELECT GameRating.*, "User".username
            FROM GameRating
            JOIN "User" ON (GameRating.user_id = "User".id)
            WHERE GameRating.game_id = %s
            ORDER BY "User".username
            """,
            (game_id,),
        )
        .fetchall()
    )
