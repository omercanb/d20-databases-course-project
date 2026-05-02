import pytest

from d20.db.market.market_history import get_trades_by_participant
from d20.db.market.market_participant import (
    create_market_participant,
    get_market_participant,
)
from d20.db.market.orders import cancel_order, create_order, get_order, try_match_order
from d20.db.market.participant_inventory import (
    create_participant_inventory,
    get_participant_inventory_for_game,
)


def make_participants(game_id=1):
    """Create buyer and seller with initial cash. Inventory auto-creates on first order."""
    buyer_id = create_market_participant(customer_id=1, available_cash=100000.0)
    seller_id = create_market_participant(customer_id=2, available_cash=0.0)
    # Pre-create seller inventory with 10 available units
    create_participant_inventory(
        seller_id, game_id, available_quantity=10, reserved_quantity=0
    )
    return buyer_id, seller_id


def test_limit_buy_matches_sell(app):
    """Buyer BUY LIMIT matches seller SELL LIMIT at same price."""
    with app.app_context():
        buyer_id, seller_id = make_participants()

        # Seller places SELL LIMIT at $10 for 5 units (reserves 5 inventory)
        sell_order_id, _, _ = create_order(
            participant_id=seller_id,
            game_id=1,
            order_type="LIMIT",
            side="SELL",
            price=10.0,
            initial_quantity=5,
        )

        # Buyer places BUY LIMIT at $10 for 5 units (reserves $50 cash, auto-matches)
        buy_order_id, num_fills, error = create_order(
            participant_id=buyer_id,
            game_id=1,
            order_type="LIMIT",
            side="BUY",
            price=10.0,
            initial_quantity=5,
        )
        assert error is False
        assert num_fills == 5

        # Verify orders are COMPLETED
        buy = get_order(buy_order_id)
        sell = get_order(sell_order_id)
        assert buy["status"] == "COMPLETED"
        assert sell["status"] == "COMPLETED"
        assert buy["filled_quantity"] == 5
        assert sell["filled_quantity"] == 5

        # Verify inventory transferred
        buyer_inv = get_participant_inventory_for_game(buyer_id, 1)
        seller_inv = get_participant_inventory_for_game(seller_id, 1)
        assert buyer_inv["available_quantity"] == 5
        assert seller_inv["reserved_quantity"] == 0

        # Verify cash transferred (seller gets $50 at $10/unit)
        seller = get_market_participant(seller_id)
        buyer = get_market_participant(buyer_id)
        assert seller["available_cash"] == 50.0
        assert buyer["reserved_cash"] == 0.0

        # Verify trade recorded
        trades = get_trades_by_participant(buyer_id)
        assert len(trades) == 1
        assert trades[0]["execution_price"] == 10.0
        assert trades[0]["quantity"] == 5


def test_limit_sell_matches_buy(app):
    """Seller SELL LIMIT matches buyer BUY LIMIT. Execution at buyer's price (passive)."""
    with app.app_context():
        buyer_id, seller_id = make_participants()

        # Buyer places BUY LIMIT at $15 for 3 units (reserves $45 cash)
        buy_order_id, _, _ = create_order(
            participant_id=buyer_id,
            game_id=1,
            order_type="LIMIT",
            side="BUY",
            price=15.0,
            initial_quantity=3,
        )

        # Seller places SELL LIMIT at $12 for 3 units (reserves 3 inventory, auto-matches)
        sell_order_id, num_fills, error = create_order(
            participant_id=seller_id,
            game_id=1,
            order_type="LIMIT",
            side="SELL",
            price=12.0,
            initial_quantity=3,
        )
        assert error is False
        assert num_fills == 3

        # Verify both COMPLETED
        buy = get_order(buy_order_id)
        sell = get_order(sell_order_id)
        assert buy["status"] == "COMPLETED"
        assert sell["status"] == "COMPLETED"

        # Verify execution price is buyer's price (passive pricing)
        seller = get_market_participant(seller_id)
        buyer = get_market_participant(buyer_id)
        assert seller["available_cash"] == 45.0  # 3 * $15
        assert buyer["reserved_cash"] == 0.0

        # Verify inventory
        buyer_inv = get_participant_inventory_for_game(buyer_id, 1)
        assert buyer_inv["available_quantity"] == 3

        # Verify trade at buyer's price
        trades = get_trades_by_participant(seller_id)
        assert len(trades) == 1
        assert trades[0]["execution_price"] == 15.0


