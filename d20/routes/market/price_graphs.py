from flask import g, render_template

from d20.db.market.market_history import get_historical_game_prices

from . import bp, market_login_required


@bp.route("/price-graphs", methods=("GET",))
@market_login_required
def price_graphs():
    price_data = get_historical_game_prices()

    games_data = {}
    for row in price_data:
        game_id = row["game_id"]
        if game_id not in games_data:
            games_data[game_id] = {
                "name": row["name"],
                "prices": []
            }
        games_data[game_id]["prices"].append({
            "timestamp": row["timestamp"],
            "price": float(row["price"])
        })

    return render_template(
        "market/price_graphs.html",
        active_tab="price_graphs",
        games_data=games_data,
    )
