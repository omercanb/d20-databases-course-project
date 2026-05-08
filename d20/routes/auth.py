import functools
from datetime import date, datetime
from operator import add

from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from d20.db import get_db
from d20.db.menu import create_session_order, get_menu, get_session_orders
from d20.db.session import (
    MAX_RESERVATIONS,
    check_in_session,
    delete_session,
    get_reservation_count,
    get_session,
    get_session_games,
    get_sessions_with_store_by_user,
    is_session_not_attended,
    session_has_ended,
)
from d20.db.stores import create_store, get_store, get_store_by_id
from d20.db.user import create_user, get_user, get_user_by_id

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        db = get_db()
        error = None

        if not username:
            error = "Username is required."
        elif not password:
            error = "Password is required."

        if error is None:
            try:
                create_user(username, password)
            except db.IntegrityError:
                error = f"User {username} is already registered."
            else:
                return redirect(url_for("auth.login"))

        flash(error)

    return render_template("auth/register.html")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        error = None

        if not username:
            error = "Username is required"
        elif not password:
            error = "Password is required"

        user = get_user(username)

        if user is None:
            error = "Incorrect username."
        elif not check_password_hash(user["password"], password):
            error = "Incorrect password."

        if error is None:
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("index"))

        flash(error)

    return render_template("auth/login.html")


@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")

    if user_id is None:
        g.user = None
    else:
        g.user = get_user_by_id(user_id)


def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))

        return view(**kwargs)

    return wrapped_view


@bp.route("/registerstore", methods=("GET", "POST"))
def registerstore():
    if request.method == "POST":
        username = request.form["username"]
        store_name = request.form["store_name"]
        password = request.form["password"]
        address = request.form["address"]
        db = get_db()
        error = None

        if not username:
            error = "Username is required."
        elif not store_name:
            error = "Store name is required."
        elif not password:
            error = "Password is required."
        elif not address:
            error = "Address is required."

        if error is None:
            try:
                create_store(username, store_name, password, address)
            except db.IntegrityError:
                error = f"Store {username}/{store_name} is already registered."
            else:
                return redirect(url_for("auth.loginstore"))

        flash(error)

    return render_template("auth/registerstore.html")


