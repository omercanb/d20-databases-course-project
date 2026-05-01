"""Tests for the game library feature (db functions and routes)."""

import pytest

from d20.db import get_db
from d20.db.game import (
    get_available_games_during,
    get_game_copies_with_condition,
    get_game_detail,
    get_games_filtered,
    get_store_genres,
    get_unavailable_games_during,
    get_user_rating,
    rate_game,
)
from d20.db.session import create_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_store(db, name="Test Store", username="storeuser", password="x"):
    db.execute(
        "insert into Store (username, password, name) values (?, ?, ?)",
        (username, password, name),
    )
    db.commit()
    return db.execute("select id from Store where name = ?", (name,)).fetchone()["id"]


def _insert_game(
    db,
    name="Chess",
    symbol="CH",
    genre="Strategy",
    min_players=2,
    max_players=2,
    complexity_rating=3.0,
    avg_duration=60,
    description="Classic chess",
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


# ---------------------------------------------------------------------------
# DB function tests – get_games_filtered
# ---------------------------------------------------------------------------

class TestGetGamesFiltered:
    """Tests for get_games_filtered."""

    def _setup(self, app):
        """Return (store_id, game1_id, game2_id) after inserting minimal data."""
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db)

            game1_id = _insert_game(
                db,
                name="Chess",
                symbol="CH",
                genre="Strategy",
                min_players=2,
                max_players=2,
                complexity_rating=3.0,
                avg_duration=60,
            )
            game2_id = _insert_game(
                db,
                name="Catan",
                symbol="CA",
                genre="Euro",
                min_players=3,
                max_players=4,
                complexity_rating=2.0,
                avg_duration=90,
            )
            _insert_game_copy(db, game1_id, store_id, copy_num=1)
            _insert_game_copy(db, game2_id, store_id, copy_num=1)
            return store_id, game1_id, game2_id

    def test_no_filters_returns_all_store_games(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id)
        names = [g["name"] for g in games]
        assert "Chess" in names
        assert "Catan" in names

    def test_genre_filter(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id, genre="Strategy")
        assert len(games) == 1
        assert games[0]["name"] == "Chess"

    def test_genre_filter_no_match(self, app):
        store_id, _, _ = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id, genre="Trivia")
        assert games == []

    def test_min_players_filter(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            # min_players >= 3 should exclude Chess (min=2) and include Catan (min=3)
            games = get_games_filtered(store_id, min_players=3)
        names = [g["name"] for g in games]
        assert "Chess" not in names
        assert "Catan" in names

    def test_max_players_filter(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            # max_players <= 2 should include only Chess
            games = get_games_filtered(store_id, max_players=2)
        names = [g["name"] for g in games]
        assert "Chess" in names
        assert "Catan" not in names

    def test_complexity_rating_filter(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id, complexity_rating=2.0)
        assert len(games) == 1
        assert games[0]["name"] == "Catan"

    def test_max_avg_duration_filter(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            # avg_duration <= 60 should include only Chess (60), not Catan (90)
            games = get_games_filtered(store_id, max_avg_duration=60)
        names = [g["name"] for g in games]
        assert "Chess" in names
        assert "Catan" not in names

    def test_available_only_filter_includes_all_when_no_sessions(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id, available_only=True)
        names = [g["name"] for g in games]
        assert "Chess" in names
        assert "Catan" in names

    def test_available_only_filter_excludes_unusable_copies(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db)
            game_id = _insert_game(db, name="Broken Game", symbol="BG")
            _insert_game_copy(db, game_id, store_id, condition="damaged")
            games = get_games_filtered(store_id, available_only=True)
        assert games == []

    def test_combined_filters(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(
                store_id,
                genre="Strategy",
                max_players=4,
                complexity_rating=3.0,
            )
        assert len(games) == 1
        assert games[0]["name"] == "Chess"

    def test_does_not_return_games_from_other_stores(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            db = get_db()
            other_store_id = _insert_store(db, name="Other Store", username="other_store")
            games = get_games_filtered(other_store_id)
        assert games == []

    def test_results_ordered_by_name(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id)
        names = [g["name"] for g in games]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# DB function tests – get_store_genres
# ---------------------------------------------------------------------------

class TestGetStoreGenres:
    def test_returns_genres_of_games_at_store(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db)
            game1_id = _insert_game(db, name="G1", symbol="G1", genre="Strategy")
            game2_id = _insert_game(db, name="G2", symbol="G2", genre="Euro")
            _insert_game_copy(db, game1_id, store_id, copy_num=1)
            _insert_game_copy(db, game2_id, store_id, copy_num=1)
            genres = get_store_genres(store_id)
        genre_values = [r["genre"] for r in genres]
        assert "Strategy" in genre_values
        assert "Euro" in genre_values

    def test_does_not_return_genres_from_other_stores(self, app):
        with app.app_context():
            db = get_db()
            store1_id = _insert_store(db, name="Store 1", username="s1")
            store2_id = _insert_store(db, name="Store 2", username="s2")
            game_id = _insert_game(db, name="OnlyHere", symbol="OH", genre="Trivia")
            _insert_game_copy(db, game_id, store2_id, copy_num=1)
            genres = get_store_genres(store1_id)
        assert genres == []

    def test_genres_are_distinct(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db)
            game1_id = _insert_game(db, name="Dup1", symbol="D1", genre="Strategy")
            game2_id = _insert_game(db, name="Dup2", symbol="D2", genre="Strategy")
            _insert_game_copy(db, game1_id, store_id, copy_num=1)
            _insert_game_copy(db, game2_id, store_id, copy_num=1)
            genres = get_store_genres(store_id)
        assert len(genres) == 1
        assert genres[0]["genre"] == "Strategy"

    def test_excludes_null_genre(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db)
            game_id = _insert_game(db, name="NoGenre", symbol="NG", genre=None)
            # Override the helper which passes genre as positional arg – insert manually
            db.execute(
                "insert into Game (name, symbol) values ('Bare', 'BR')"
            )
            db.commit()
            bare_id = db.execute("select id from Game where name = 'Bare'").fetchone()["id"]
            _insert_game_copy(db, bare_id, store_id, copy_num=1)
            genres = get_store_genres(store_id)
        # Only non-null genres should appear; 'Bare' has NULL genre
        for row in genres:
            assert row["genre"] is not None


# ---------------------------------------------------------------------------
# DB function tests – get_game_detail
# ---------------------------------------------------------------------------

class TestGetGameDetail:
    def test_returns_game_row_for_valid_id(self, app):
        with app.app_context():
            # Game with id=1 is inserted via data.sql ("Test Game")
            game = get_game_detail(1)
        assert game is not None
        assert game["name"] == "Test Game"

    def test_returns_none_for_missing_id(self, app):
        with app.app_context():
            game = get_game_detail(99999)
        assert game is None


# ---------------------------------------------------------------------------
# DB function tests – rate_game + get_user_rating
# ---------------------------------------------------------------------------

class TestRateGame:
    def _setup(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db)
            game_id = _insert_game(db, name="Ratable", symbol="RA")
            _insert_game_copy(db, game_id, store_id)
            # user id 1 exists from data.sql
            return game_id

    def test_rating_is_saved(self, app):
        game_id = self._setup(app)
        with app.app_context():
            rate_game(user_id=1, game_id=game_id, rating=4)
            row = get_user_rating(user_id=1, game_id=game_id)
        assert row is not None
        assert row["rating"] == 4

    def test_avg_rating_updated_on_game(self, app):
        game_id = self._setup(app)
        with app.app_context():
            # user 1 rates 4, user 2 rates 2 → avg = 3.0
            rate_game(user_id=1, game_id=game_id, rating=4)
            rate_game(user_id=2, game_id=game_id, rating=2)
            game = get_game_detail(game_id)
        assert game["avg_rating"] == pytest.approx(3.0)

    def test_re_rating_updates_existing(self, app):
        game_id = self._setup(app)
        with app.app_context():
            rate_game(user_id=1, game_id=game_id, rating=3)
            rate_game(user_id=1, game_id=game_id, rating=5)
            row = get_user_rating(user_id=1, game_id=game_id)
        assert row["rating"] == 5

    def test_get_user_rating_returns_none_when_not_rated(self, app):
        game_id = self._setup(app)
        with app.app_context():
            row = get_user_rating(user_id=1, game_id=game_id)
        assert row is None


# ---------------------------------------------------------------------------
# Route tests – GET /store/<id>/games
# ---------------------------------------------------------------------------

class TestGameLibraryRoute:
    def _setup_store_and_game(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db)
            game_id = _insert_game(
                db, name="Dominion", symbol="DO", genre="Deck-Building",
                min_players=2, max_players=4, complexity_rating=2.0, avg_duration=30,
            )
            _insert_game_copy(db, game_id, store_id)
            return store_id, game_id

    def test_200_with_no_filters(self, client, app):
        store_id, _ = self._setup_store_and_game(app)
        response = client.get(f"/store/{store_id}/games")
        assert response.status_code == 200

    def test_genre_filter_param_returns_200(self, client, app):
        store_id, _ = self._setup_store_and_game(app)
        response = client.get(f"/store/{store_id}/games?genre=Deck-Building")
        assert response.status_code == 200
        assert b"Dominion" in response.data

    def test_genre_filter_no_match_returns_empty(self, client, app):
        store_id, _ = self._setup_store_and_game(app)
        response = client.get(f"/store/{store_id}/games?genre=Trivia")
        assert response.status_code == 200
        assert b"Dominion" not in response.data

    def test_complexity_rating_filter_via_route(self, client, app):
        store_id, _ = self._setup_store_and_game(app)
        response = client.get(f"/store/{store_id}/games?complexity_rating=2.0")
        assert response.status_code == 200
        assert b"Dominion" in response.data

    def test_invalid_min_players_flashes_error(self, client, app):
        store_id, _ = self._setup_store_and_game(app)
        response = client.get(f"/store/{store_id}/games?min_players=0")
        assert response.status_code == 200
        assert b"Minimum players" in response.data


# ---------------------------------------------------------------------------
# Route tests – GET /store/<id>/game/<game_id>
# ---------------------------------------------------------------------------

class TestGameDetailRoute:
    def _setup(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db)
            game_id = _insert_game(db, name="Pandemic", symbol="PA", genre="Coop")
            _insert_game_copy(db, game_id, store_id, condition="good")
            return store_id, game_id

    def test_200_for_valid_game(self, client, app):
        store_id, game_id = self._setup(app)
        response = client.get(f"/store/{store_id}/game/{game_id}")
        assert response.status_code == 200
        assert b"Pandemic" in response.data

    def test_404_for_missing_game_id(self, client, app):
        store_id, _ = self._setup(app)
        response = client.get(f"/store/{store_id}/game/99999")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Route tests – POST /store/<id>/game/<game_id>/rate
# ---------------------------------------------------------------------------

class TestRateGameRoute:
    def _setup(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db)
            game_id = _insert_game(db, name="Terraforming", symbol="TF")
            _insert_game_copy(db, game_id, store_id)
            return store_id, game_id

    def test_unauthenticated_redirects_to_login(self, client, app):
        store_id, game_id = self._setup(app)
        response = client.post(
            f"/store/{store_id}/game/{game_id}/rate", data={"rating": "4"}
        )
        assert response.status_code == 302
        assert "/auth/login" in response.headers["Location"]

    def test_valid_rating_succeeds(self, client, auth, app):
        store_id, game_id = self._setup(app)
        auth.login()
        response = client.post(
            f"/store/{store_id}/game/{game_id}/rate",
            data={"rating": "4"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Rating submitted" in response.data

    def test_rating_zero_flashes_error(self, client, auth, app):
        store_id, game_id = self._setup(app)
        auth.login()
        response = client.post(
            f"/store/{store_id}/game/{game_id}/rate",
            data={"rating": "0"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Rating must be between 1 and 5" in response.data

    def test_rating_six_flashes_error(self, client, auth, app):
        store_id, game_id = self._setup(app)
        auth.login()
        response = client.post(
            f"/store/{store_id}/game/{game_id}/rate",
            data={"rating": "6"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Rating must be between 1 and 5" in response.data

    def test_missing_rating_flashes_error(self, client, auth, app):
        store_id, game_id = self._setup(app)
        auth.login()
        response = client.post(
            f"/store/{store_id}/game/{game_id}/rate",
            data={},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Rating must be between 1 and 5" in response.data

    def test_rate_game_404_for_missing_game(self, client, auth, app):
        store_id, _ = self._setup(app)
        auth.login()
        response = client.post(
            f"/store/{store_id}/game/99999/rate", data={"rating": "3"}
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# DB function tests – get_games_filtered search parameter
# ---------------------------------------------------------------------------

class TestGetGamesFilteredSearch:
    """Tests for the search= parameter of get_games_filtered."""

    def _setup(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db, name="Search Store", username="searchstore")
            game1_id = _insert_game(
                db,
                name="Dragon Quest",
                symbol="DQ",
                genre="RPG",
                min_players=1,
                max_players=4,
                complexity_rating=3.0,
                avg_duration=90,
                description="Slay the dragon and save the kingdom",
            )
            game2_id = _insert_game(
                db,
                name="Chess",
                symbol="CS2",
                genre="Strategy",
                min_players=2,
                max_players=2,
                complexity_rating=4.0,
                avg_duration=60,
                description="Classic board game of kings",
            )
            _insert_game_copy(db, game1_id, store_id, copy_num=1)
            _insert_game_copy(db, game2_id, store_id, copy_num=1)
            return store_id, game1_id, game2_id

    def test_search_by_name_returns_match(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id, search="Dragon")
        assert len(games) == 1
        assert games[0]["name"] == "Dragon Quest"

    def test_search_by_description_returns_match(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id, search="kingdom")
        assert len(games) == 1
        assert games[0]["name"] == "Dragon Quest"

    def test_search_none_returns_all(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id, search=None)
        names = [g["name"] for g in games]
        assert "Dragon Quest" in names
        assert "Chess" in names

    def test_search_empty_string_treated_as_none_by_route(self, app, client):
        """The route converts empty string to None, so all games are returned."""
        store_id, game1_id, game2_id = self._setup(app)
        response = client.get(f"/store/{store_id}/games?search=")
        assert response.status_code == 200
        assert b"Dragon Quest" in response.data
        assert b"Chess" in response.data

    def test_search_no_match_returns_empty(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id, search="xyzzy_no_match")
        assert games == []

    def test_search_is_case_insensitive(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            games = get_games_filtered(store_id, search="dragon")
        assert len(games) == 1
        assert games[0]["name"] == "Dragon Quest"

    def test_search_route_returns_matching_game(self, app, client):
        store_id, game1_id, game2_id = self._setup(app)
        response = client.get(f"/store/{store_id}/games?search=Chess")
        assert response.status_code == 200
        assert b"Chess" in response.data
        assert b"Dragon Quest" not in response.data

    def test_search_combined_with_genre_filter(self, app):
        store_id, game1_id, game2_id = self._setup(app)
        with app.app_context():
            # search matches both but genre narrows to one
            games = get_games_filtered(store_id, search="game", genre="Strategy")
        assert len(games) == 1
        assert games[0]["name"] == "Chess"


# ---------------------------------------------------------------------------
# DB function tests – get_available_games_during / get_unavailable_games_during
# return Game.* columns
# ---------------------------------------------------------------------------

class TestAvailableGamesDuringColumns:
    """Verify that get_available_games_during returns full Game columns."""

    def _setup(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db, name="ColStore", username="colstore")
            game_id = _insert_game(
                db,
                name="Wingspan",
                symbol="WS",
                genre="Nature",
                min_players=1,
                max_players=5,
                complexity_rating=2.0,
                avg_duration=70,
                description="Bird card game",
            )
            _insert_game_copy(db, game_id, store_id, copy_num=1)
            return store_id, game_id

    def test_available_games_includes_genre(self, app):
        store_id, game_id = self._setup(app)
        with app.app_context():
            games = get_available_games_during(store_id, "2099-01-01", 9, 20)
        assert len(games) == 1
        assert games[0]["genre"] == "Nature"

    def test_available_games_includes_complexity_rating(self, app):
        store_id, game_id = self._setup(app)
        with app.app_context():
            games = get_available_games_during(store_id, "2099-01-01", 9, 20)
        assert games[0]["complexity_rating"] == pytest.approx(2.0)

    def test_available_games_includes_min_max_players(self, app):
        store_id, game_id = self._setup(app)
        with app.app_context():
            games = get_available_games_during(store_id, "2099-01-01", 9, 20)
        assert games[0]["min_players"] == 1
        assert games[0]["max_players"] == 5

    def test_available_games_includes_avg_duration(self, app):
        store_id, game_id = self._setup(app)
        with app.app_context():
            games = get_available_games_during(store_id, "2099-01-01", 9, 20)
        assert games[0]["avg_duration"] == 70

    def test_available_games_still_has_copy_aggregates(self, app):
        store_id, game_id = self._setup(app)
        with app.app_context():
            games = get_available_games_during(store_id, "2099-01-01", 9, 20)
        assert games[0]["total_copies"] == 1
        assert games[0]["available_copies"] == 1

    def test_damaged_copy_is_not_available_during(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db, name="DamagedStore", username="damagedstore")
            game_id = _insert_game(db, name="Damaged Game", symbol="DG")
            _insert_game_copy(db, game_id, store_id, condition="damaged")
            available = get_available_games_during(store_id, "2099-01-01", 9, 20)
            unavailable = get_unavailable_games_during(store_id, "2099-01-01", 9, 20)
        assert available == []
        assert unavailable[0]["name"] == "Damaged Game"


class TestCreateSessionAvailability:
    def test_occupied_table_raises_error(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db, name="OccupiedStore", username="occupiedstore")
            game_id = _insert_game(db, name="Table Check Game", symbol="TCG")
            _insert_game_copy(db, game_id, store_id)
            db.execute(
                "insert into 'Table' (store_id, table_num, capacity) values (?, 1, 4)",
                (store_id,),
            )
            db.execute(
                """
                insert into Session (user_id, store_id, table_num, day, start_time, end_time)
                values (1, ?, 1, '2099-01-01', 9, 20)
                """,
                (store_id,),
            )
            db.commit()

            with pytest.raises(
                ValueError,
                match="The table you selected is occupied at the selected time slot.",
            ):
                create_session(1, store_id, 1, "2099-01-01", 10, 12, [game_id])

    def test_no_available_game_copy_raises_error(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db, name="NoCopyStore", username="nocopystore")
            game_id = _insert_game(db, name="No Copy Game", symbol="NCG")
            _insert_game_copy(db, game_id, store_id, condition="missing_pieces")
            db.execute(
                "insert into 'Table' (store_id, table_num, capacity) values (?, 1, 4)",
                (store_id,),
            )
            db.commit()

            with pytest.raises(
                ValueError,
                match="The game you selected has no available copies at the selected time slot.",
            ):
                create_session(1, store_id, 1, "2099-01-01", 10, 12, [game_id])

    def test_uses_available_copy_not_first_copy(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db, name="BookingStore", username="bookingstore")
            game_id = _insert_game(db, name="Reservable", symbol="RV")
            _insert_game_copy(db, game_id, store_id, copy_num=1)
            _insert_game_copy(db, game_id, store_id, copy_num=2)
            db.execute(
                "insert into 'Table' (store_id, table_num, capacity) values (?, 1, 4)",
                (store_id,),
            )
            db.execute(
                "insert into 'Table' (store_id, table_num, capacity) values (?, 2, 4)",
                (store_id,),
            )
            db.execute(
                """
                insert into Session (user_id, store_id, table_num, day, start_time, end_time)
                values (1, ?, 1, '2099-01-01', 9, 20)
                """,
                (store_id,),
            )
            session_id = db.execute("select last_insert_rowid()").fetchone()[0]
            db.execute(
                """
                insert into SessionGameCopy (session_id, game_id, store_id, copy_num)
                values (?, ?, ?, 1)
                """,
                (session_id, game_id, store_id),
            )
            db.commit()

            new_session_id = create_session(
                1, store_id, 2, "2099-01-01", 10, 12, [game_id]
            )
            copy = db.execute(
                "select copy_num from SessionGameCopy where session_id = ?",
                (new_session_id,),
            ).fetchone()

        assert copy["copy_num"] == 2


# ---------------------------------------------------------------------------
# Route tests – select_games page shows game detail fields
# ---------------------------------------------------------------------------

class TestSelectGamesRoute:
    """Verify that the select_games route renders genre/complexity rating details."""

    def _setup(self, app):
        with app.app_context():
            db = get_db()
            store_id = _insert_store(db, name="SGStore", username="sgstore")
            game_id = _insert_game(
                db,
                name="Agricola",
                symbol="AG",
                genre="Farming",
                min_players=1,
                max_players=5,
                complexity_rating=4.0,
                avg_duration=120,
                description="Farming strategy game",
            )
            _insert_game_copy(db, game_id, store_id, copy_num=1)
            # Insert a table
            db.execute(
                "insert into 'Table' (store_id, table_num, capacity) values (?, 1, 6)",
                (store_id,),
            )
            db.commit()
            return store_id, game_id

    def _login(self, client):
        client.post("/auth/login", data={"username": "test", "password": "test"})

    def test_select_games_shows_genre(self, client, app):
        store_id, game_id = self._setup(app)
        self._login(client)
        response = client.get(
            f"/store/{store_id}/table/1/select-games?day=2099-01-01&start_time=9&end_time=20"
        )
        assert response.status_code == 200
        assert b"Farming" in response.data

    def test_select_games_shows_complexity_rating(self, client, app):
        store_id, game_id = self._setup(app)
        self._login(client)
        response = client.get(
            f"/store/{store_id}/table/1/select-games?day=2099-01-01&start_time=9&end_time=20"
        )
        assert response.status_code == 200
        assert b"Complexity" in response.data

    def test_select_games_shows_player_range(self, client, app):
        store_id, game_id = self._setup(app)
        self._login(client)
        response = client.get(
            f"/store/{store_id}/table/1/select-games?day=2099-01-01&start_time=9&end_time=20"
        )
        assert response.status_code == 200
        assert b"players" in response.data

    def test_select_games_shows_play_time(self, client, app):
        store_id, game_id = self._setup(app)
        self._login(client)
        response = client.get(
            f"/store/{store_id}/table/1/select-games?day=2099-01-01&start_time=9&end_time=20"
        )
        assert response.status_code == 200
        assert b"120 min" in response.data
