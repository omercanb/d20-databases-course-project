from d20.db import get_db


def create_participant_inventory(
    participant_id, game_id, available_quantity=0, reserved_quantity=0
):
    """Create or initialize market inventory for a participant and game."""
    db = get_db()
    db.execute(
        "INSERT INTO MarketParticipantInventory"
        " (participant_id, game_id, available_quantity, reserved_quantity)"
        " VALUES (%s, %s, %s, %s)",
        (participant_id, game_id, available_quantity, reserved_quantity),
    )
    db.commit()


def get_participant_inventory(participant_id):
    """Get all inventory items for a participant."""
    return (
        get_db()
        .execute(
            "SELECT * FROM MarketParticipantInventory JOIN Game ON (game_id = id)"
            " WHERE participant_id = %s",
            (participant_id,),
        )
        .fetchall()
    )


def get_participant_inventory_for_game(participant_id, game_id):
    """Get inventory for a specific participant and game."""
    return (
        get_db()
        .execute(
            "SELECT * FROM MarketParticipantInventory"
            " WHERE participant_id = %s AND game_id = %s",
            (participant_id, game_id),
        )
        .fetchone()
    )


def get_game_inventory_count(game_id):
    """Get total quantity (available + reserved) of a game across all participants."""
    return (
        get_db()
        .execute(
            "SELECT SUM(available_quantity + reserved_quantity) AS total"
            " FROM MarketParticipantInventory WHERE game_id = %s",
            (game_id,),
        )
        .fetchone()["total"]
    )


def update_available_quantity(participant_id, game_id, quantity):
    """Set the available quantity for a participant's game. Auto-creates if doesn't exist."""
    db = get_db()
    inventory = get_participant_inventory_for_game(participant_id, game_id)

    if not inventory:
        db.execute(
            "INSERT INTO MarketParticipantInventory"
            " (participant_id, game_id, available_quantity, reserved_quantity)"
            " VALUES (%s, %s, %s, %s)",
            (participant_id, game_id, quantity, 0),
        )
    else:
        db.execute(
            "UPDATE MarketParticipantInventory SET available_quantity = %s"
            " WHERE participant_id = %s AND game_id = %s",
            (quantity, participant_id, game_id),
        )
        if quantity == 0 and inventory["reserved_quantity"] == 0:
            delete_market_inventory(participant_id, game_id)
            db.commit()
            return

    db.commit()


def update_reserved_quantity(participant_id, game_id, quantity):
    """Set the reserved quantity for a participant's game. Auto-creates if doesn't exist."""
    db = get_db()
    inventory = get_participant_inventory_for_game(participant_id, game_id)

    if not inventory:
        db.execute(
            "INSERT INTO MarketParticipantInventory"
            " (participant_id, game_id, available_quantity, reserved_quantity)"
            " VALUES (%s, %s, %s, %s)",
            (participant_id, game_id, 0, quantity),
        )
    else:
        db.execute(
            "UPDATE MarketParticipantInventory SET reserved_quantity = %s"
            " WHERE participant_id = %s AND game_id = %s",
            (quantity, participant_id, game_id),
        )
        if inventory["available_quantity"] == 0 and quantity == 0:
            delete_market_inventory(participant_id, game_id)
            db.commit()
            return

    db.commit()


def update_game_quantity(
    participant_id, game_id, available_quantity, reserved_quantity
):
    """Update both available and reserved quantities. Auto-creates if doesn't exist."""
    if available_quantity == 0 and reserved_quantity == 0:
        delete_market_inventory(participant_id, game_id)
        return

    db = get_db()
    inventory = get_participant_inventory_for_game(participant_id, game_id)

    if not inventory:
        db.execute(
            "INSERT INTO MarketParticipantInventory"
            " (participant_id, game_id, available_quantity, reserved_quantity)"
            " VALUES (%s, %s, %s, %s)",
            (participant_id, game_id, available_quantity, reserved_quantity),
        )
    else:
        db.execute(
            "UPDATE MarketParticipantInventory"
            " SET available_quantity = %s, reserved_quantity = %s"
            " WHERE participant_id = %s AND game_id = %s",
            (available_quantity, reserved_quantity, participant_id, game_id),
        )

    db.commit()


def increment_available_quantity(participant_id, game_id, amount):
    """Increase available quantity for a participant's game. Auto-creates if doesn't exist."""
    inventory = get_participant_inventory_for_game(participant_id, game_id)
    current_available = inventory["available_quantity"] if inventory else 0

    new_available = current_available + amount
    if new_available < 0:
        raise ValueError("Available quantity cannot be negative")

    update_available_quantity(participant_id, game_id, new_available)


def decrement_available_quantity(participant_id, game_id, amount):
    """Decrease available quantity for a participant's game. Auto-creates if doesn't exist."""
    inventory = get_participant_inventory_for_game(participant_id, game_id)
    current_available = inventory["available_quantity"] if inventory else 0

    new_available = current_available - amount
    if new_available < 0:
        raise ValueError(
            f"Cannot decrease available quantity by {amount}. Only {current_available} available."
        )

    update_available_quantity(participant_id, game_id, new_available)


def increment_reserved_quantity(participant_id, game_id, amount):
    """Increase reserved quantity for a participant's game. Auto-creates if doesn't exist."""
    inventory = get_participant_inventory_for_game(participant_id, game_id)
    current_reserved = inventory["reserved_quantity"] if inventory else 0

    new_reserved = current_reserved + amount
    if new_reserved < 0:
        raise ValueError("Reserved quantity cannot be negative")

    update_reserved_quantity(participant_id, game_id, new_reserved)


def decrement_reserved_quantity(participant_id, game_id, amount):
    """Decrease reserved quantity for a participant's game. Auto-creates if doesn't exist."""
    inventory = get_participant_inventory_for_game(participant_id, game_id)
    current_reserved = inventory["reserved_quantity"] if inventory else 0

    new_reserved = current_reserved - amount
    if new_reserved < 0:
        raise ValueError(
            f"Cannot decrease reserved quantity by {amount}. Only {current_reserved} reserved."
        )

    update_reserved_quantity(participant_id, game_id, new_reserved)


def delete_market_inventory(participant_id, game_id):
    """Delete inventory entry for a participant and game."""
    db = get_db()
    db.execute(
        "DELETE FROM MarketParticipantInventory WHERE participant_id = %s AND game_id = %s",
        (participant_id, game_id),
    )
    db.commit()
