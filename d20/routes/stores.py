import functools
from datetime import date

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from d20.db import get_db
from d20.db.game import (
    create_game_copy,
    delete_game_copy,
    get_available_games_during,
    get_available_games_with_counts,
    get_game_copies_with_condition,
    get_game_detail,
    get_game_ratings,
    get_games,
    get_games_filtered,
    get_similar_games,
    get_store_genres,
    get_unavailable_games_during,
    get_user_rating,
    rate_game,
)
from d20.db.session import (
    MAX_RESERVATIONS,
    create_session,
    delete_session,
    get_available_tables,
    get_reservation_count,
    get_session,
    get_session_games,
    get_unavailable_tables,
    get_upcoming_sessions_with_user_by_store,
)
from d20.db.stores import (
    create_table,
    delete_table,
    get_store_by_id,
    get_table,
    get_tables,
    update_table,
)

bp = Blueprint("stores", __name__)


@bp.before_app_request
def load_logged_in_store():
    store_id = session.get("store_id")

    if store_id is None:
        g.store = None
    else:
        g.store = get_store_by_id(store_id)


def store_login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.store is None:
            return redirect(url_for("auth.loginstore"))

        return view(**kwargs)

    return wrapped_view


@bp.route("/")
def stores():
    db = get_db()

    search = request.args.get("search", "")

    stores = db.execute(
        "select * from Store where name like ?", (f"%{search}%",)
    ).fetchall()

    return render_template("stores/stores.html", stores=stores, search=search)


@bp.route("/mystore")
@store_login_required
def my_store():
    store_id = g.store["id"]
    tables = get_tables(store_id)
    games = get_available_games_with_counts(store_id)
    all_games = get_games()
    today = str(date.today())
    upcoming_sessions_raw = get_upcoming_sessions_with_user_by_store(store_id, today)

    # Convert to dicts and attach games
    upcoming_sessions = []
    for sess in upcoming_sessions_raw:
        sess_dict = dict(sess)
        sess_dict["games"] = get_session_games(sess["id"])
        upcoming_sessions.append(sess_dict)

    return render_template(
        "stores/my_store.html",
        tables=tables,
        games=games,
        all_games=all_games,
        upcoming_sessions=upcoming_sessions,
    )


@bp.route("/mystore/table/add", methods=("POST",))
@store_login_required
def add_table():
    capacity = request.form.get("capacity", type=int)
    if capacity is None or capacity <= 0:
        flash("Capacity must be a positive number.")
        return redirect(url_for("stores.my_store"))

    try:
        create_table(g.store["id"], capacity)
        flash("Table added successfully.")
    except Exception as e:
        flash(f"Error adding table: {str(e)}")

    return redirect(url_for("stores.my_store"))


@bp.route("/mystore/table/<int:table_num>/update", methods=("POST",))
@store_login_required
def update_table_route(table_num):
    capacity = request.form.get("capacity", type=int)
    if capacity is None or capacity <= 0:
        flash("Capacity must be a positive number.")
        return redirect(url_for("stores.my_store"))

    try:
        update_table(g.store["id"], table_num, capacity)
        flash("Table updated successfully.")
    except Exception as e:
        flash(f"Error updating table: {str(e)}")

    return redirect(url_for("stores.my_store"))


@bp.route("/mystore/table/<int:table_num>/delete", methods=("POST",))
@store_login_required
def delete_table_route(table_num):
    try:
        delete_table(g.store["id"], table_num)
        flash("Table deleted successfully.")
    except Exception as e:
        flash(f"Error deleting table: {str(e)}")

    return redirect(url_for("stores.my_store"))


@bp.route("/mystore/game/add", methods=("POST",))
@store_login_required
def add_game_copy():
    game_id = request.form.get("game_id", type=int)
    if game_id is None:
        flash("Please select a game.")
        return redirect(url_for("stores.my_store"))

    try:
        create_game_copy(game_id, g.store["id"])
        flash("Game copy added successfully.")
    except Exception as e:
        flash(f"Error adding game copy: {str(e)}")

    return redirect(url_for("stores.my_store"))


@bp.route("/mystore/game/<int:game_id>/remove", methods=("POST",))
@store_login_required
def remove_game_copy(game_id):
    try:
        # Get the latest copy
        copy = (
            get_db()
            .execute(
                "select copy_num from GameCopy where game_id = ? and store_id = ? order by copy_num desc limit 1",
                (game_id, g.store["id"]),
            )
            .fetchone()
        )

        if not copy:
            flash("No copies of this game found.")
            return redirect(url_for("stores.my_store"))

        delete_game_copy(game_id, g.store["id"], copy["copy_num"])
        flash("Game copy removed successfully.")
    except Exception as e:
        flash(f"Error removing game copy: {str(e)}")

    return redirect(url_for("stores.my_store"))