def test_market_buy_matches_sell(app):
    """Buyer MARKET order matches seller SELL LIMIT. Not enough liquidity, so order is cancelled."""
    with app.app_context():
        buyer_id, seller_id = make_participants()

        # Seller places SELL LIMIT at $8 for 4 units (reserves 4 inventory)
        sell_order_id, _, _ = create_order(
            participant_id=seller_id,
            game_id=1,
            order_type="LIMIT",
            side="SELL",
            price=8.0,
            initial_quantity=4,
        )

        # Buyer places BUY MARKET for 8 units (only 4 available, so partial fill then cancelled)
        buy_order_id, num_fills, error = create_order(
            participant_id=buyer_id,
            game_id=1,
            order_type="MARKET",
            side="BUY",
            price=None,
            initial_quantity=8,
        )
        assert error is False
        assert num_fills == 4

        # Verify buy is CANCELLED (not enough liquidity), sell is COMPLETED
        buy = get_order(buy_order_id)
        sell = get_order(sell_order_id)
        assert buy["status"] == "CANCELLED"
        assert sell["status"] == "COMPLETED"

        # Verify execution at seller's price ($8)
        seller = get_market_participant(seller_id)
        assert seller["available_cash"] == 32.0  # 4 * $8

        # Verify trade
        trades = get_trades_by_participant(buyer_id)
        assert len(trades) == 1
        assert trades[0]["execution_price"] == 8.0


def test_market_sell_matches_buy(app):
    """Seller MARKET order matches buyer BUY LIMIT. Execution at buyer's price."""
    with app.app_context():
        buyer_id, seller_id = make_participants()

        # Buyer places BUY LIMIT at $20 for 2 units (reserves $40 cash)
        buy_order_id, _, _ = create_order(
            participant_id=buyer_id,
            game_id=1,
            order_type="LIMIT",
            side="BUY",
            price=20.0,
            initial_quantity=2,
        )

        # Seller places SELL MARKET for 2 units (auto-matches)
        sell_order_id, num_fills, error = create_order(
            participant_id=seller_id,
            game_id=1,
            order_type="MARKET",
            side="SELL",
            price=None,
            initial_quantity=2,
        )
        assert error is False
        assert num_fills == 2

        # Verify both COMPLETED
        buy = get_order(buy_order_id)
        sell = get_order(sell_order_id)
        assert buy["status"] == "COMPLETED"
        assert sell["status"] == "COMPLETED"

        # Verify execution at buyer's price ($20)
        seller = get_market_participant(seller_id)
        assert seller["available_cash"] == 40.0  # 2 * $20

        # Verify trade
        trades = get_trades_by_participant(seller_id)
        assert len(trades) == 1
        assert trades[0]["execution_price"] == 20.0


def test_partial_fill(app):
    """Buyer BUY LIMIT only partially filled (not enough inventory available)."""
    with app.app_context():
        buyer_id, seller_id = make_participants()

        # Seller places SELL LIMIT at $10 for 3 units (reserves 3 inventory)
        sell_order_id, _, _ = create_order(
            participant_id=seller_id,
            game_id=1,
            order_type="LIMIT",
            side="SELL",
            price=10.0,
            initial_quantity=3,
        )

        # Buyer places BUY LIMIT at $10 for 5 units (more than available, auto-matches)
        buy_order_id, num_fills, error = create_order(
            participant_id=buyer_id,
            game_id=1,
            order_type="LIMIT",
            side="BUY",
            price=10.0,
            initial_quantity=5,
        )
        assert error is False
        assert num_fills == 3

        # Match the new buy order
        try_match_order(buy_order_id)

        # Verify buy is PARTIAL (3 of 5 filled)
        buy = get_order(buy_order_id)
        sell = get_order(sell_order_id)
        assert buy["status"] == "PARTIAL"
        assert buy["filled_quantity"] == 3
        assert sell["status"] == "COMPLETED"
        assert sell["filled_quantity"] == 3

        # Verify only 3 units transferred
        buyer_inv = get_participant_inventory_for_game(buyer_id, 1)
        assert buyer_inv["available_quantity"] == 3


