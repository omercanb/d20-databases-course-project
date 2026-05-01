"""Tests for text search in the game library and game details on the booking page."""

import pytest

from d20.db import get_db
from d20.db.game import (
    get_available_games_during,
    get_games_filtered,
    get_unavailable_games_during,
)


# ---------------------------------------------------------------------------
# Helpers – minimal data insertion
# ---------------------------------------------------------------------------

def _insert_store(db, name="Search Store", username="searchstore_sb"):
    db.execute(
        "insert into Store (username, password, name) values (?, 'x', ?)",
        (username, name),
    )
    db.commit()
    return db.execute("select id from Store where name = ?", (name,)).fetchone()["id"]


def _insert_game(
    db,
    name,
    symbol,
    genre="Strategy",
    min_players=2,
    max_players=4,
    complexity_rating=3.0,
    avg_duration=60,
    description="A test game",
):
    db.execute(
        """
        insert into Game (name, symbol, genre, min_players, max_players,
                          complexity_rating, avg_duration, description)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (name, symbol, genre, min_players, max_players, complexity_rating, avg_duration, description),
    )
    db.commit()
    return db.execute("select id from Game where name = ?", (name,)).fetchone()["id"]


def _insert_game_copy(db, game_id, store_id, copy_num=1, condition="good"):
    db.execute(
        "insert into GameCopy (game_id, store_id, copy_num, condition) values (?, ?, ?, ?)",
        (game_id, store_id, copy_num, condition),
    )
    db.commit()


def _insert_table(db, store_id, table_num=1, capacity=4):
    db.execute(
        "insert into 'Table' (store_id, table_num, capacity) values (?, ?, ?)",
        (store_id, table_num, capacity),
    )
    db.commit()


# ---------------------------------------------------------------------------
# Feature 1: Text search – get_games_filtered(search=...)
# ---------------------------------------------------------------------------

class TestGetGamesFilteredSearch:
    """DB-level tests for the search= parameter added to get_games_filtered."""

    def _setup(self, app):
        """Insert a store with two games that have distinct names and descriptions."""
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db, name="SB Search Store", username="sb_searchstore")
            catan_id = _insert_game(
                db,
                name="Catan",
                symbol="SB_CT",
                genre="Euro",
                min_players=3,
                max_players=4,
                complexity_rating=2.0,
                avg_duration=90,
                description="Settle and trade on an island",
            )
            chess_id = _insert_game(
                db,
                name="Chess Classic",
                symbol="SB_CC",
                genre="Abstract",
                min_players=2,
                max_players=2,
                complexity_rating=5.0,
                avg_duration=60,
                description="Battle of wits with pieces on a board",
            )
            _insert_game_copy(db, catan_id, store_id)
            _insert_game_copy(db, chess_id, store_id)
            return store_id, catan_id, chess_id

    def test_search_by_name_catan_returns_only_catan(self, app):
        """search='Catan' must return exactly the Catan game and nothing else."""
        store_id, catan_id, chess_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id, search="Catan")
        assert len(games) == 1
        assert games[0]["name"] == "Catan"

    def test_search_by_description_returns_match(self, app):
        """search term found only in description should still surface the game."""
        store_id, catan_id, chess_id = self._setup(app)
        with app.app_context():
            # 'island' is only in Catan's description
            games = get_games_filtered(store_id, search="island")
        assert len(games) == 1
        assert games[0]["name"] == "Catan"

    def test_search_with_no_match_returns_empty_list(self, app):
        """A search term that matches nothing should produce an empty result."""
        store_id, catan_id, chess_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id, search="xyzzy_no_match_ever")
        assert games == []

    def test_search_none_does_not_filter_by_text(self, app):
        """Passing search=None (the default) should return all store games."""
        store_id, catan_id, chess_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id, search=None)
        names = {g["name"] for g in games}
        assert "Catan" in names
        assert "Chess Classic" in names

    def test_search_is_case_insensitive(self, app):
        """SQLite LIKE is case-insensitive for ASCII; lowercase search must match."""
        store_id, catan_id, chess_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id, search="catan")
        assert len(games) == 1
        assert games[0]["name"] == "Catan"

    def test_search_partial_match_works(self, app):
        """A sub-string of the name should still match via LIKE %search%."""
        store_id, catan_id, chess_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id, search="Clas")  # hits "Chess Classic"
        assert len(games) == 1
        assert games[0]["name"] == "Chess Classic"


# ---------------------------------------------------------------------------
# Feature 1: Text search – store route (?search= query param)
# ---------------------------------------------------------------------------

class TestGameLibraryRouteSearch:
    """Route-level tests for GET /store/<id>?search=..."""

    def _setup(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db, name="Route Search Store", username="rt_searchstore")
            game1_id = _insert_game(
                db,
                name="Pandemic Legacy",
                symbol="PL_SB",
                genre="Coop",
                description="Save the world from disease",
            )
            game2_id = _insert_game(
                db,
                name="Ticket to Ride",
                symbol="TR_SB",
                genre="Family",
                description="Build train routes across continents",
            )
            _insert_game_copy(db, game1_id, store_id)
            _insert_game_copy(db, game2_id, store_id)
            return store_id, game1_id, game2_id

    def test_search_param_returns_200(self, client, app):
        store_id, _, _ = self._setup(app)
        response = client.get(f"/store/{store_id}?search=Pandemic")
        assert response.status_code == 200

    def test_search_param_filters_results_to_matching_game(self, client, app):
        store_id, _, _ = self._setup(app)
        response = client.get(f"/store/{store_id}?search=Pandemic")
        assert b"Pandemic Legacy" in response.data
        assert b"Ticket to Ride" not in response.data

    def test_search_param_no_match_shows_neither_game(self, client, app):
        store_id, _, _ = self._setup(app)
        response = client.get(f"/store/{store_id}?search=xyzzy_no_match")
        assert response.status_code == 200
        assert b"Pandemic Legacy" not in response.data
        assert b"Ticket to Ride" not in response.data

    def test_empty_search_param_treated_as_no_filter(self, client, app):
        """Route converts empty string to None, so all games are returned."""
        store_id, _, _ = self._setup(app)
        response = client.get(f"/store/{store_id}?search=")
        assert response.status_code == 200
        assert b"Pandemic Legacy" in response.data
        assert b"Ticket to Ride" in response.data

    def test_search_by_description_keyword_via_route(self, client, app):
        store_id, _, _ = self._setup(app)
        # 'continents' appears only in Ticket to Ride's description
        response = client.get(f"/store/{store_id}?search=continents")
        assert response.status_code == 200
        assert b"Ticket to Ride" in response.data
        assert b"Pandemic Legacy" not in response.data


# ---------------------------------------------------------------------------
# Feature 2: Booking details – get_available_games_during returns Game.*
# ---------------------------------------------------------------------------

class TestGetAvailableGamesDuringColumns:
    """Verify that get_available_games_during returns full Game.* columns."""

    def _setup(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db, name="Avail Detail Store", username="avail_det_store")
            game_id = _insert_game(
                db,
                name="Wingspan",
                symbol="WN_SB",
                genre="Nature",
                min_players=1,
                max_players=5,
                complexity_rating=2.0,
                avg_duration=70,
                description="Attract birds to your wildlife preserve",
            )
            _insert_game_copy(db, game_id, store_id)
            return store_id, game_id

    def test_returns_genre_column(self, app):
        store_id, _ = self._setup(app)
        with app.app_context():
            games = get_available_games_during(store_id, "2099-01-01", 9, 20)
        assert len(games) == 1
        assert games[0]["genre"] == "Nature"

    def test_returns_complexity_rating_column(self, app):
        store_id, _ = self._setup(app)
        with app.app_context():
            games = get_available_games_during(store_id, "2099-01-01", 9, 20)
        assert games[0]["complexity_rating"] == pytest.approx(2.0)

    def test_returns_min_players_column(self, app):
        store_id, _ = self._setup(app)
        with app.app_context():
            games = get_available_games_during(store_id, "2099-01-01", 9, 20)
        assert games[0]["min_players"] == 1

    def test_returns_max_players_column(self, app):
        store_id, _ = self._setup(app)
        with app.app_context():
            games = get_available_games_during(store_id, "2099-01-01", 9, 20)
        assert games[0]["max_players"] == 5

    def test_returns_avg_duration_column(self, app):
        store_id, _ = self._setup(app)
        with app.app_context():
            games = get_available_games_during(store_id, "2099-01-01", 9, 20)
        assert games[0]["avg_duration"] == 70


# ---------------------------------------------------------------------------
# Feature 2: Booking details – get_unavailable_games_during returns Game.*
# ---------------------------------------------------------------------------

class TestGetUnavailableGamesDuringColumns:
    """Verify that get_unavailable_games_during returns full Game.* columns."""

    def _setup(self, app):
        """Insert a game, a session that fully books its only copy, then verify unavailability."""
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db, name="Unavail Detail Store", username="unavail_det_store")
            game_id = _insert_game(
                db,
                name="Agricola",
                symbol="AG_SB",
                genre="Farming",
                min_players=1,
                max_players=5,
                complexity_rating=4.0,
                avg_duration=120,
                description="Farming strategy game",
            )
            _insert_game_copy(db, game_id, store_id, copy_num=1)
            _insert_table(db, store_id, table_num=1)

            # Book the single copy during our test window so it becomes unavailable
            db.execute(
                "insert into User (username, password) values ('unavail_user_sb', 'x')"
            )
            db.commit()
            user_id = db.execute(
                "select id from User where username = 'unavail_user_sb'"
            ).fetchone()["id"]
            db.execute(
                """
                insert into Session (user_id, store_id, table_num, day, start_time, end_time)
                values (?, ?, 1, '2099-06-01', 9, 20)
                """,
                (user_id, store_id),
            )
            db.commit()
            session_id = db.execute(
                "select id from Session where user_id = ? and store_id = ?",
                (user_id, store_id),
            ).fetchone()["id"]
            db.execute(
                """
                insert into SessionGameCopy (session_id, game_id, store_id, copy_num)
                values (?, ?, ?, 1)
                """,
                (session_id, game_id, store_id),
            )
            db.commit()
            return store_id, game_id

    def test_returns_genre_column(self, app):
        store_id, _ = self._setup(app)
        with app.app_context():
            games = get_unavailable_games_during(store_id, "2099-06-01", 9, 20)
        assert len(games) == 1
        assert games[0]["genre"] == "Farming"

    def test_returns_complexity_rating_column(self, app):
        store_id, _ = self._setup(app)
        with app.app_context():
            games = get_unavailable_games_during(store_id, "2099-06-01", 9, 20)
        assert games[0]["complexity_rating"] == pytest.approx(4.0)

    def test_returns_min_players_column(self, app):
        store_id, _ = self._setup(app)
        with app.app_context():
            games = get_unavailable_games_during(store_id, "2099-06-01", 9, 20)
        assert games[0]["min_players"] == 1

    def test_returns_max_players_column(self, app):
        store_id, _ = self._setup(app)
        with app.app_context():
            games = get_unavailable_games_during(store_id, "2099-06-01", 9, 20)
        assert games[0]["max_players"] == 5

    def test_returns_avg_duration_column(self, app):
        store_id, _ = self._setup(app)
        with app.app_context():
            games = get_unavailable_games_during(store_id, "2099-06-01", 9, 20)
        assert games[0]["avg_duration"] == 120


# ---------------------------------------------------------------------------
# Feature 2: Booking details – select_games route renders detail fields
# ---------------------------------------------------------------------------

class TestSelectGamesRouteDetails:
    """Route-level tests verifying game detail fields are rendered on the booking page."""

    def _setup(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db, name="SG Route Store", username="sg_route_store")
            game_id = _insert_game(
                db,
                name="Power Grid",
                symbol="PG_SB",
                genre="Economic",
                min_players=2,
                max_players=6,
                complexity_rating=4.0,
                avg_duration=150,
                description="Build your power network",
            )
            _insert_game_copy(db, game_id, store_id)
            _insert_table(db, store_id, table_num=1)
            return store_id, game_id

    def _login(self, client):
        client.post("/auth/login", data={"username": "test", "password": "test"})

    def test_select_games_route_returns_200(self, client, app):
        store_id, _ = self._setup(app)
        self._login(client)
        response = client.get(
            f"/store/{store_id}/table/1/select-games?day=2099-01-01&start_time=9&end_time=20"
        )
        assert response.status_code == 200

    def test_select_games_unauthenticated_redirects(self, client, app):
        store_id, _ = self._setup(app)
        response = client.get(
            f"/store/{store_id}/table/1/select-games?day=2099-01-01&start_time=9&end_time=20"
        )
        assert response.status_code == 302
        assert "/auth/login" in response.headers["Location"]

    def test_select_games_renders_genre(self, client, app):
        store_id, _ = self._setup(app)
        self._login(client)
        response = client.get(
            f"/store/{store_id}/table/1/select-games?day=2099-01-01&start_time=9&end_time=20"
        )
        assert b"Economic" in response.data

    def test_select_games_renders_complexity(self, client, app):
        store_id, _ = self._setup(app)
        self._login(client)
        response = client.get(
            f"/store/{store_id}/table/1/select-games?day=2099-01-01&start_time=9&end_time=20"
        )
        assert b"Complexity" in response.data

    def test_select_games_renders_player_count(self, client, app):
        store_id, _ = self._setup(app)
        self._login(client)
        response = client.get(
            f"/store/{store_id}/table/1/select-games?day=2099-01-01&start_time=9&end_time=20"
        )
        assert b"players" in response.data

    def test_select_games_renders_avg_duration(self, client, app):
        store_id, _ = self._setup(app)
        self._login(client)
        response = client.get(
            f"/store/{store_id}/table/1/select-games?day=2099-01-01&start_time=9&end_time=20"
        )
        assert b"150 min" in response.data
