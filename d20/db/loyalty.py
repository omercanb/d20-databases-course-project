from d20.db import get_db

SESSION_POINTS_PER_HOUR = 5
FOOD_POINT_PER_DOLLAR = 1
RATING_POINTS = 5
TOURNAMENT_PARTICIPATION_POINTS = 20
REDEMPTION_RATE = 0.10  # 1 point = $0.10 discount

DEFAULT_POINT_RULES = {
    "session_hour": SESSION_POINTS_PER_HOUR,
    "food_dollar": FOOD_POINT_PER_DOLLAR,
    "game_rating": RATING_POINTS,
    "tournament_participation": TOURNAMENT_PARTICIPATION_POINTS,
}

def get_user_advance_days(user_id, store_id):
    db = get_db()
    row = db.execute(
        """
        SELECT lt.reservation_advance_days
        FROM LoyaltyTier lt
        WHERE lt.store_id = %s
          AND lt.code = COALESCE(
              (SELECT tier_code FROM LoyaltyPoint WHERE user_id = %s AND store_id = %s),
              'Bronze'
          )
        """,
        (store_id, user_id, store_id),
    ).fetchone()
    return row["reservation_advance_days"] if row else 0


def add_points(user_id, store_id, amount):
    """UPSERT points for a user at a specific store."""
    if amount <= 0:
        return

    db = get_db()
    db.execute(
        """
        INSERT INTO LoyaltyPoint (user_id, store_id, points, lifetime_points)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id, store_id) DO UPDATE
        SET points = LoyaltyPoint.points + EXCLUDED.points,
            lifetime_points = LoyaltyPoint.lifetime_points + EXCLUDED.lifetime_points,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, store_id, int(amount), int(amount)),
    )
    db.commit()

def get_user_points(user_id, store_id):
    """Get the current point balance for a user at a store."""
    db = get_db()
    row = db.execute(
        "SELECT points FROM LoyaltyPoint WHERE user_id = %s AND store_id = %s",
        (user_id, store_id),
    ).fetchone()
    return row["points"] if row else 0

def get_point_rule(store_id, action_code):
    """Return the configured points for a store action."""
    db = get_db()
    row = db.execute(
        """
        SELECT points_per_unit
        FROM LoyaltyPointRule
        WHERE store_id = %s AND action_code = %s
        """,
        (store_id, action_code),
    ).fetchone()
    if row is None:
        return DEFAULT_POINT_RULES[action_code]
    return float(row["points_per_unit"])

def redeem_points(user_id, store_id, amount, description=None):
    """Deduct points and record a redemption."""
    amount = int(amount)
    if amount <= 0:
        raise ValueError("Redemption amount must be positive.")

    db = get_db()
    updated = db.execute(
        """
        UPDATE LoyaltyPoint
        SET points = points - %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = %s AND store_id = %s AND points >= %s
        RETURNING points
        """,
        (amount, user_id, store_id, amount),
    ).fetchone()
    if updated is None:
        current_points = get_user_points(user_id, store_id)
        raise ValueError(f"Insufficient points balance. You have {current_points} points.")

    db.execute(
        """
        INSERT INTO LoyaltyRedemption (user_id, store_id, points_spent, description)
        VALUES (%s, %s, %s, %s)
        """,
        (user_id, store_id, amount, description),
    )
    db.commit()
    return amount * REDEMPTION_RATE

def update_store_loyalty_tiers(store_id, tiers):
    """Update a store's loyalty thresholds and future perk settings."""
    required_codes = {"Bronze", "Silver", "Gold"}
    submitted_codes = {tier["code"] for tier in tiers}
    if submitted_codes != required_codes:
        raise ValueError("Bronze, Silver, and Gold tiers are required.")

    by_code = {tier["code"]: tier for tier in tiers}
    if by_code["Bronze"]["min_points"] != 0:
        raise ValueError("Bronze must start at 0 points.")
    if not by_code["Bronze"]["min_points"] < by_code["Silver"]["min_points"] < by_code["Gold"]["min_points"]:
        raise ValueError("Tier thresholds must increase from Bronze to Silver to Gold.")

    db = get_db()
    db.execute("SET CONSTRAINTS loyaltytier_store_min_points_unique DEFERRED")
    for tier in tiers:
        db.execute(
            """
            UPDATE LoyaltyTier
            SET min_points = %s,
                discount_percent = %s,
                reservation_advance_days = %s,
                free_tournament_entries = %s
            WHERE store_id = %s AND code = %s
            """,
            (
                tier["min_points"],
                tier["discount_percent"],
                tier["reservation_advance_days"],
                tier["free_tournament_entries"],
                store_id,
                tier["code"],
            ),
        )
    db.commit()

def update_store_loyalty_point_rules(store_id, rules):
    """Update the points a store awards for each loyalty action."""
    required_actions = {
        "session_hour",
        "food_dollar",
        "game_rating",
        "tournament_participation",
    }
    submitted_actions = {rule["action_code"] for rule in rules}
    if submitted_actions != required_actions:
        raise ValueError("All loyalty point earning rules are required.")

    db = get_db()
    for rule in rules:
        if rule["points_per_unit"] < 0:
            raise ValueError("Point earning rules cannot be negative.")
        db.execute(
            """
            UPDATE LoyaltyPointRule
            SET points_per_unit = %s
            WHERE store_id = %s AND action_code = %s
            """,
            (rule["points_per_unit"], store_id, rule["action_code"]),
        )
    db.commit()

def get_store_loyalty_stats(store_id, tier_code=None):
    """Get aggregate loyalty stats for a store."""
    db = get_db()
    
    # Total points earned over customer lifetimes
    total_awarded = db.execute(
        "SELECT SUM(lifetime_points) as total FROM LoyaltyPoint WHERE store_id = %s",
        (store_id,),
    ).fetchone()["total"] or 0

    # Total points active
    total_active_points = db.execute(
        "SELECT SUM(points) as total FROM LoyaltyPoint WHERE store_id = %s",
        (store_id,),
    ).fetchone()["total"] or 0
    
    # Total points spent
    total_spent_points = db.execute(
        "SELECT SUM(points_spent) as total FROM LoyaltyRedemption WHERE store_id = %s",
        (store_id,),
    ).fetchone()["total"] or 0
    
    # Average points per user
    avg_points = db.execute(
        "SELECT AVG(points) as avg FROM LoyaltyPoint WHERE store_id = %s",
        (store_id,),
    ).fetchone()["avg"] or 0
    
    tiers = db.execute(
        """
        SELECT code, min_points, discount_percent, reservation_advance_days, free_tournament_entries
        FROM LoyaltyTier
        WHERE store_id = %s
        ORDER BY min_points ASC
        """,
        (store_id,),
    ).fetchall()

    point_rules = [dict(r) for r in db.execute(
        """
        SELECT action_code, points_per_unit
        FROM LoyaltyPointRule
        WHERE store_id = %s
        ORDER BY action_code ASC
        """,
        (store_id,),
    ).fetchall()]

    tier_distribution = db.execute(
        """
        SELECT lt.code, lt.min_points, lt.discount_percent, lt.reservation_advance_days,
               lt.free_tournament_entries, COUNT(lp.id) AS customer_count,
               COALESCE(SUM(lp.points), 0) AS total_points
        FROM LoyaltyTier lt
        LEFT JOIN LoyaltyPoint lp ON lp.tier_code = lt.code AND lp.store_id = %s
        WHERE lt.store_id = %s
        GROUP BY lt.code, lt.min_points, lt.discount_percent, lt.reservation_advance_days, lt.free_tournament_entries
        ORDER BY lt.min_points ASC
        """,
        (store_id, store_id),
    ).fetchall()

    customer_filter = ""
    params = [store_id]
    if tier_code:
        customer_filter = "AND lp.tier_code = %s"
        params.append(tier_code)

    customers = db.execute(
        """
        SELECT u.username, lp.tier_code, lp.points AS current_points,
               lp.lifetime_points
        FROM LoyaltyPoint lp
        JOIN "User" u ON lp.user_id = u.id
        WHERE lp.store_id = %s
        """ + customer_filter + """
        ORDER BY lifetime_points DESC
        """,
        tuple(params),
    ).fetchall()

    top_point_holders = db.execute(
        """
        SELECT username, tier_code, current_points, redeemed_points, lifetime_points, store_rank
        FROM store_top_loyalty_point_holders
        WHERE store_id = %s
        ORDER BY store_rank ASC
        """,
        (store_id,),
    ).fetchall()
    
    return {
        "total_awarded": total_awarded,
        "total_active": total_active_points,
        "total_spent": total_spent_points,
        "avg_points": round(float(avg_points), 2),
        "tiers": [dict(t) for t in tiers],
        "point_rules": point_rules,
        "point_rule_map": {rule["action_code"]: rule["points_per_unit"] for rule in point_rules},
        "tier_distribution": [dict(t) for t in tier_distribution],
        "customers": [dict(c) for c in customers],
        "top_customers": [dict(c) for c in top_point_holders],
    }
