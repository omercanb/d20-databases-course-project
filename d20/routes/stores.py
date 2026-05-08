import functools
from datetime import date, datetime, timedelta
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from d20.db import get_db
from d20.db.game import (
    FileTypeError,
    ImageTooLargeError,
    create_game,
    create_game_copy,
    delete_game_copy,
    get_available_games_during,
    get_available_games_with_counts,
    get_game_copies_with_condition,
    get_game_detail,
    get_game_ratings,
    get_games,
    get_games_filtered,
    get_latest_game_copy,
    get_similar_games,
    get_store_genres,
    get_unavailable_games_during,
    get_user_rating,
    rate_game,
    update_game_image,
    update_game_image_url,
)
from d20.db.loyalty import get_user_advance_days
from d20.db.voucher import (
    REWARD_TYPE_LABELS,
    buy_voucher,
    calculate_voucher_discount,
    create_voucher,
    delete_voucher,
    get_customer_vouchers,
    get_store_vouchers,
    get_unused_vouchers_for_session,
    update_voucher,
)
from d20.db.session import (
    MAX_RESERVATIONS,
    create_session,
    delete_session,
    get_available_tables,
    get_reservation_count,
    get_session,
    get_unavailable_tables,
    get_upcoming_sessions_with_user_and_games_by_store,
    is_session_not_attended,
)
from d20.db.stores import (
    create_table,
    delete_table,
    get_store_analytics_summary,
    get_store_by_id,
    get_store_overview_metrics,
    get_store_popular_games,
    get_store_popular_menu_items,
    get_table,
    get_tables,
    update_table,
)
from d20.routes import ALLOWED_IMAGE_EXTENSIONS, MAX_IMAGE_SIZE_BYTES

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


