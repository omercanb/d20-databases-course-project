from d20.db import get_db

# Hourly base table fee per session
TABLE_HOURLY_RATE = 5.00
DAMAGE_FEE_AMOUNT = 25.00  # flat fee per damaged/missing-pieces game copy


def checkout_session(session_id, game_conditions, customer_voucher_id=None):
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

    customer_voucher = None
    if customer_voucher_id is not None:
        from d20.db.voucher import calculate_voucher_discount
        customer_voucher = db.execute(
            """
            SELECT cv.*, lv.reward_type, lv.reward_value
            FROM CustomerVoucher cv
            JOIN LoyaltyVoucher lv
              ON cv.voucher_id = lv.id
             AND cv.store_id = lv.store_id
            WHERE cv.id = %s
              AND cv.user_id = %s
              AND cv.store_id = %s
              AND cv.is_used = FALSE
            """,
            (customer_voucher_id, sess["user_id"], sess["store_id"])
        ).fetchone()
        if customer_voucher is None:
            raise ValueError("Voucher is not valid for this session.")

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

    # 5. Calculate loyalty discounts
    from d20.db.loyalty import REDEMPTION_RATE, calculate_tier_discount
    discount_row = db.execute(
        """
        SELECT COALESCE(SUM(points_spent), 0) as total_points 
        FROM LoyaltyRedemption 
        WHERE user_id = %s AND store_id = %s AND bill_id IS NULL
        """,
        (sess["user_id"], sess["store_id"])
    ).fetchone()
    loyalty_discount = round(float(discount_row["total_points"] * REDEMPTION_RATE), 2)

    subtotal_before_tier = round(table_fee + food_total + damage_fee - loyalty_discount, 2)
    tier_discount, _ = calculate_tier_discount(
        sess["user_id"], sess["store_id"], subtotal_before_tier
    )
    subtotal_before_voucher = round(subtotal_before_tier - tier_discount, 2)
    grand_total = round(max(0.0, subtotal_before_voucher), 2)

    # 5b. Apply voucher discount if provided
    voucher_discount = 0.0
    if customer_voucher is not None:
        voucher_discount = calculate_voucher_discount(
            customer_voucher, table_fee, food_total, subtotal_before_voucher
        )
        if voucher_discount <= 0:
            raise ValueError("Voucher does not apply to this bill.")
        grand_total = round(max(0.0, grand_total - voucher_discount), 2)

    # 6. Generate bill
    bill = db.execute(
        """
        INSERT INTO Bill (session_id, table_fee, food_total, damage_fee, loyalty_discount, tier_discount, voucher_discount, grand_total)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (session_id, table_fee, food_total, damage_fee, loyalty_discount, tier_discount, voucher_discount, grand_total)
    ).fetchone()

    # 7. Mark redemptions as applied
    db.execute(
        "UPDATE LoyaltyRedemption SET bill_id = %s WHERE user_id = %s AND store_id = %s AND bill_id IS NULL",
        (bill["id"], sess["user_id"], sess["store_id"])
    )

    # 7b. Mark voucher as used if applied
    if customer_voucher_id is not None and voucher_discount > 0:
        db.execute(
            """
            UPDATE CustomerVoucher
            SET is_used=TRUE, bill_id=%s, used_at=CURRENT_TIMESTAMP
            WHERE id=%s AND user_id=%s AND store_id=%s AND is_used=FALSE
            """,
            (bill["id"], customer_voucher_id, sess["user_id"], sess["store_id"])
        )

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
