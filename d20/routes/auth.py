import functools
from datetime import date
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
    delete_session,
    get_reservation_count,
    get_session,
    get_session_games,
    get_sessions_with_store_by_user,
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

    upcoming = []
    past = []

    for sess in sessions:
        sess_dict = dict(sess)
        sess_dict["games"] = get_session_games(sess["id"])
        if sess["checkout_status"] == "checked_out" or sess["day"] < today:
            past.append(sess_dict)
        else:
            upcoming.append(sess_dict)

    return render_template(
        "auth/sessions.html",
        upcoming_sessions=upcoming,
        past_sessions=past,
        reservation_count=get_reservation_count(g.user["id"]),
        max_reservation_count=MAX_RESERVATIONS,
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
        flash(f"Error cancelling session: {str(e)}")

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
    
    return render_template("auth/loyalty.html", points=points_rows, redemption_rate=REDEMPTION_RATE)


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
