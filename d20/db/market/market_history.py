from datetime import datetime

from d20.db import get_db


def record_trade(
    buy_order_id,
    sell_order_id,
    buyer_id,
    seller_id,
    game_symbol,
    execution_price,
    quantity,
    executed_at=None,
):
    """Record a completed trade (fill).

    Args:
        executed_at: Optional timestamp (defaults to now)

    Returns:
        1 on success
    """
    db = get_db()
    trade_timestamp = executed_at if executed_at else datetime.now().isoformat()
    db.execute(
        "INSERT INTO MarketHistory"
        " (buy_order_id, sell_order_id, buyer_id, seller_id, game_symbol,"
        "  execution_price, quantity, executed_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (
            buy_order_id,
            sell_order_id,
            buyer_id,
            seller_id,
            game_symbol,
            execution_price,
            quantity,
            trade_timestamp,
        ),
    )
    db.commit()
    return 1


def get_trades_by_participant(participant_id):
    """Get all trades involving a participant (as buyer or seller), most recent first."""
    return (
        get_db()
        .execute(
            "SELECT * FROM MarketHistory"
            " WHERE buyer_id = %s OR seller_id = %s"
            " ORDER BY executed_at DESC",
            (participant_id, participant_id),
        )
        .fetchall()
    )


def get_all_trades():
    """Get all trades, most recent first."""
    return (
        get_db()
        .execute("SELECT * FROM MarketHistory ORDER BY executed_at DESC")
        .fetchall()
    )


def get_price(game_symbol):
    """Returns the most recent execution price for a game symbol, or None."""
    row = (
        get_db()
        .execute(
            "SELECT execution_price FROM MarketHistory"
            " WHERE game_symbol = %s ORDER BY executed_at DESC LIMIT 1",
            (game_symbol,),
        )
        .fetchone()
    )
    if row is None:
        return None
    return row["execution_price"]


def get_historical_game_prices():
    """Get all historical game price data grouped by game."""
    return (
        get_db()
        .execute(
            "SELECT hgp.game_id, g.name, hgp.timestamp, hgp.price "
            "FROM historical_game_price hgp "
            "JOIN Game g ON hgp.game_id = g.id "
            "ORDER BY hgp.game_id, hgp.timestamp ASC"
        )
        .fetchall()
    )