@bp.route("/mystore/session/<int:session_id>/cancel", methods=("POST",))
@store_login_required
def cancel_store_session(session_id):
    sess = get_session(session_id)
    if not sess or sess["store_id"] != g.store["id"]:
        flash("Session not found.")
        return redirect(url_for("stores.my_store"))

    try:
        delete_session(session_id)
        flash("Session cancelled successfully.")
    except Exception as e:
        flash(f"Error cancelling session: {str(e)}")

    return redirect(url_for("stores.my_store"))


@bp.route("/store/<int:store_id>")
def store(store_id):
    store = get_store_by_id(store_id)
    tables = get_tables(store_id)
    games = get_available_games_with_counts(store_id)
    return render_template("stores/store.html", store=store, tables=tables, games=games)


@bp.route("/store/<int:store_id>/book")
def book_session(store_id):
    start_time = request.args.get("start_time")
    end_time = request.args.get("end_time")
    day = request.args.get("day")
    if not start_time:
        start_time = 9
        end_time = 20
        day = str(date.today())
    tables = get_available_tables(store_id, day, start_time, end_time)
    unvailable_tables = get_unavailable_tables(store_id, day, start_time, end_time)
    store = get_store_by_id(store_id)
    return render_template(
        "stores/book_session.html",
        store=store,
        tables=tables,
        unvailable_tables=unvailable_tables,
        day=day,
        today=str(date.today()),
        start_time=start_time,
        end_time=end_time,
    )


@bp.route("/store/<int:store_id>/table/<int:table_num>/select-games")
def select_games(store_id, table_num):
    if not g.user:
        return redirect(url_for("auth.login"))

    day = request.args.get("day", str(date.today()))
    start_time = request.args.get("start_time", 9, type=int)
    end_time = request.args.get("end_time", 20, type=int)
    search = request.args.get("search") or None
    genre = request.args.get("genre") or None
    min_players = request.args.get("min_players", type=int)
    max_players = request.args.get("max_players", type=int)
    max_avg_duration = request.args.get("max_avg_duration", type=int)
    user_rating = request.args.get("user_rating", type=int)
    complexity_rating = request.args.get("complexity_rating", type=int)
    strategy_rating = request.args.get("strategy_rating", type=int)
    luck_rating = request.args.get("luck_rating", type=int)
    interaction_rating = request.args.get("interaction_rating", type=int)

    store = get_store_by_id(store_id)
    table = get_table(store_id, table_num)
    available_games = get_available_games_during(store_id, day, start_time, end_time)
    unavailable_games = get_unavailable_games_during(
        store_id, day, start_time, end_time
    )
    genres = get_store_genres(store_id)

    def matches_filters(game):
        if search:
            text = f"{game['name']} {game['description'] or ''}".lower()
            if search.lower() not in text:
                return False
        if genre is not None and game["genre"] != genre:
            return False
        if min_players is not None and (
            game["min_players"] is None or game["min_players"] < min_players
        ):
            return False
        if max_players is not None and (
            game["max_players"] is None or game["max_players"] > max_players
        ):
            return False
        if max_avg_duration is not None and (
            game["avg_duration"] is None or game["avg_duration"] > max_avg_duration
        ):
            return False
        if user_rating is not None and game["avg_rating"] < user_rating:
            return False
        if complexity_rating is not None and game["complexity_rating"] != complexity_rating:
            return False
        if strategy_rating is not None and game["strategy_rating"] != strategy_rating:
            return False
        if luck_rating is not None and game["luck_rating"] != luck_rating:
            return False
        if interaction_rating is not None and game["interaction_rating"] != interaction_rating:
            return False
        return True

    available_games = [game for game in available_games if matches_filters(game)]
    unavailable_games = [game for game in unavailable_games if matches_filters(game)]

    return render_template(
        "stores/select_games.html",
        store=store,
        table=table,
        available_games=available_games,
        unavailable_games=unavailable_games,
        genres=genres,
        day=day,
        start_time=start_time,
        end_time=end_time,
        search=search,
        selected_genre=genre,
        min_players=min_players,
        max_players=max_players,
        max_avg_duration=max_avg_duration,
        user_rating=user_rating,
        complexity_rating=complexity_rating,
        strategy_rating=strategy_rating,
        luck_rating=luck_rating,
        interaction_rating=interaction_rating,
    )


