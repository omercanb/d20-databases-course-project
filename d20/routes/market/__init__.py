import functools

from flask import Blueprint, g, redirect, session, url_for

from d20.db.market.market_participant import (
    get_market_participant,
    get_market_participant_by_customer,
    get_market_participant_by_store,
)

bp = Blueprint("market", __name__, url_prefix="/market")


@bp.before_app_request
def load_logged_in_market_participant():
    store_id = session.get("store_id")
    user_id = session.get("user_id")
    participant_data = None

    if store_id is not None:
        participant_data = get_market_participant_by_store(store_id)
    elif user_id is not None:
        participant_data = get_market_participant_by_customer(user_id)

    if participant_data:
        g.market_participant = get_market_participant(participant_data["id"])
    else:
        g.market_participant = None


def market_login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if g.market_participant is None:
            return redirect(url_for("auth.login"))
        return view(**kwargs)

    return wrapped_view


# Import route modules to register them on the blueprint
from . import algorithmic, history, portfolio, scripts_json_endpoints, trading
