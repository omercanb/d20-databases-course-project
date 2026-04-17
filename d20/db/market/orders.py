import operator
from datetime import datetime
from typing import Literal

from d20.db import get_db
from d20.db.game import get_game
from d20.db.market.market_history import record_trade
from d20.db.market.market_participant import (
    decrement_available_cash,
    decrement_reserved_cash,
    get_market_participant,
    increment_available_cash,
    increment_reserved_cash,
)
from d20.db.market.participant_inventory import (
    decrement_available_quantity,
    decrement_reserved_quantity,
    get_participant_inventory_for_game,
    increment_available_quantity,
    increment_reserved_quantity,
)


def create_order(
    participant_id,
    game_id,
    order_type: Literal["LIMIT", "MARKET"],
    side: Literal["BUY", "SELL"],
    price,
    initial_quantity,
):
    """Create a new order and reserve the required cash or inventory.

    Args:
        participant_id: Market participant placing the order
        game_id: Game being traded
        order_type: 'LIMIT' or 'MARKET'
        side: 'BUY' or 'SELL'
        price: Price per unit (None for MARKET orders)
        initial_quantity: Total quantity requested

    Returns:
        The ID of the newly created order

    Raises:
        ValueError: If participant doesn't have enough available cash/inventory
    """
    participant = get_market_participant(participant_id)
    if not participant:
        raise ValueError(f"Participant {participant_id} not found")

    # Reserve resources based on order side
    if side == "SELL":
        # For SELL orders, reserve inventory
        inventory = get_participant_inventory_for_game(participant_id, game_id)
        current_available = inventory["available_quantity"] if inventory else 0
        if current_available < initial_quantity:
            raise ValueError(
                f"Cannot sell {initial_quantity} units. Only {current_available} available."
            )
        decrement_available_quantity(participant_id, game_id, initial_quantity)
        increment_reserved_quantity(participant_id, game_id, initial_quantity)
    else:  # side == "BUY"
        # For BUY orders, reserve cash
        # Use worst-case price for MARKET orders (assume max reasonable price)
        if order_type == "MARKET":
            # For market orders, require enough cash for a reasonable upper bound
            # In practice, this should be validated at the route level
            required_cash = initial_quantity * 1000.0  # Arbitrary high price
        else:
            required_cash = initial_quantity * price

        if participant["availiable_cash"] < required_cash:
            raise ValueError(
                f"Cannot buy {initial_quantity} units at ${price}. Only ${participant['availiable_cash']:.2f} available."
            )
        decrement_available_cash(participant_id, required_cash)
        increment_reserved_cash(participant_id, required_cash)

    # Create the order record
    db = get_db()
    game_symbol = get_game(game_id)["symbol"]  # The symbol name that's traded
    cursor = db.execute(
        """insert into Orders
           (participant_id, game_id, game_symbol, order_type, side, price, initial_quantity, filled_quantity, status, created_at)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            participant_id,
            game_id,
            game_symbol,
            order_type,
            side,
            price,
            initial_quantity,
            0,
            "OPEN",
            datetime.now().isoformat(),
        ),
    )
    db.commit()
    return cursor.lastrowid


def try_match_order(order_id):
    """Used for a newly created order to try to match it with an order of the other side"""
    order = get_order(order_id)
    game_id = order["game_id"]
    side = order["side"]
    # buys match with sell and sells match with buy
    # fetch the opposite order type (sorted increasing for buys and decreasing for sells (plus earliness))
    if side == "BUY":
        possible_matches = get_sell_orders(game_id)
        # price is matching is a comparator function to be later used to check against possible matching prices
        price_is_matching = operator.ge
    else:
        possible_matches = get_buy_orders(game_id)
        price_is_matching = operator.le
    # We simulate a market order with an order with the most flexible price range possible
    # The price limit is the price that needs to match
    order_type = order["order_type"]
    if order_type == "MARKET":
        if side == "BUY":
            price_limit = float("inf")
        else:  # side == "SELL"
            price_limit = 0
    else:
        price_limit = order["price"]

    # The total matches needed for completion
    remaining_matches_for_completion = order["initial_quantity"]
    # match all that match until the quantity is fulfilled or no more matches can be considered
    matches = []
    for possible_match in possible_matches:
        match_price = possible_match["price"]
        remaining_quantity_for_possible_match = (
            possible_match["initial_quantity"] - possible_match["filled_quantity"]
        )
        if price_is_matching(price_limit, match_price):
            if remaining_quantity_for_possible_match < remaining_matches_for_completion:
                # the quantity of the possible match is not enough to complete the order
                remaining_matches_for_completion -= (
                    remaining_quantity_for_possible_match
                )
                matches.append(
                    (possible_match["id"], remaining_quantity_for_possible_match)
                )
            else:
                # the order is fully completed
                matches.append((possible_match["id"], remaining_matches_for_completion))
                remaining_matches_for_completion = 0
                break

    # if all requested quantity is handled the it's a complete order otherwise its a partial order
    # all fills then need to go towards updating the rows and need to be added to history
    # we have like a list of fills that happened (which can also be empty and probabbly won't be too long)
    total_fills = 0
    for matched_order_id, num_fills in matches:
        # We need to set transfer direction based on wether this was a buy or sell order
        if side == "BUY":
            buyer = order["participant_id"]
            seller = get_order(matched_order_id)["participant_id"]
        else:
            buyer = get_order(matched_order_id)["participant_id"]
            seller = order["participant_id"]

        total_fills += num_fills
        matched_order = get_order(matched_order_id)
        # The order rows themselves are updated
        add_fills(matched_order_id, num_fills)
        add_fills(order_id, num_fills)
        # If you are selling you have reserved inventory
        # If you are buying you have reserved cash
        # Inventory updated
        decrement_reserved_quantity(seller, game_id, num_fills)
        increment_available_quantity(buyer, game_id, num_fills)
        # Execution price determined as the resting orders price
        execution_price = matched_order["price"]
        total_cost = execution_price * num_fills
        # Money updated
        increment_available_cash(seller, total_cost)
        decrement_reserved_cash(buyer, total_cost)

        # A trade is added to history
        if side == "BUY":
            buy_order_id = order_id
            sell_order_id = matched_order_id
        else:
            buy_order_id = matched_order_id
            sell_order_id = order_id
        record_trade(
            buy_order_id, sell_order_id, buyer, seller, execution_price, num_fills
        )

    # If we have a market order and don't have enough liqudity we fill what we can then cancel the order
    if order_type == "MARKET" and remaining_matches_for_completion > 0:
        cancel_order(order_id)

    return total_fills


def get_order(order_id):
    """Get an order by ID."""
    return get_db().execute("select * from Orders where id = ?", (order_id,)).fetchone()


def get_orders_by_participant(participant_id):
    """Get all orders for a participant, most recent first."""
    return (
        get_db()
        .execute(
            "select * from Orders where participant_id = ? order by created_at desc",
            (participant_id,),
        )
        .fetchall()
    )


def get_active_orders_by_participant(participant_id):
    return (
        get_db()
        .execute(
            "select * from Orders where participant_id = ? and status in ('OPEN', 'PARTIAL') order by created_at desc",
            (participant_id,),
        )
        .fetchall()
    )


def get_inactive_orders_by_participant(participant_id):
    return (
        get_db()
        .execute(
            "select * from Orders where participant_id = ? and status not in ('OPEN', 'PARTIAL') order by created_at desc",
            (participant_id,),
        )
        .fetchall()
    )


def get_orders_by_participant_and_game(participant_id, game_id):
    """Get all orders for a participant for a specific game."""
    return (
        get_db()
        .execute(
            "select * from Orders where participant_id = ? and game_id = ? order by created_at desc",
            (participant_id, game_id),
        )
        .fetchall()
    )


def get_open_orders(participant_id=None):
    """Get all OPEN or PARTIAL orders. If participant_id is provided, only their orders."""
    if participant_id:
        return (
            get_db()
            .execute(
                "select * from Orders where participant_id = ? and status in ('OPEN', 'PARTIAL') order by created_at asc",
                (participant_id,),
            )
            .fetchall()
        )
    else:
        return (
            get_db()
            .execute(
                "select * from Orders where status in ('OPEN', 'PARTIAL') order by created_at asc"
            )
            .fetchall()
        )


def get_buy_orders(game_id, participant_id=None):
    """Get all open BUY orders for a game. Used for order matching."""
    if participant_id:
        return (
            get_db()
            .execute(
                "select * from Orders where game_id = ? and side = 'BUY' and status in ('OPEN', 'PARTIAL') and participant_id = ? order by price desc, created_at asc",
                (game_id, participant_id),
            )
            .fetchall()
        )
    else:
        return (
            get_db()
            .execute(
                "select * from Orders where game_id = ? and side = 'BUY' and status in ('OPEN', 'PARTIAL') order by price desc, created_at asc",
                (game_id,),
            )
            .fetchall()
        )


def get_sell_orders(game_id, participant_id=None):
    """Get all open SELL orders for a game. Used for order matching."""
    if participant_id:
        return (
            get_db()
            .execute(
                "select * from Orders where game_id = ? and side = 'SELL' and status in ('OPEN', 'PARTIAL') and participant_id = ? order by price asc, created_at asc",
                (game_id, participant_id),
            )
            .fetchall()
        )
    else:
        return (
            get_db()
            .execute(
                "select * from Orders where game_id = ? and side = 'SELL' and status in ('OPEN', 'PARTIAL') order by price asc, created_at asc",
                (game_id,),
            )
            .fetchall()
        )


def get_orders_by_status(status):
    """Get all orders with a specific status."""
    return (
        get_db()
        .execute(
            "select * from Orders where status = ? order by created_at desc", (status,)
        )
        .fetchall()
    )


def update_order_status(order_id, status):
    """Update order status."""
    db = get_db()
    db.execute("update Orders set status = ? where id = ?", (status, order_id))
    db.commit()


def add_fills(order_id, quantity_to_add):
    """Increase the filled quantity of an order. Automatically sets status based on new total fill.

    Args:
        order_id: Order ID to increment
        quantity_to_add: Amount to add to filled_quantity
    """
    order = get_order(order_id)
    if not order:
        raise ValueError(f"Order {order_id} not found")

    new_filled_quantity = order["filled_quantity"] + quantity_to_add

    # Determine new status based on new total fill
    if new_filled_quantity >= order["initial_quantity"]:
        new_status = "COMPLETED"
    elif new_filled_quantity > 0:
        new_status = "PARTIAL"
    else:
        new_status = "OPEN"

    db = get_db()
    db.execute(
        "update Orders set filled_quantity = ?, status = ? where id = ?",
        (new_filled_quantity, new_status, order_id),
    )
    db.commit()


def cancel_order(order_id):
    """Cancel an order."""
    db = get_db()
    db.execute("update Orders set status = 'CANCELLED' where id = ?", (order_id,))
    db.commit()


def delete_order(order_id):
    """Delete an order."""
    db = get_db()
    db.execute("delete from Orders where id = ?", (order_id,))
    db.commit()