def _quarter_bounds(day):
    quarter_start_month = ((day.month - 1) // 3) * 3 + 1
    start = date(day.year, quarter_start_month, 1)
    if quarter_start_month == 10:
        next_start = date(day.year + 1, 1, 1)
    else:
        next_start = date(day.year, quarter_start_month + 3, 1)
    return start, next_start - timedelta(days=1)


def _parse_date_arg(name, default):
    value = request.args.get(name)
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        return default


@bp.route("/")
def stores():
    db = get_db()

    search = request.args.get("search", "")
    print(f"[STORES] Search query: '{search}'")

    stores = db.execute(
        "select * from Store where name ilike %s", (f"%{search}%",)
    ).fetchall()
    print(f"[STORES] Found {len(stores)} results")

    return render_template("stores/stores.html", stores=stores, search=search)


@bp.route("/mystore")
@store_login_required
def my_store():
    return redirect(url_for("stores.my_store_overview"))


@bp.route("/mystore/overview")
@store_login_required
def my_store_overview():
    store_id = g.store["id"]
    today = date.today()
    overview = get_store_overview_metrics(store_id, today)
    popular_games = [
        dict(game)
        for game in get_store_popular_games(store_id, limit=1, start_date=today, end_date=today)
    ]
    popular_menu_items = get_store_popular_menu_items(
        store_id, limit=1, start_date=today, end_date=today
    )
    today_iso = today.isoformat()
    upcoming_sessions_raw = get_upcoming_sessions_with_user_and_games_by_store(
        store_id, today_iso
    )
    upcoming_sessions = [dict(sess) for sess in upcoming_sessions_raw]

    from collections import Counter
    next_7_days = [(today + timedelta(days=i)).isoformat() for i in range(7)]
    session_counts = Counter(sess["day"] for sess in upcoming_sessions)
    sessions_by_day = [session_counts.get(d, 0) for d in next_7_days]

    return render_template(
        "stores/mystore_overview.html",
        upcoming_sessions=upcoming_sessions,
        overview=overview,
        popular_games=popular_games,
        popular_menu_items=popular_menu_items,
        sessions_by_day=sessions_by_day,
        next_7_days=next_7_days,
    )


@bp.route("/mystore/analytics")
@store_login_required
def my_store_analytics():
    store_id = g.store["id"]
    current_q_start, current_q_end = _quarter_bounds(date.today())
    previous_q_end = current_q_start - timedelta(days=1)
    previous_q_start, _ = _quarter_bounds(previous_q_end)

    period_a_start = _parse_date_arg("a_start", current_q_start)
    period_a_end = _parse_date_arg("a_end", current_q_end)
    period_b_start = _parse_date_arg("b_start", previous_q_start)
    period_b_end = _parse_date_arg("b_end", previous_q_end)
    if period_a_start > period_a_end:
        period_a_start, period_a_end = period_a_end, period_a_start
    if period_b_start > period_b_end:
        period_b_start, period_b_end = period_b_end, period_b_start

    period_a = get_store_analytics_summary(store_id, period_a_start, period_a_end)
    period_b = get_store_analytics_summary(store_id, period_b_start, period_b_end)
    games_a = [
        dict(game)
        for game in get_store_popular_games(store_id, 5, period_a_start, period_a_end)
    ]
    games_b = [
        dict(game)
        for game in get_store_popular_games(store_id, 5, period_b_start, period_b_end)
    ]
    menu_a = get_store_popular_menu_items(store_id, 5, period_a_start, period_a_end)
    menu_b = get_store_popular_menu_items(store_id, 5, period_b_start, period_b_end)

    return render_template(
        "stores/mystore_analytics.html",
        period_a=period_a,
        period_b=period_b,
        games_a=games_a,
        games_b=games_b,
        menu_a=menu_a,
        menu_b=menu_b,
    )


@bp.route("/mystore/games")
@store_login_required
def my_store_games():
    return redirect(url_for("stores.my_store_games_inventory"))


@bp.route("/mystore/games/inventory")
@store_login_required
def my_store_games_inventory():
    store_id = g.store["id"]
    games = get_available_games_with_counts(store_id)
    all_games = get_games()
    return render_template(
        "stores/mystore_games_inventory.html",
        games=games,
        all_games=all_games,
    )


@bp.route("/mystore/games/library")
@store_login_required
def my_store_games_library():
    all_games = get_games()
    return render_template(
        "stores/mystore_games_library.html",
        all_games=all_games,
    )


@bp.route("/mystore/game/<int:game_id>/edit")
@store_login_required
def edit_store_game(game_id):
    game = get_game_detail(game_id)
    if game is None:
        abort(404)
    if not get_game_copies_with_condition(game_id, g.store["id"]):
        flash("You can only edit games in your inventory.")
        return redirect(url_for("stores.my_store_games_inventory"))
    return render_template("stores/mystore_game_edit.html", game=game)


@bp.route("/mystore/game/<int:game_id>/edit", methods=("POST",))
@store_login_required
def update_store_game(game_id):
    game = get_game_detail(game_id)
    if game is None:
        abort(404)
    if not get_game_copies_with_condition(game_id, g.store["id"]):
        flash("You can only edit games in your inventory.")
        return redirect(url_for("stores.my_store_games_inventory"))

    db = get_db()
    try:
        db.execute(
            """
            UPDATE Game
            SET name = %s,
                symbol = %s,
                genre = %s,
                min_players = %s,
                max_players = %s,
                avg_duration = %s,
                complexity_rating = %s,
                strategy_rating = %s,
                luck_rating = %s,
                interaction_rating = %s,
                description = %s,
                publisher = %s
            WHERE id = %s
            """,
            (
                request.form.get("name", "").strip(),
                request.form.get("symbol", "").strip(),
                request.form.get("genre") or None,
                request.form.get("min_players", type=int),
                request.form.get("max_players", type=int),
                request.form.get("avg_duration", type=int),
                request.form.get("complexity_rating", type=int),
                request.form.get("strategy_rating", type=int),
                request.form.get("luck_rating", type=int),
                request.form.get("interaction_rating", type=int),
                request.form.get("description") or None,
                request.form.get("publisher") or None,
                game_id,
            ),
        )
        db.commit()
        flash("Game updated successfully.")
    except db.IntegrityError:
        flash("A game with this name or symbol already exists.")
    except Exception as exc:
        flash(f"Error updating game: {exc}")
    return redirect(url_for("stores.edit_store_game", game_id=game_id))


@bp.route("/mystore/tables")
@store_login_required
def my_store_tables():
    store_id = g.store["id"]
    tables = get_tables(store_id)
    return render_template(
        "stores/mystore_tables.html",
        tables=tables,
    )


@bp.route("/mystore/sessions")
@store_login_required
def my_store_sessions():
    store_id = g.store["id"]
    today = str(date.today())
    current_hour = datetime.now().hour
    from_day = request.args.get("from_day") or ""
    to_day = request.args.get("to_day") or ""
    upcoming_sessions_raw = get_upcoming_sessions_with_user_and_games_by_store(
        store_id, today
    )

    all_sessions = []
    for sess in upcoming_sessions_raw:
        if from_day and sess["day"] < from_day:
            continue
        if to_day and sess["day"] > to_day:
            continue
        sess_dict = dict(sess)
        sess_dict["is_not_attended"] = is_session_not_attended(
            sess, today, current_hour
        )
        all_sessions.append(sess_dict)

    # Split into active (started today) and pending (not started yet)
    active_sessions = []
    pending_sessions = []

    for sess in all_sessions:
        if sess["day"] == today and sess["start_time"] <= current_hour:
            active_sessions.append(sess)
        else:
            pending_sessions.append(sess)

    return render_template(
        "stores/mystore_sessions.html",
        active_sessions=active_sessions,
        pending_sessions=pending_sessions,
        from_day=from_day,
        to_day=to_day,
    )


@bp.route("/mystore/table/add", methods=("POST",))
@store_login_required
def add_table():
    capacity = request.form.get("capacity", type=int)
    if capacity is None or capacity <= 0:
        flash("Capacity must be a positive number.")
        return redirect(url_for("stores.my_store_tables"))

    try:
        create_table(g.store["id"], capacity)
        flash("Table added successfully.")
    except Exception as e:
        flash(f"Error adding table: {str(e)}")

    return redirect(url_for("stores.my_store_tables"))


@bp.route("/mystore/table/<int:table_num>/update", methods=("POST",))
@store_login_required
def update_table_route(table_num):
    capacity = request.form.get("capacity", type=int)
    if capacity is None or capacity <= 0:
        flash("Capacity must be a positive number.")
        return redirect(url_for("stores.my_store_tables"))

    try:
        update_table(g.store["id"], table_num, capacity)
        flash("Table updated successfully.")
    except Exception as e:
        flash(f"Error updating table: {str(e)}")

    return redirect(url_for("stores.my_store_tables"))


@bp.route("/mystore/table/<int:table_num>/delete", methods=("POST",))
@store_login_required
def delete_table_route(table_num):
    try:
        delete_table(g.store["id"], table_num)
        flash("Table deleted successfully.")
    except Exception as e:
        flash(f"Error deleting table: {str(e)}")

    return redirect(url_for("stores.my_store_tables"))


@bp.route("/mystore/game/add", methods=("POST",))
@store_login_required
def add_game_copy():
    game_id = request.form.get("game_id", type=int)
    copy_count = request.form.get("copy_count", 1, type=int)
    if game_id is None:
        flash("Please select a game.")
        return redirect(url_for("stores.my_store_games_inventory"))
    if copy_count is None or copy_count <= 0:
        flash("Copy count must be a positive number.")
        return redirect(url_for("stores.my_store_games_inventory"))

    try:
        for _ in range(copy_count):
            create_game_copy(game_id, g.store["id"])
        flash(
            f"{copy_count} game {'copy' if copy_count == 1 else 'copies'} added successfully."
        )
    except Exception as e:
        flash(f"Error adding game copy: {str(e)}")

    return redirect(url_for("stores.my_store_games_inventory"))


@bp.route("/mystore/game/create", methods=("POST",))
@store_login_required
def create_store_game():
    name = request.form.get("name", "").strip()
    symbol = request.form.get("symbol", "").strip()
    genre = request.form.get("genre") or None
    min_players = request.form.get("min_players", type=int)
    max_players = request.form.get("max_players", type=int)
    avg_duration = request.form.get("avg_duration", type=int)
    complexity_rating = request.form.get("complexity_rating", type=int)
    strategy_rating = request.form.get("strategy_rating", type=int)
    luck_rating = request.form.get("luck_rating", type=int)
    interaction_rating = request.form.get("interaction_rating", type=int)
    description = request.form.get("description") or None
    publisher = request.form.get("publisher") or None

    if not name or not symbol:
        flash("Game name and symbol are required.")
        return redirect(url_for("stores.my_store_games_library"))

    db = get_db()
    try:
        create_game(
            name=name,
            symbol=symbol,
            genre=genre,
            min_players=min_players,
            max_players=max_players,
            complexity_rating=complexity_rating,
            avg_duration=avg_duration,
            description=description,
            publisher=publisher,
            strategy_rating=strategy_rating,
            luck_rating=luck_rating,
            interaction_rating=interaction_rating,
        )
        flash("Game created in catalog.")
    except db.IntegrityError:
        flash("A game with this name or symbol already exists.")
    except Exception as e:
        flash(f"Error creating game: {str(e)}")

    return redirect(url_for("stores.my_store_games_library"))


@bp.route("/mystore/game/<int:game_id>/upload-image", methods=("POST",))
@store_login_required
def upload_game_image(game_id):
    game = get_game_detail(game_id)
    if game is None:
        abort(404)
    if not get_game_copies_with_condition(game_id, g.store["id"]):
        flash("You can only upload images for games in your inventory.")
        return redirect(url_for("stores.edit_store_game", game_id=game_id))

    image = request.files.get("image")
    if image is None or not image.filename:
        flash("Please choose an image to upload.")
        return redirect(url_for("stores.edit_store_game", game_id=game_id))

    try:
        update_game_image(game["id"], image)
    except FileTypeError:
        flash("Invalid file type. Use jpg, jpeg, png, or webp.")
        return redirect(url_for("stores.edit_store_game", game_id=game_id))
    except ImageTooLargeError:
        flash("Image is too large. Maximum size is 5MB.")
        return redirect(url_for("stores.edit_store_game", game_id=game_id))
    except Exception as exc:
        flash(f"Error uploading image: {exc}")

    return redirect(url_for("stores.edit_store_game", game_id=game_id))


@bp.route("/mystore/game/<int:game_id>/remove", methods=("POST",))
@store_login_required
def remove_game_copy(game_id):
    try:
        copy = get_latest_game_copy(game_id, g.store["id"])

        if not copy:
            flash("No copies of this game found.")
            return redirect(url_for("stores.my_store_games_inventory"))

        delete_game_copy(game_id, g.store["id"], copy["copy_num"])
        flash("Game copy removed successfully.")
    except Exception as e:
        flash(f"Error removing game copy: {str(e)}")

    return redirect(url_for("stores.my_store_games_inventory"))


@bp.route("/mystore/session/<int:session_id>/cancel", methods=("POST",))
@store_login_required
def cancel_store_session(session_id):
    sess = get_session(session_id)
    if not sess or sess["store_id"] != g.store["id"]:
        flash("Session not found.")
        return redirect(url_for("stores.my_store_sessions"))

    try:
        delete_session(session_id)
        flash("Session cancelled successfully.")
    except Exception as e:
        flash(f"Error cancelling session: {str(e)}")

    return redirect(url_for("stores.my_store_sessions"))


from d20.db.checkout import checkout_session as do_checkout_session
from d20.db.checkout import get_bill, get_session_game_copies
from d20.db.menu import get_session_orders


@bp.route("/mystore/session/<int:session_id>/checkout", methods=("GET",))
@store_login_required
def checkout_session_form(session_id):
    sess = get_session(session_id)
    if not sess or sess["store_id"] != g.store["id"]:
        flash("Session not found.")
        return redirect(url_for("stores.my_store_sessions"))

    if sess["checkout_status"] == "checked_out":
        return redirect(url_for("stores.view_bill", session_id=session_id))

    if not sess["checked_in"]:
        flash("Customer must check in before checkout.")
        return redirect(url_for("stores.my_store_sessions"))

    game_copies = get_session_game_copies(session_id)
    food_orders = get_session_orders(session_id)
    food_total = sum(float(o["total_amount"]) for o in food_orders)

    # Calculate potential loyalty discounts
    from d20.db.loyalty import (
        REDEMPTION_RATE,
        calculate_tier_discount,
        get_customer_loyalty_profile,
    )
    db = get_db()
    discount_row = db.execute(
        """
        SELECT COALESCE(SUM(points_spent), 0) as total_points 
        FROM LoyaltyRedemption 
        WHERE user_id = %s AND store_id = %s AND bill_id IS NULL
        """,
        (sess["user_id"], sess["store_id"])
    ).fetchone()
    loyalty_discount = round(float(discount_row["total_points"] * REDEMPTION_RATE), 2)
    table_fee = (sess["end_time"] - sess["start_time"]) * 5.0
    subtotal_before_tier = max(0.0, table_fee + food_total - loyalty_discount)
    tier_discount, tier_benefits = calculate_tier_discount(
        sess["user_id"], sess["store_id"], subtotal_before_tier
    )
    customer_loyalty_profile = get_customer_loyalty_profile(
        sess["user_id"], sess["store_id"], session_limit=5
    )

    available_vouchers = []
    if sess.get("user_id"):
        available_vouchers = get_unused_vouchers_for_session(sess["user_id"], sess["store_id"])
        subtotal_before_voucher = max(0.0, subtotal_before_tier - tier_discount)
        for voucher in available_vouchers:
            voucher["applicable_discount"] = calculate_voucher_discount(
                voucher, table_fee, food_total, subtotal_before_voucher
            )

    return render_template(
        "stores/checkout.html",
        sess=sess,
        game_copies=game_copies,
        food_orders=food_orders,
        food_total=food_total,
        loyalty_discount=loyalty_discount,
        tier_discount=tier_discount,
        tier_benefits=tier_benefits,
        available_vouchers=available_vouchers,
        reward_type_labels=REWARD_TYPE_LABELS,
        customer_loyalty_profile=customer_loyalty_profile,
    )


@bp.route("/mystore/session/<int:session_id>/checkout", methods=("POST",))
@store_login_required
def do_checkout(session_id):
    sess = get_session(session_id)
    if not sess or sess["store_id"] != g.store["id"]:
        flash("Session not found.")
        return redirect(url_for("stores.my_store_sessions"))

    if sess["checkout_status"] == "checked_out":
        flash("Session already checked out.")
        return redirect(url_for("stores.view_bill", session_id=session_id))

    if not sess["checked_in"]:
        flash("Customer must check in before checkout.")
        return redirect(url_for("stores.my_store_sessions"))

    game_copies = get_session_game_copies(session_id)
    game_conditions = []
    for gc in game_copies:
        field_condition = f"condition_{gc['game_id']}_{gc['copy_num']}"
        field_description = f"desc_{gc['game_id']}_{gc['copy_num']}"
        condition = request.form.get(field_condition, "good")
        description = request.form.get(field_description, "")
        game_conditions.append(
            {
                "game_id": gc["game_id"],
                "store_id": gc["store_id"],
                "copy_num": gc["copy_num"],
                "condition": condition,
                "description": description,
            }
        )

    customer_voucher_id = request.form.get("customer_voucher_id", type=int)

    try:
        do_checkout_session(session_id, game_conditions, customer_voucher_id)

        # Award loyalty points
        from d20.db.loyalty import add_points, get_point_rule
        duration = sess["end_time"] - sess["start_time"]
        if duration > 0:
            points = int(duration * get_point_rule(sess["store_id"], "session_hour"))
            add_points(sess["user_id"], sess["store_id"], points)
            
        flash("Session checked out successfully! Loyalty points awarded.")
        return redirect(url_for("stores.view_bill", session_id=session_id))
    except ValueError as e:
        flash(str(e))
        return redirect(url_for("stores.checkout_session_form", session_id=session_id))
    except Exception as e:
        flash(f"Error during checkout: {str(e)}")
        return redirect(url_for("stores.checkout_session_form", session_id=session_id))


@bp.route("/mystore/session/<int:session_id>/bill")
@store_login_required
def view_bill(session_id):
    sess = get_session(session_id)
    if not sess or sess["store_id"] != g.store["id"]:
        flash("Session not found.")
        return redirect(url_for("stores.my_store_sessions"))

    bill = get_bill(session_id)
    game_copies = get_session_game_copies(session_id)
    food_orders = get_session_orders(session_id)
    return render_template(
        "stores/bill.html",
        sess=sess,
        bill=bill,
        game_copies=game_copies,
        food_orders=food_orders,
    )


@bp.route("/store/<int:store_id>")
def store(store_id):
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

    store = get_store_by_id(store_id)
    if store is None:
        abort(404)
    tables = get_tables(store_id)
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
    genres = get_store_genres(store_id)
    return render_template(
        "stores/store.html",
        store=store,
        tables=tables,
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


@bp.route("/store/<int:store_id>/book")
def book_session(store_id):
    start_time = request.args.get("start_time", 9, type=int)
    end_time = request.args.get("end_time", 20, type=int)
    day = request.args.get("day") or str(date.today())
    store = get_store_by_id(store_id)
    if store is None:
        abort(404)
    if start_time is None or end_time is None or end_time <= start_time:
        flash("End time must be later than start time.")
        start_time, end_time = 9, 20
    max_advance = None
    max_date = None
    if g.user:
        max_advance = get_user_advance_days(g.user["id"], store_id)
        max_date = str(date.today() + timedelta(days=max_advance))
    tables = get_available_tables(store_id, day, start_time, end_time)
    unvailable_tables = get_unavailable_tables(store_id, day, start_time, end_time)
    return render_template(
        "stores/book_session.html",
        store=store,
        tables=tables,
        unvailable_tables=unvailable_tables,
        day=day,
        today=str(date.today()),
        max_date=max_date,
        max_advance=max_advance,
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
    if start_time is None or end_time is None or end_time <= start_time:
        flash("End time must be later than start time.")
        return redirect(url_for("stores.book_session", store_id=store_id, day=day))
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
    if store is None:
        abort(404)
    table = get_table(store_id, table_num)
    filter_args = dict(
        search=search,
        genre=genre,
        min_players=min_players,
        max_players=max_players,
        max_avg_duration=max_avg_duration,
        user_rating=user_rating,
        complexity_rating=complexity_rating,
        strategy_rating=strategy_rating,
        luck_rating=luck_rating,
        interaction_rating=interaction_rating,
    )
    available_games = get_available_games_during(
        store_id, day, start_time, end_time, **filter_args
    )
    unavailable_games = get_unavailable_games_during(
        store_id, day, start_time, end_time, **filter_args
    )
    genres = get_store_genres(store_id)

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

    if start_time is None or end_time is None or end_time <= start_time:
        flash("End time must be later than start time.")
        return redirect(
            url_for(
                "stores.select_games",
                store_id=store_id,
                table_num=table_num,
                day=day,
                start_time=9,
                end_time=20,
            )
        )

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

    booking_date = date.fromisoformat(day)
    days_ahead = (booking_date - date.today()).days
    max_advance = get_user_advance_days(g.user["id"], store_id)
    if days_ahead > max_advance:
        flash(
            f"Your loyalty tier allows booking up to {max_advance} day(s) in advance."
        )
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


@bp.route("/store/<int:store_id>/game/<int:game_id>")
def game_detail(store_id, game_id):
    store = get_store_by_id(store_id)
    if store is None:
        abort(404)
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
    
    from d20.db.loyalty import add_points, get_point_rule
    add_points(g.user["id"], store_id, int(get_point_rule(store_id, "game_rating")))
    
    flash("Rating submitted successfully. You earned loyalty points!")
    return redirect(url_for("stores.game_detail", store_id=store_id, game_id=game_id))


from d20.db.menu import (
    create_beverage,
    create_food,
    create_menu_item,
    delete_menu_item,
    get_menu,
    get_menu_item_full,
    toggle_menu_item_availability,
    update_menu_item,
)


@bp.route("/store/<int:store_id>/menu")
def store_menu(store_id):
    store = get_store_by_id(store_id)
    if store is None:
        abort(404)
    menu_items = get_menu(store_id)
    return render_template(
        "stores/menu.html",
        store=store,
        menu_items=menu_items,
    )


# ── Store owner menu management ──────────────────────────────────────────────


@bp.route("/mystore/menu")
@store_login_required
def my_store_menu():
    store_id = g.store["id"]
    menu_items = get_menu(store_id)
    return render_template(
        "stores/mystore_menu.html",
        menu_items=menu_items,
    )


@bp.route("/mystore/loyalty")
@store_login_required
def my_store_loyalty():
    from d20.db.loyalty import get_store_loyalty_stats
    stats = get_store_loyalty_stats(g.store["id"])
    return render_template(
        "stores/mystore_loyalty.html",
        stats=stats,
    )


@bp.route("/mystore/loyalty/analytics")
@store_login_required
def my_store_loyalty_analytics():
    from d20.db.loyalty import get_loyalty_analytics
    selected_tier = request.args.get("tier") or None
    analytics = get_loyalty_analytics(g.store["id"], tier_code=selected_tier)
    if selected_tier and selected_tier not in analytics["available_tiers"]:
        flash("Unknown loyalty tier.")
        return redirect(url_for("stores.my_store_loyalty_analytics"))
    return render_template(
        "stores/mystore_loyalty_analytics.html",
        analytics=analytics,
        selected_tier=selected_tier,
    )


@bp.route("/mystore/loyalty/customer/<int:user_id>")
@store_login_required
def my_store_customer_loyalty_profile(user_id):
    from d20.db.loyalty import get_customer_loyalty_profile

    profile = get_customer_loyalty_profile(user_id, g.store["id"], session_limit=20)
    if profile is None:
        flash("Customer not found.")
        return redirect(url_for("stores.my_store_loyalty_analytics"))
    return render_template(
        "stores/mystore_loyalty_customer.html",
        profile=profile,
    )


@bp.route("/mystore/loyalty/tiers", methods=("POST",))
@store_login_required
def update_my_store_loyalty_tiers():
    from d20.db.loyalty import update_store_loyalty_tiers

    tiers = []
    for code in ("Bronze", "Silver", "Gold"):
        min_points = request.form.get(f"{code}_min_points", type=int)
        discount_percent = request.form.get(f"{code}_discount_percent", type=float)
        reservation_advance_days = request.form.get(f"{code}_reservation_advance_days", type=int)
        free_tournament_entries = request.form.get(f"{code}_free_tournament_entries", type=int)
        if (
            min_points is None
            or discount_percent is None
            or reservation_advance_days is None
            or free_tournament_entries is None
        ):
            flash("All loyalty tier fields are required.")
            return redirect(url_for("stores.my_store_loyalty"))
        if min_points < 0 or discount_percent < 0 or reservation_advance_days < 0 or free_tournament_entries < 0:
            flash("Loyalty tier values cannot be negative.")
            return redirect(url_for("stores.my_store_loyalty"))
        if discount_percent > 100:
            flash("Discount percent cannot exceed 100.")
            return redirect(url_for("stores.my_store_loyalty"))
        tiers.append(
            {
                "code": code,
                "min_points": min_points,
                "discount_percent": discount_percent,
                "reservation_advance_days": reservation_advance_days,
                "free_tournament_entries": free_tournament_entries,
            }
        )

    try:
        update_store_loyalty_tiers(g.store["id"], tiers)
        flash("Loyalty tiers updated.")
    except ValueError as e:
        flash(str(e))
    except Exception as e:
        flash(f"Error updating loyalty tiers: {str(e)}")
    return redirect(url_for("stores.my_store_loyalty"))


@bp.route("/mystore/loyalty/point-rules", methods=("POST",))
@store_login_required
def update_my_store_loyalty_point_rules():
    from d20.db.loyalty import update_store_loyalty_point_rules

    rule_labels = {
        "session_hour": "session hour",
        "food_dollar": "food dollar",
        "game_rating": "game rating",
        "tournament_participation": "tournament participation",
    }
    rules = []
    for action_code in rule_labels:
        points_per_unit = request.form.get(action_code, type=float)
        if points_per_unit is None:
            flash("All loyalty point earning rules are required.")
            return redirect(url_for("stores.my_store_loyalty"))
        if points_per_unit < 0:
            flash("Point earning rules cannot be negative.")
            return redirect(url_for("stores.my_store_loyalty"))
        rules.append({"action_code": action_code, "points_per_unit": points_per_unit})

    try:
        update_store_loyalty_point_rules(g.store["id"], rules)
        flash("Loyalty point earning rules updated.")
    except ValueError as e:
        flash(str(e))
    except Exception as e:
        flash(f"Error updating loyalty point earning rules: {str(e)}")
    return redirect(url_for("stores.my_store_loyalty"))


@bp.route("/store/<int:store_id>/loyalty")
def store_loyalty(store_id):
    store = get_store_by_id(store_id)
    if store is None:
        abort(404)
    vouchers = get_store_vouchers(store_id)
    user_points = 0
    user_vouchers = []
    if g.user:
        from d20.db.loyalty import get_user_points
        user_points = get_user_points(g.user["id"], store_id)
        user_vouchers = get_customer_vouchers(g.user["id"], store_id)
    return render_template(
        "stores/store_loyalty.html",
        store=store,
        vouchers=vouchers,
        user_points=user_points,
        user_vouchers=user_vouchers,
        reward_type_labels=REWARD_TYPE_LABELS,
    )


@bp.route("/store/<int:store_id>/voucher/<int:voucher_id>/buy", methods=("POST",))
def buy_store_voucher(store_id, voucher_id):
    if not g.user:
        return redirect(url_for("auth.login"))
    try:
        buy_voucher(g.user["id"], store_id, voucher_id)
        flash("Voucher purchased! Check your loyalty page to use it.")
    except ValueError as e:
        flash(str(e))
    except Exception as e:
        flash(f"Error: {str(e)}")
    return redirect(url_for("stores.store_loyalty", store_id=store_id))


@bp.route("/mystore/vouchers")
@store_login_required
def my_store_vouchers():
    vouchers = get_store_vouchers(g.store["id"], active_only=False)
    return render_template(
        "stores/mystore_vouchers.html",
        vouchers=vouchers,
        reward_type_labels=REWARD_TYPE_LABELS,
    )


@bp.route("/mystore/vouchers/add", methods=("POST",))
@store_login_required
def add_voucher():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip() or None
    point_cost = request.form.get("point_cost", type=int)
    reward_type = request.form.get("reward_type", "")
    reward_value = request.form.get("reward_value", type=float)
    if not name or point_cost is None or point_cost <= 0 or reward_type not in REWARD_TYPE_LABELS or reward_value is None or reward_value <= 0:
        flash("All fields required. Point cost and reward value must be positive.")
        return redirect(url_for("stores.my_store_vouchers"))
    try:
        create_voucher(g.store["id"], name, description, point_cost, reward_type, reward_value)
        flash(f"Voucher '{name}' created.")
    except Exception as e:
        flash(f"Error: {str(e)}")
    return redirect(url_for("stores.my_store_vouchers"))


@bp.route("/mystore/vouchers/<int:voucher_id>/edit", methods=("POST",))
@store_login_required
def edit_voucher(voucher_id):
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip() or None
    point_cost = request.form.get("point_cost", type=int)
    reward_type = request.form.get("reward_type", "")
    reward_value = request.form.get("reward_value", type=float)
    is_active = request.form.get("is_active") == "on"
    if not name or point_cost is None or point_cost <= 0 or reward_type not in REWARD_TYPE_LABELS or reward_value is None or reward_value <= 0:
        flash("All fields required. Point cost and reward value must be positive.")
        return redirect(url_for("stores.my_store_vouchers"))
    try:
        update_voucher(voucher_id, g.store["id"], name, description, point_cost, reward_type, reward_value, is_active)
        flash("Voucher updated.")
    except Exception as e:
        flash(f"Error: {str(e)}")
    return redirect(url_for("stores.my_store_vouchers"))


@bp.route("/mystore/vouchers/<int:voucher_id>/deactivate", methods=("POST",))
@store_login_required
def deactivate_voucher_route(voucher_id):
    from d20.db import get_db
    db = get_db()
    db.execute(
        "UPDATE LoyaltyVoucher SET is_active=FALSE WHERE id=%s AND store_id=%s",
        (voucher_id, g.store["id"]),
    )
    db.commit()
    flash("Voucher deactivated.")
    return redirect(url_for("stores.my_store_vouchers"))


@bp.route("/mystore/vouchers/<int:voucher_id>/delete", methods=("POST",))
@store_login_required
def delete_voucher_route(voucher_id):
    try:
        delete_voucher(voucher_id, g.store["id"])
        flash("Voucher deleted.")
    except Exception as e:
        flash(f"Error: {str(e)}")
    return redirect(url_for("stores.my_store_vouchers"))


@bp.route("/mystore/menu/add", methods=("POST",))
@store_login_required
def add_menu_item():
    store_id = g.store["id"]
    name = request.form.get("name", "").strip()
    price_str = request.form.get("price", "")
    description = request.form.get("description", "").strip() or None
    item_type = request.form.get("item_type", "Food")

    if not name:
        flash("Name is required.")
        return redirect(url_for("stores.my_store_menu"))
    try:
        price = float(price_str)
        if price < 0:
            raise ValueError
    except ValueError:
        flash("Price must be a non-negative number.")
        return redirect(url_for("stores.my_store_menu"))

    item_id = create_menu_item(store_id, name, price, description, is_available=True)

    if item_type == "Food":
        is_vegetarian = request.form.get("is_vegetarian") == "on"
        allergens = request.form.get("allergens", "").strip() or None
        category = request.form.get("category", "").strip() or None
        create_food(item_id, is_vegetarian, allergens, category)
    elif item_type == "Beverage":
        size = request.form.get("size", "").strip() or None
        temperature = request.form.get("temperature", "").strip() or None
        create_beverage(item_id, size, temperature)

    flash(f"'{name}' added to the menu.")
    return redirect(url_for("stores.my_store_menu"))


@bp.route("/mystore/menu/<int:item_id>/edit", methods=("GET", "POST"))
@store_login_required
def edit_menu_item(item_id):
    item = get_menu_item_full(item_id)
    if item is None or item["store_id"] != g.store["id"]:
        flash("Menu item not found.")
        return redirect(url_for("stores.my_store_menu"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price_str = request.form.get("price", "")
        description = request.form.get("description", "").strip() or None
        is_available = request.form.get("is_available") == "on"
        item_type = request.form.get("item_type", item["item_type"])

        if not name:
            flash("Name is required.")
            return redirect(url_for("stores.edit_menu_item", item_id=item_id))
        try:
            price = float(price_str)
            if price < 0:
                raise ValueError
        except ValueError:
            flash("Price must be a non-negative number.")
            return redirect(url_for("stores.edit_menu_item", item_id=item_id))

        is_vegetarian = request.form.get("is_vegetarian") == "on"
        allergens = request.form.get("allergens", "").strip() or None
        category = request.form.get("category", "").strip() or None
        size = request.form.get("size", "").strip() or None
        temperature = request.form.get("temperature", "").strip() or None

        update_menu_item(
            item_id,
            name,
            price,
            description,
            is_available,
            item_type,
            is_vegetarian=is_vegetarian,
            allergens=allergens,
            category=category,
            size=size,
            temperature=temperature,
        )
        flash(f"'{name}' updated successfully.")
        return redirect(url_for("stores.my_store_menu"))

    return render_template("stores/mystore_menu_edit.html", item=item)


@bp.route("/mystore/menu/<int:item_id>/toggle", methods=("POST",))
@store_login_required
def toggle_menu_item(item_id):
    item = get_menu_item_full(item_id)
    if item is None or item["store_id"] != g.store["id"]:
        flash("Menu item not found.")
    else:
        toggle_menu_item_availability(item_id)
        status = "unavailable" if item["is_available"] else "available"
        flash(f"'{item['name']}' marked as {status}.")
    return redirect(url_for("stores.my_store_menu"))


@bp.route("/mystore/menu/<int:item_id>/delete", methods=("POST",))
@store_login_required
def delete_menu_item_route(item_id):
    item = get_menu_item_full(item_id)
    if item is None or item["store_id"] != g.store["id"]:
        flash("Menu item not found.")
    else:
        delete_menu_item(item_id)
        flash(f"'{item['name']}' removed from the menu.")
    return redirect(url_for("stores.my_store_menu"))
