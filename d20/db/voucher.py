from d20.db import get_db

REWARD_TYPE_LABELS = {
    'food': 'Discount on Food & Drinks',
    'session': 'Discount on Table Fee',
    'any': 'Discount on Total Bill',
}


def get_store_vouchers(store_id, active_only=True):
    db = get_db()
    clause = "AND is_active = TRUE" if active_only else ""
    return [dict(r) for r in db.execute(
        f"SELECT * FROM LoyaltyVoucher WHERE store_id = %s {clause} ORDER BY point_cost ASC",
        (store_id,),
    ).fetchall()]


def create_voucher(store_id, name, description, point_cost, reward_type, reward_value):
    db = get_db()
    row = db.execute(
        """
        INSERT INTO LoyaltyVoucher (store_id, name, description, point_cost, reward_type, reward_value)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (store_id, name, description, point_cost, reward_type, reward_value),
    ).fetchone()
    db.commit()
    return row["id"]


def update_voucher(voucher_id, store_id, name, description, point_cost, reward_type, reward_value, is_active):
    db = get_db()
    db.execute(
        """
        UPDATE LoyaltyVoucher
        SET name=%s, description=%s, point_cost=%s, reward_type=%s, reward_value=%s, is_active=%s
        WHERE id=%s AND store_id=%s
        """,
        (name, description, point_cost, reward_type, reward_value, is_active, voucher_id, store_id),
    )
    db.commit()


def delete_voucher(voucher_id, store_id):
    db = get_db()
    db.execute("DELETE FROM LoyaltyVoucher WHERE id=%s AND store_id=%s", (voucher_id, store_id))
    db.commit()


def buy_voucher(user_id, store_id, voucher_id):
    """Deduct points and issue a CustomerVoucher. Returns customer_voucher_id."""
    from d20.db.loyalty import get_user_points
    db = get_db()
    voucher = db.execute(
        "SELECT * FROM LoyaltyVoucher WHERE id=%s AND store_id=%s AND is_active=TRUE",
        (voucher_id, store_id),
    ).fetchone()
    if voucher is None:
        raise ValueError("Voucher not found or no longer available.")
    pts = get_user_points(user_id, store_id)
    if pts < voucher["point_cost"]:
        raise ValueError(f"Insufficient points. You have {pts} pts, need {voucher['point_cost']} pts.")
    updated = db.execute(
        "UPDATE LoyaltyPoint SET points=points-%s WHERE user_id=%s AND store_id=%s AND points>=%s RETURNING points",
        (voucher["point_cost"], user_id, store_id, voucher["point_cost"]),
    ).fetchone()
    if updated is None:
        raise ValueError("Could not deduct points. Please try again.")
    cv = db.execute(
        "INSERT INTO CustomerVoucher (user_id, store_id, voucher_id) VALUES (%s,%s,%s) RETURNING id",
        (user_id, store_id, voucher_id),
    ).fetchone()
    db.commit()
    return cv["id"]


def get_customer_vouchers(user_id, store_id=None):
    db = get_db()
    params = [user_id]
    store_clause = ""
    if store_id:
        store_clause = "AND cv.store_id=%s"
        params.append(store_id)
    return [dict(r) for r in db.execute(
        f"""
        SELECT cv.id, cv.user_id, cv.store_id, cv.is_used, cv.issued_at, cv.used_at, cv.bill_id,
               lv.name AS voucher_name, lv.description AS voucher_description,
               lv.reward_type, lv.reward_value, lv.point_cost,
               s.name AS store_name
        FROM CustomerVoucher cv
        JOIN LoyaltyVoucher lv ON cv.voucher_id=lv.id AND cv.store_id=lv.store_id
        JOIN Store s ON cv.store_id=s.id
        WHERE cv.user_id=%s {store_clause}
        ORDER BY cv.is_used ASC, cv.issued_at DESC
        """,
        tuple(params),
    ).fetchall()]


def get_unused_vouchers_for_session(user_id, store_id):
    db = get_db()
    return [dict(r) for r in db.execute(
        """
        SELECT cv.id, lv.name AS voucher_name, lv.reward_type, lv.reward_value,
               lv.description AS voucher_description
        FROM CustomerVoucher cv
        JOIN LoyaltyVoucher lv ON cv.voucher_id=lv.id AND cv.store_id=lv.store_id
        WHERE cv.user_id=%s AND cv.store_id=%s AND cv.is_used=FALSE
        ORDER BY lv.reward_value DESC
        """,
        (user_id, store_id),
    ).fetchall()]


def calculate_voucher_discount(voucher, table_fee, food_total, subtotal_before_voucher):
    rv = float(voucher["reward_value"])
    rt = voucher["reward_type"]
    if rt == "food":
        return round(min(rv, food_total), 2)
    elif rt == "session":
        return round(min(rv, table_fee), 2)
    else:
        return round(min(rv, subtotal_before_voucher), 2)
