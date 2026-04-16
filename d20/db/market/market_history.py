from datetime import datetime

from d20.db import get_db


def create_trade(
    buy_order_id, sell_order_id, buyer_id, seller_id, execution_price, quantity
):
    """Record a completed trade (fill).

    Args:
        buy_order_id: ID of the buy order
        sell_order_id: ID of the sell order
        buyer_id: Participant ID of the buyer
        seller_id: Participant ID of the seller
        execution_price: Price at which the trade executed
        quantity: Number of units traded

    Returns:
        1 on success
    """
    db = get_db()
    db.execute(
        """insert into MarketHistory
           (buy_order_id, sell_order_id, buyer_id, seller_id, execution_price, quantity, executed_at)
           values (?, ?, ?, ?, ?, ?, ?)""",
        (
            buy_order_id,
            sell_order_id,
            buyer_id,
            seller_id,
            execution_price,
            quantity,
            datetime.now().isoformat(),
        ),
    )
    db.commit()
    return 1


def get_trade(buy_order_id, sell_order_id):
    """Get a trade by its order IDs (composite primary key)."""
    return (
        get_db()
        .execute(
            "select * from MarketHistory where buy_order_id = ? and sell_order_id = ?",
            (buy_order_id, sell_order_id),
        )
        .fetchone()
    )


def get_trades_by_participant(participant_id):
    """Get all trades involving a participant (as buyer or seller), most recent first."""
    return (
        get_db()
        .execute(
            """select * from MarketHistory
               where buyer_id = ? or seller_id = ?
               order by executed_at desc""",
            (participant_id, participant_id),
        )
        .fetchall()
    )


def get_trades_as_buyer(participant_id):
    """Get all trades where participant was the buyer."""
    return (
        get_db()
        .execute(
            "select * from MarketHistory where buyer_id = ? order by executed_at desc",
            (participant_id,),
        )
        .fetchall()
    )


def get_trades_as_seller(participant_id):
    """Get all trades where participant was the seller."""
    return (
        get_db()
        .execute(
            "select * from MarketHistory where seller_id = ? order by executed_at desc",
            (participant_id,),
        )
        .fetchall()
    )


def get_trades_by_game(game_id):
    """Get all trades for a specific game (joined with order data).

    Note: Requires join with Orders table to filter by game_id.
    """
    return (
        get_db()
        .execute(
            """select MarketHistory.*, Orders.game_id
               from MarketHistory
               join Orders on (MarketHistory.buy_order_id = Orders.id or MarketHistory.sell_order_id = Orders.id)
               where Orders.game_id = ?
               order by MarketHistory.executed_at desc""",
            (game_id,),
        )
        .fetchall()
    )


def get_all_trades():
    """Get all trades, most recent first."""
    return (
        get_db()
        .execute("select * from MarketHistory order by executed_at desc")
        .fetchall()
    )


def get_trades_by_date_range(start_date, end_date):
    """Get trades within a date range (ISO format strings)."""
    return (
        get_db()
        .execute(
            "select * from MarketHistory where executed_at >= ? and executed_at <= ? order by executed_at desc",
            (start_date, end_date),
        )
        .fetchall()
    )


def get_trade_volume_by_game(game_id):
    """Get total volume (quantity) traded for a game."""
    result = (
        get_db()
        .execute(
            """select sum(quantity) as total_volume
               from MarketHistory
               join Orders on (MarketHistory.buy_order_id = Orders.id or MarketHistory.sell_order_id = Orders.id)
               where Orders.game_id = ?""",
            (game_id,),
        )
        .fetchone()
    )
    return result["total_volume"] or 0


def get_average_price_by_game(game_id):
    """Get average execution price for a game."""
    result = (
        get_db()
        .execute(
            """select avg(execution_price) as avg_price
               from MarketHistory
               join Orders on (MarketHistory.buy_order_id = Orders.id or MarketHistory.sell_order_id = Orders.id)
               where Orders.game_id = ?""",
            (game_id,),
        )
        .fetchone()
    )
    return result["avg_price"] or 0


def delete_trade(buy_order_id, sell_order_id):
    """Delete a trade record (use with caution - this is essentially untrading)."""
    db = get_db()
    db.execute(
        "delete from MarketHistory where buy_order_id = ? and sell_order_id = ?",
        (buy_order_id, sell_order_id),
    )
    db.commit()
