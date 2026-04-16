from d20.db import get_db


def create_participant_inventory(
    participant_id, game_id, available_quantity=0, reserved_quantity=0
):
    """Create or initialize market inventory for a participant and game.

    Args:
        participant_id: ID of the market participant
        game_id: ID of the game
        available_quantity: Initial available quantity
        reserved_quantity: Initial reserved quantity
    """
    db = get_db()
    db.execute(
        "insert into MarketParticipantInventory (participant_id, game_id, available_quantity, reserved_quantity) values (?, ?, ?, ?)",
        (participant_id, game_id, available_quantity, reserved_quantity),
    )
    db.commit()


def get_participant_inventory(participant_id):
    """Get all inventory items for a participant."""
    return (
        get_db()
        .execute(
            "select * from MarketParticipantInventory join Game on (game_id = id) where participant_id = ?",
            (participant_id,),
        )
        .fetchall()
    )


def get_participant_inventory_for_game(participant_id, game_id):
    """Get inventory for a specific participant and game."""
    return (
        get_db()
        .execute(
            "select * from MarketParticipantInventory where participant_id = ? and game_id = ?",
            (participant_id, game_id),
        )
        .fetchone()
    )


def get_game_inventory_count(game_id):
    """Get total quantity (available + reserved) of a game across all participants."""
    return (
        get_db()
        .execute(
            "select sum(available_quantity + reserved_quantity) as total from MarketParticipantInventory where game_id = ?",
            (game_id,),
        )
        .fetchone()[0]
    )


def update_available_quantity(participant_id, game_id, quantity):
    """Set the available quantity for a participant's game."""
    db = get_db()
    db.execute(
        "update MarketParticipantInventory set available_quantity = ? where participant_id = ? and game_id = ?",
        (quantity, participant_id, game_id),
    )
    db.commit()


def update_reserved_quantity(participant_id, game_id, quantity):
    """Set the reserved quantity for a participant's game."""
    db = get_db()
    db.execute(
        "update MarketParticipantInventory set reserved_quantity = ? where participant_id = ? and game_id = ?",
        (quantity, participant_id, game_id),
    )
    db.commit()


def update_game_quantity(
    participant_id, game_id, available_quantity, reserved_quantity
):
    """Update both available and reserved quantities."""
    db = get_db()
    db.execute(
        "update MarketParticipantInventory set available_quantity = ?, reserved_quantity = ? where participant_id = ? and game_id = ?",
        (available_quantity, reserved_quantity, participant_id, game_id),
    )
    db.commit()


# def increment_available_quantity(participant_id, game_id, amount):
#     """Add to available quantity (use negative amount to subtract)."""
#     inventory = get_participant_inventory_for_game(participant_id, game_id)
#     if not inventory:
#         raise ValueError(
#             f"Inventory not found for participant {participant_id}, game {game_id}"
#         )
#
#     new_available = inventory["available_quantity"] + amount
#     if new_available < 0:
#         raise ValueError("Available quantity cannot be negative")
#
#     db = get_db()
#     db.execute(
#         "update MarketParticipantInventory set available_quantity = ? where participant_id = ? and game_id = ?",
#         (new_available, participant_id, game_id),
#     )
#     db.commit()
#
#
# def increment_reserved_quantity(participant_id, game_id, amount):
#     """Add to reserved quantity (use negative amount to subtract)."""
#     inventory = get_participant_inventory_for_game(participant_id, game_id)
#     if not inventory:
#         raise ValueError(
#             f"Inventory not found for participant {participant_id}, game {game_id}"
#         )
#
#     new_reserved = inventory["reserved_quantity"] + amount
#     if new_reserved < 0:
#         raise ValueError("Reserved quantity cannot be negative")
#
#     db = get_db()
#     db.execute(
#         "update MarketParticipantInventory set reserved_quantity = ? where participant_id = ? and game_id = ?",
#         (new_reserved, participant_id, game_id),
#     )
#     db.commit()


def delete_market_inventory(participant_id, game_id):
    """Delete inventory entry for a participant and game."""
    db = get_db()
    db.execute(
        "delete from MarketParticipantInventory where participant_id = ? and game_id = ?",
        (participant_id, game_id),
    )
    db.commit()