@bp.route(
    "/store/<int:store_id>/table/<int:table_num>/confirm-booking", methods=("POST",)
)
def confirm_booking(store_id, table_num):
    if not g.user:
        return redirect(url_for("auth.login"))

    day = request.form.get("day")
    start_time = request.form.get("start_time", type=int)
    end_time = request.form.get("end_time", type=int)
    selected_games = request.form.getlist("selected_games")

    if not selected_games:
        flash("Please select at least one game.")
        return redirect(
            url_for(
                "stores.select_games",
                store_id=store_id,
                table_num=table_num,
                day=day,
                start_time=start_time,
                end_time=end_time,
            )
        )

    if get_reservation_count(g.user["id"]) >= MAX_RESERVATIONS:
        flash("You have reached the maximum number of active reservations.")
        return redirect(
            url_for(
                "stores.select_games",
                store_id=store_id,
                table_num=table_num,
                day=day,
                start_time=start_time,
                end_time=end_time,
            )
        )

    try:
        game_ids = [int(game_id) for game_id in selected_games]
        create_session(
            g.user["id"], store_id, table_num, day, start_time, end_time, game_ids
        )
        flash(
            f"Session booked! Table {table_num} from {start_time}:00 to {end_time}:00"
        )
        return redirect(url_for("index"))
    except ValueError as e:
        flash(str(e))
        return redirect(
            url_for(
                "stores.select_games",
                store_id=store_id,
                table_num=table_num,
                day=day,
                start_time=start_time,
                end_time=end_time,
            )
        )
    except Exception as e:
        flash(f"Error booking session: {str(e)}")
        return redirect(
            url_for(
                "stores.select_games",
                store_id=store_id,
                table_num=table_num,
                day=day,
                start_time=start_time,
                end_time=end_time,
            )
        )


@bp.route("/store/<int:store_id>/games")
def game_library(store_id):
    genre = request.args.get("genre") or None
    min_players = request.args.get("min_players", type=int)
    max_players = request.args.get("max_players", type=int)
    user_rating = request.args.get("user_rating", type=int)
    complexity_rating = request.args.get("complexity_rating", type=int)
    strategy_rating = request.args.get("strategy_rating", type=int)
    luck_rating = request.args.get("luck_rating", type=int)
    interaction_rating = request.args.get("interaction_rating", type=int)
    max_avg_duration = request.args.get("max_avg_duration", type=int)
    available_only = request.args.get("available_only") == "1"
    search = request.args.get("search") or None

    errors = []
    if min_players is not None and min_players < 1:
        errors.append("Minimum players must be at least 1.")
        min_players = None
    if (
        min_players is not None
        and max_players is not None
        and max_players < min_players
    ):
        errors.append("Maximum players must be >= minimum players.")
        max_players = None

    for err in errors:
        flash(err)

    games = get_games_filtered(
        store_id,
        genre=genre,
        min_players=min_players,
        max_players=max_players,
        user_rating=user_rating,
        complexity_rating=complexity_rating,
        strategy_rating=strategy_rating,
        luck_rating=luck_rating,
        interaction_rating=interaction_rating,
        max_avg_duration=max_avg_duration,
        available_only=available_only,
        search=search,
    )

    store = get_store_by_id(store_id)
    genres = get_store_genres(store_id)

    return render_template(
        "stores/game_library.html",
        store=store,
        games=games,
        genres=genres,
        selected_genre=genre,
        min_players=min_players,
        max_players=max_players,
        user_rating=user_rating,
        complexity_rating=complexity_rating,
        strategy_rating=strategy_rating,
        luck_rating=luck_rating,
        interaction_rating=interaction_rating,
        max_avg_duration=max_avg_duration,
        available_only=available_only,
        search=search,
    )


@bp.route("/store/<int:store_id>/game/<int:game_id>")
def game_detail(store_id, game_id):
    store = get_store_by_id(store_id)
    game = get_game_detail(game_id)
    if game is None:
        abort(404)
    copies = get_game_copies_with_condition(game_id, store_id)
    ratings = get_game_ratings(game_id)
    similar_games = get_similar_games(game_id, store_id)
    user_rating = None
    if g.user:
        user_rating = get_user_rating(g.user["id"], game_id)
    return render_template(
        "stores/game_detail.html",
        store=store,
        game=game,
        copies=copies,
        ratings=ratings,
        similar_games=similar_games,
        user_rating=user_rating,
    )


@bp.route("/store/<int:store_id>/game/<int:game_id>/rate", methods=("POST",))
def rate_game_route(store_id, game_id):
    if not g.user:
        return redirect(url_for("auth.login"))

    if get_game_detail(game_id) is None:
        abort(404)
    rating = request.form.get("rating", type=int)
    comment = request.form.get("comment") or None
    if rating is None or not (1 <= rating <= 5):
        flash("Rating must be between 1 and 5.")
        return redirect(
            url_for("stores.game_detail", store_id=store_id, game_id=game_id)
        )

    rate_game(g.user["id"], game_id, rating, comment)
    flash("Rating submitted successfully.")
    return redirect(url_for("stores.game_detail", store_id=store_id, game_id=game_id))
