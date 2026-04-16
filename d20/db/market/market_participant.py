from d20.db import get_db


# MarketParticipant Functions
def create_market_participant(
    customer_id=None, store_id=None, available_cash=0.0, reserved_cash=0.0
):
    """Create a new market participant (either customer or store).

    Args:
        customer_id: ID of customer (mutually exclusive with store_id)
        store_id: ID of store (mutually exclusive with customer_id)
        available_cash: Initial available cash
        reserved_cash: Initial reserved cash

    Returns:
        The ID of the newly created market participant
    """
    if (customer_id is None and store_id is None) or (
        customer_id is not None and store_id is not None
    ):
        raise ValueError("Exactly one of customer_id or store_id must be provided")

    db = get_db()
    cursor = db.execute(
        "insert into MarketPariticipant (customer_id, store_id, availiable_cash, reserved_cash) values (?, ?, ?, ?)",
        (customer_id, store_id, available_cash, reserved_cash),
    )
    db.commit()
    return cursor.lastrowid


# TODO I'm sure I will use some of the below commented out functions, but these were generated with claude so I want to make sure we're only keeping the ones we will actually use to not bloat. So I will add as needed
# def get_market_participant(participant_id):
#     """Get a market participant by ID."""
#     return (
#         get_db()
#         .execute("select * from MarketPariticipant where id = ?", (participant_id,))
#         .fetchone()
#     )
#
#
# def get_market_participant_by_customer(customer_id):
#     """Get a market participant by customer ID."""
#     return (
#         get_db()
#         .execute(
#             "select * from MarketPariticipant where customer_id = ?", (customer_id,)
#         )
#         .fetchone()
#     )
#
#
# def get_market_participant_by_store(store_id):
#     """Get a market participant by store ID."""
#     return (
#         get_db()
#         .execute("select * from MarketPariticipant where store_id = ?", (store_id,))
#         .fetchone()
#     )
#
#
# def get_all_market_participants():
#     """Get all market participants."""
#     return get_db().execute("select * from MarketPariticipant").fetchall()
#
#
# def update_market_participant_cash(participant_id, available_cash, reserved_cash):
#     """Update available and reserved cash for a participant."""
#     db = get_db()
#     db.execute(
#         "update MarketPariticipant set availiable_cash = ?, reserved_cash = ? where id = ?",
#         (available_cash, reserved_cash, participant_id),
#     )
#     db.commit()
#
#
# def update_available_cash(participant_id, amount):
#     """Add/subtract from available cash (use negative amount to subtract)."""
#     participant = get_market_participant(participant_id)
#     if not participant:
#         raise ValueError(f"Participant {participant_id} not found")
#
#     new_available = participant["availiable_cash"] + amount
#     if new_available < 0:
#         raise ValueError("Available cash cannot be negative")
#
#     db = get_db()
#     db.execute(
#         "update MarketPariticipant set availiable_cash = ? where id = ?",
#         (new_available, participant_id),
#     )
#     db.commit()
#
#
# def update_reserved_cash(participant_id, amount):
#     """Add/subtract from reserved cash (use negative amount to subtract)."""
#     participant = get_market_participant(participant_id)
#     if not participant:
#         raise ValueError(f"Participant {participant_id} not found")
#
#     new_reserved = participant["reserved_cash"] + amount
#     if new_reserved < 0:
#         raise ValueError("Reserved cash cannot be negative")
#
#     db = get_db()
#     db.execute(
#         "update MarketPariticipant set reserved_cash = ? where id = ?",
#         (new_reserved, participant_id),
#     )
#     db.commit()


def delete_market_participant(participant_id):
    """Delete a market participant."""
    db = get_db()
    db.execute("delete from MarketPariticipant where id = ?", (participant_id,))
    db.commit()
