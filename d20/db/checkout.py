from d20.db import get_db

# Hourly base table fee per session
TABLE_HOURLY_RATE = 5.00
DAMAGE_FEE_AMOUNT = 25.00  # flat fee per damaged/missing-pieces game copy


def checkout_session(session_id, game_conditions):
    """
    Perform checkout for a session.
    game_conditions: list of dicts {game_id, store_id, copy_num, condition}
    Returns the generated bill dict.
    """
    db = get_db()

    # 1. Fetch session
    sess = db.execute(
        "SELECT * FROM Session WHERE id = %s AND checkout_status = 'active'",
        (session_id,)
    ).fetchone()
    if sess is None:
        raise ValueError("Session not found or already checked out.")

    # 2. Update game conditions and log damage if needed
    damage_fee = 0.0
    for gc in game_conditions:
        condition = gc["condition"]
        game_id = gc["game_id"]
        store_id = gc["store_id"]
        copy_num = gc["copy_num"]
        description = gc.get("description", "")

        # Update game copy condition
        db.execute(
            "UPDATE GameCopy SET condition = %s WHERE game_id = %s AND store_id = %s AND copy_num = %s",
            (condition, game_id, store_id, copy_num)
        )

        # If damaged or missing, log incident and charge fee
        if condition in ("damaged", "missing_pieces"):
            db.execute(
                """
                INSERT INTO GameDamage (session_id, game_id, store_id, copy_num, description)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (session_id, game_id, store_id, copy_num) DO UPDATE
                SET description = EXCLUDED.description
                """,
                (session_id, game_id, store_id, copy_num, description)
            )
            damage_fee += DAMAGE_FEE_AMOUNT

    # 3. Calculate table fee (hourly rate × hours)
    hours = int(sess["end_time"]) - int(sess["start_time"])
    table_fee = round(TABLE_HOURLY_RATE * hours, 2)

    # 4. Sum food/drink orders
    food_row = db.execute(
        "SELECT COALESCE(SUM(total_amount), 0) AS food_total FROM SessionOrder WHERE session_id = %s",
        (session_id,)
    ).fetchone()
    food_total = round(float(food_row["food_total"]), 2)

    grand_total = round(table_fee + food_total + damage_fee, 2)

    # 5. Generate bill
    bill = db.execute(
        """
        INSERT INTO Bill (session_id, table_fee, food_total, damage_fee, grand_total)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING *
        """,
        (session_id, table_fee, food_total, damage_fee, grand_total)
    ).fetchone()

    # 6. Mark session as checked out
    db.execute(
        "UPDATE Session SET checkout_status = 'checked_out' WHERE id = %s",
        (session_id,)
    )

    db.commit()
    return dict(bill)


def get_bill(session_id):
    db = get_db()
    row = db.execute(
        "SELECT * FROM Bill WHERE session_id = %s", (session_id,)
    ).fetchone()
    return dict(row) if row else None


def get_session_game_copies(session_id):
    """Return all game copies booked in this session for condition logging."""
    db = get_db()
    rows = db.execute(
        """
        SELECT sgc.game_id, sgc.store_id, sgc.copy_num,
               gc.condition, g.name AS game_name
        FROM SessionGameCopy sgc
        JOIN GameCopy gc ON (sgc.game_id = gc.game_id AND sgc.store_id = gc.store_id AND sgc.copy_num = gc.copy_num)
        JOIN Game g ON (sgc.game_id = g.id)
        WHERE sgc.session_id = %s
        """,
        (session_id,)
    ).fetchall()
    return [dict(r) for r in rows]