def test_no_match_price_mismatch(app):
    """Buy LIMIT at $10 does NOT match sell LIMIT at $20 (price mismatch)."""
    with app.app_context():
        buyer_id, seller_id = make_participants()

        # Seller places SELL LIMIT at $20 for 5 units (reserves 5 inventory)
        sell_order_id, _, _ = create_order(
            participant_id=seller_id,
            game_id=1,
            order_type="LIMIT",
            side="SELL",
            price=20.0,
            initial_quantity=5,
        )

        # Buyer places BUY LIMIT at $10 for 5 units (below seller's ask, no match)
        buy_order_id, num_fills, error = create_order(
            participant_id=buyer_id,
            game_id=1,
            order_type="LIMIT",
            side="BUY",
            price=10.0,
            initial_quantity=5,
        )
        assert error is False
        assert num_fills == 0

        # Match the new buy order
        try_match_order(buy_order_id)

        # Verify neither order matched
        buy = get_order(buy_order_id)
        sell = get_order(sell_order_id)
        assert buy["status"] == "OPEN"
        assert buy["filled_quantity"] == 0
        assert sell["status"] == "OPEN"
        assert sell["filled_quantity"] == 0

        # Verify no inventory transferred
        buyer_inv = get_participant_inventory_for_game(buyer_id, 1)
        seller_inv = get_participant_inventory_for_game(seller_id, 1)
        # Buyer should have no inventory entry (never received goods)
        assert buyer_inv is None
        # Seller should still have all 5 reserved
        assert seller_inv["reserved_quantity"] == 5
        assert seller_inv["available_quantity"] == 5

        # Verify no trades
        trades = get_trades_by_participant(buyer_id)
        assert len(trades) == 0


def test_cancel_buy_order(app):
    """Cancel a BUY order returns reserved cash to available."""
    with app.app_context():
        buyer_id, seller_id = make_participants()

        # Buyer places BUY LIMIT at $10 for 5 units (reserves $50 cash)
        buy_order_id, _, _ = create_order(
            participant_id=buyer_id,
            game_id=1,
            order_type="LIMIT",
            side="BUY",
            price=10.0,
            initial_quantity=5,
        )

        # Verify cash is reserved
        buyer_before = get_market_participant(buyer_id)
        assert buyer_before["available_cash"] == 100000.0 - 50.0  # 50 reserved
        assert buyer_before["reserved_cash"] == 50.0

        # Cancel the order
        cancel_order(buy_order_id)

        # Verify order is cancelled
        buy = get_order(buy_order_id)
        assert buy["status"] == "CANCELLED"

        # Verify cash is returned to available
        buyer_after = get_market_participant(buyer_id)
        assert buyer_after["available_cash"] == 100000.0  # All available again
        assert buyer_after["reserved_cash"] == 0.0


def test_cancel_sell_order(app):
    """Cancel a SELL order returns reserved inventory to available."""
    with app.app_context():
        buyer_id, seller_id = make_participants()

        # Seller places SELL LIMIT at $10 for 5 units (reserves 5 inventory)
        sell_order_id, _, _ = create_order(
            participant_id=seller_id,
            game_id=1,
            order_type="LIMIT",
            side="SELL",
            price=10.0,
            initial_quantity=5,
        )

        # Verify inventory is reserved
        seller_inv_before = get_participant_inventory_for_game(seller_id, 1)
        assert seller_inv_before["available_quantity"] == 5  # 10 - 5 reserved
        assert seller_inv_before["reserved_quantity"] == 5

        # Cancel the order
        cancel_order(sell_order_id)

        # Verify order is cancelled
        sell = get_order(sell_order_id)
        assert sell["status"] == "CANCELLED"

        # Verify inventory is returned to available
        seller_inv_after = get_participant_inventory_for_game(seller_id, 1)
        assert seller_inv_after["available_quantity"] == 10  # All available again
        assert seller_inv_after["reserved_quantity"] == 0