@bp.route("/loginstore", methods=("GET", "POST"))
def loginstore():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        error = None

        if not username:
            error = "Username is required"
        elif not password:
            error = "Password is required"

        store = get_store(username)

        if store is None:
            error = "Incorrect username."
        elif not check_password_hash(store["password"], password):
            error = "Incorrect password."

        if error is None:
            session.clear()
            session["store_id"] = store["id"]
            return redirect(url_for("index"))

        flash(error)

    return render_template("auth/loginstore.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@bp.route("/sessions")
@login_required
def view_sessions():
    sessions = get_sessions_with_store_by_user(g.user["id"])
    today = str(date.today())
    current_hour = datetime.now().hour

    upcoming = []
    past = []

    for sess in sessions:
        sess_dict = dict(sess)
        sess_dict["games"] = get_session_games(sess["id"])
        sess_dict["is_not_attended"] = is_session_not_attended(
            sess, today, current_hour
        )
        if (
            sess["checkout_status"] == "checked_out"
            or session_has_ended(sess, today, current_hour)
        ):
            past.append(sess_dict)
        else:
            upcoming.append(sess_dict)

    return render_template(
        "auth/sessions.html",
        upcoming_sessions=upcoming,
        past_sessions=past,
        reservation_count=get_reservation_count(g.user["id"]),
        max_reservation_count=MAX_RESERVATIONS,
        today=today,
        current_hour=current_hour,
    )


@bp.route("/session/<int:session_id>/cancel", methods=("POST",))
@login_required
def cancel_session(session_id):
    sess = get_session(session_id)

    if not sess or sess["user_id"] != g.user["id"]:
        flash("Session not found.")
        return redirect(url_for("auth.view_sessions"))

    try:
        delete_session(session_id)
        flash("Session cancelled successfully.")
    except Exception as e:
        msg = str(e).split('\n')[0].replace('ERROR:', '').strip()
        flash(f"Could not cancel session: {msg}")

    return redirect(url_for("auth.view_sessions"))


@bp.route("/session/<int:session_id>/checkin", methods=("POST",))
@login_required
def check_in_user_session(session_id):
    sess = get_session(session_id)

    if not sess or sess["user_id"] != g.user["id"]:
        flash("Session not found.")
        return redirect(url_for("auth.view_sessions"))

    today = str(date.today())
    current_hour = datetime.now().hour

    if sess["day"] != today or sess["start_time"] > current_hour:
        flash("You can only check in when the session has started.")
        return redirect(url_for("auth.view_sessions"))

    if sess["end_time"] <= current_hour:
        flash("This session has already ended.")
        return redirect(url_for("auth.view_sessions"))

    if sess["checked_in"]:
        flash("You are already checked in.")
        return redirect(url_for("auth.view_sessions"))

    if sess["checkout_status"] == "checked_out":
        flash("This session has already been checked out.")
        return redirect(url_for("auth.view_sessions"))

    try:
        check_in_session(session_id)
        flash("Checked in successfully!")
    except Exception as e:
        flash(f"Error during check-in: {str(e)}")

    return redirect(url_for("auth.view_sessions"))


@bp.route("/session/<int:session_id>/order", methods=("GET", "POST"))
@login_required
def order_food(session_id):
    sess = get_session(session_id)
    if not sess or sess["user_id"] != g.user["id"]:
        flash("Session not found.")
        return redirect(url_for("auth.view_sessions"))

    store = get_store_by_id(sess["store_id"])
    menu_items = get_menu(store["id"])

    if request.method == "POST":
        # Process order
        items_to_order = []
        for item in menu_items:
            qty_str = request.form.get(f'qty_{item["id"]}')
            if qty_str and qty_str.isdigit():
                qty = int(qty_str)
                if qty > 0:
                    items_to_order.append((item["id"], qty))

        if items_to_order:
            create_session_order(session_id, items_to_order)
            flash("Order placed successfully!")
            return redirect(url_for("auth.view_sessions"))
        else:
            flash("Please select at least one item.")

    # GET: show order form and previous orders
    previous_orders = get_session_orders(session_id)
    return render_template(
        "auth/order.html",
        session=sess,
        store=store,
        menu_items=menu_items,
        previous_orders=previous_orders,
    )


from d20.db.checkout import get_bill as _get_bill_for_user
from d20.db.game import rate_game


@bp.route("/session/<int:session_id>/rate", methods=("GET", "POST"))
@login_required
def rate_session_games(session_id):
    sess = get_session(session_id)
    if not sess or sess["user_id"] != g.user["id"]:
        flash("Session not found.")
        return redirect(url_for("auth.view_sessions"))

    games = get_session_games(session_id)

    if request.method == "POST":
        any_rated = False
        for game in games:
            game_id = game["game_id"]
            rating_val = request.form.get(f"rating_{game_id}", type=int)
            comment_val = request.form.get(f"comment_{game_id}", "").strip() or None
            if rating_val and 1 <= rating_val <= 5:
                try:
                    rate_game(g.user["id"], game_id, rating_val, comment_val)
                    any_rated = True
                except Exception:
                    pass  # Already rated — ignore duplicate
        if any_rated:
            from d20.db.loyalty import add_points, get_point_rule
            add_points(g.user["id"], sess["store_id"], int(get_point_rule(sess["store_id"], "game_rating")))
            flash("Ratings submitted! You earned loyalty points.")
        else:
            flash("Please select at least one rating (1–5).")
        return redirect(url_for("auth.view_sessions"))

    return render_template(
        "auth/rate_session.html",
        sess=sess,
        games=games,
    )


@bp.route("/loyalty")
@login_required
def view_loyalty():
    from d20.db.loyalty import REDEMPTION_RATE
    from d20.db.voucher import get_customer_vouchers, REWARD_TYPE_LABELS
    db = get_db()
    points_rows = db.execute(
        """
        SELECT lp.store_id, s.name as store_name, lp.points, lp.tier_code
        FROM LoyaltyPoint lp
        JOIN Store s ON lp.store_id = s.id
        WHERE lp.user_id = %s
        ORDER BY s.name ASC
        """,
        (g.user["id"],)
    ).fetchall()

    all_vouchers = get_customer_vouchers(g.user["id"])

    return render_template(
        "auth/loyalty.html",
        points=points_rows,
        redemption_rate=REDEMPTION_RATE,
        all_vouchers=all_vouchers,
        reward_type_labels=REWARD_TYPE_LABELS,
    )


@bp.route("/loyalty/<int:store_id>/how-it-works")
@login_required
def view_loyalty_policy(store_id):
    from d20.db.loyalty import REDEMPTION_RATE

    default_back_url = url_for("auth.view_loyalty")
    back_url = request.args.get("next") or default_back_url
    if not back_url.startswith("/") or back_url.startswith("//"):
        back_url = default_back_url
    back_label = "Back to My Loyalty Points"
    if back_url == url_for("stores.store_loyalty", store_id=store_id):
        back_label = "Back to Loyalty Rewards"
    elif back_url != default_back_url:
        back_label = "Back"

    db = get_db()
    store = db.execute(
        """
        SELECT s.id, s.name,
               COALESCE(lp.points, 0) AS points,
               COALESCE(lp.tier_code, 'Bronze') AS tier_code
        FROM Store s
        LEFT JOIN LoyaltyPoint lp
          ON lp.store_id = s.id
         AND lp.user_id = %s
        WHERE s.id = %s
        """,
        (g.user["id"], store_id),
    ).fetchone()
    if store is None:
        flash("Store not found.")
        return redirect(url_for("auth.view_loyalty"))

    point_rules = db.execute(
        """
        SELECT action_code, points_per_unit
        FROM LoyaltyPointRule
        WHERE store_id = %s
        ORDER BY CASE action_code
            WHEN 'session_hour' THEN 1
            WHEN 'food_dollar' THEN 2
            WHEN 'game_rating' THEN 3
            WHEN 'tournament_participation' THEN 4
            ELSE 5
        END
        """,
        (store_id,),
    ).fetchall()
    tiers = db.execute(
        """
        SELECT code, min_points, discount_percent, reservation_advance_days, free_tournament_entries
        FROM LoyaltyTier
        WHERE store_id = %s
        ORDER BY min_points ASC
        """,
        (store_id,),
    ).fetchall()

    return render_template(
        "auth/loyalty_policy.html",
        store=store,
        point_rules=point_rules,
        tiers=tiers,
        redemption_rate=REDEMPTION_RATE,
        back_url=back_url,
        back_label=back_label,
    )


@bp.route("/loyalty/redeem", methods=("POST",))
@login_required
def redeem_loyalty_points():
    from d20.db.loyalty import redeem_points
    store_id = request.form.get("store_id", type=int)
    points = request.form.get("points", type=int)
    description = request.form.get("description", "Discount")
    
    if not store_id or not points or points <= 0:
        flash("Invalid request. Please provide a valid store and points amount.")
        return redirect(url_for("auth.view_loyalty"))
        
    try:
        discount = redeem_points(g.user["id"], store_id, points, description)
        flash(f"Redeemed {points} points for a ${discount:.2f} discount!")
    except ValueError as e:
        flash(str(e))
    except Exception as e:
        flash(f"An error occurred: {str(e)}")
        
    return redirect(url_for("auth.view_loyalty"))
