from d20.db import get_db
from decimal import Decimal


def create_market_participant(
    customer_id=None, store_id=None, available_cash=0.0, reserved_cash=0.0
):
    """Create a new market participant (either customer or store).

    Returns:
        The ID of the newly created market participant
    """
    if (customer_id is None and store_id is None) or (
        customer_id is not None and store_id is not None
    ):
        raise ValueError("Exactly one of customer_id or store_id must be provided")

    db = get_db()
    cursor = db.execute(
        "INSERT INTO MarketParticipant (customer_id, store_id, available_cash, reserved_cash)"
        " VALUES (%s, %s, %s, %s) RETURNING id",
        (customer_id, store_id, available_cash, reserved_cash),
    )
    db.commit()
    return cursor.fetchone()["id"]


def get_market_participant(participant_id):
    """Get a market participant by ID."""
    return (
        get_db()
        .execute("SELECT * FROM MarketParticipant WHERE id = %s", (participant_id,))
        .fetchone()
    )


def get_market_participant_by_customer(customer_id):
    """Get a market participant by customer ID."""
    return (
        get_db()
        .execute(
            "SELECT * FROM MarketParticipant WHERE customer_id = %s", (customer_id,)
        )
        .fetchone()
    )


def get_market_participant_by_store(store_id):
    """Get a market participant by store ID."""
    return (
        get_db()
        .execute("SELECT * FROM MarketParticipant WHERE store_id = %s", (store_id,))
        .fetchone()
    )


def increment_available_cash(participant_id, amount):
    """Increase available cash for a participant."""
    participant = get_market_participant(participant_id)
    if not participant:
        raise ValueError(f"Participant {participant_id} not found")

    amount = Decimal(str(amount))
    new_available = participant["available_cash"] + amount

    db = get_db()
    db.execute(
        "UPDATE MarketParticipant SET available_cash = %s WHERE id = %s",
        (new_available, participant_id),
    )
    db.commit()


def decrement_available_cash(participant_id, amount):
    """Decrease available cash for a participant."""
    participant = get_market_participant(participant_id)
    if not participant:
        raise ValueError(f"Participant {participant_id} not found")

    amount = Decimal(str(amount))
    new_available = participant["available_cash"] - amount
    if new_available < 0:
        raise ValueError(
            f"Cannot decrease available cash by ${amount:.2f}. Only ${participant['available_cash']:.2f} available."
        )

    db = get_db()
    db.execute(
        "UPDATE MarketParticipant SET available_cash = %s WHERE id = %s",
        (new_available, participant_id),
    )
    db.commit()


def increment_reserved_cash(participant_id, amount):
    """Increase reserved cash for a participant."""
    participant = get_market_participant(participant_id)
    if not participant:
        raise ValueError(f"Participant {participant_id} not found")

    amount = Decimal(str(amount))
    new_reserved = participant["reserved_cash"] + amount

    db = get_db()
    db.execute(
        "UPDATE MarketParticipant SET reserved_cash = %s WHERE id = %s",
        (new_reserved, participant_id),
    )
    db.commit()


def decrement_reserved_cash(participant_id, amount):
    """Decrease reserved cash for a participant."""
    participant = get_market_participant(participant_id)
    if not participant:
        raise ValueError(f"Participant {participant_id} not found")

    amount = Decimal(str(amount))
    new_reserved = participant["reserved_cash"] - amount
    if new_reserved < 0:
        raise ValueError(
            f"Cannot decrease reserved cash by ${amount:.2f}. Only ${participant['reserved_cash']:.2f} reserved."
        )

    db = get_db()
    db.execute(
        "UPDATE MarketParticipant SET reserved_cash = %s WHERE id = %s",
        (new_reserved, participant_id),
    )
    db.commit()


def delete_market_participant(participant_id):
    """Delete a market participant."""
    db = get_db()
    db.execute("DELETE FROM MarketParticipant WHERE id = %s", (participant_id,))
    db.commit()
