import functools

from datetime import date

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

from flaskr.db import get_db
from flaskr.db.session import (
    delete_session,
    get_session,
    get_session_games,
    get_sessions_with_store_by_user,
)
from flaskr.db.stores import create_store, get_store, get_store_by_id
from flaskr.db.user import create_user, get_user, get_user_by_id

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
        db = get_db()
        error = None

        if not username:
            error = "Username is required."
        elif not store_name:
            error = "Store name is required."
        elif not password:
            error = "Password is required."

        if error is None:
            try:
                create_store(username, store_name, password)
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
        if sess["day"] >= today:
            upcoming.append(sess_dict)
        else:
            past.append(sess_dict)

    return render_template(
        "auth/sessions.html", upcoming_sessions=upcoming, past_sessions=past
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
