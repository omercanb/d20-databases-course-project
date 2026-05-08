from d20.db import get_db

SESSION_POINTS_PER_HOUR = 5
FOOD_POINT_PER_DOLLAR = 1
RATING_POINTS = 5
REDEMPTION_RATE = 0.10  # 1 point = $0.10 discount

DEFAULT_POINT_RULES = {
    "session_hour": SESSION_POINTS_PER_HOUR,
    "food_dollar": FOOD_POINT_PER_DOLLAR,
    "game_rating": RATING_POINTS,
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


def get_user_tier_benefits(user_id, store_id):
    """Return the user's current tier benefits at a store, defaulting to Bronze."""
    db = get_db()
    row = db.execute(
        """
        SELECT lt.code AS tier_code,
               lt.discount_percent,
               lt.reservation_advance_days,
               lt.free_tournament_entries,
               COALESCE(lp.points, 0) AS points,
               COALESCE(lp.lifetime_points, 0) AS lifetime_points,
               COALESCE(lp.used_free_tournament_entries, 0) AS used_free_tournament_entries
        FROM LoyaltyTier lt
        LEFT JOIN LoyaltyPoint lp
          ON lp.store_id = lt.store_id
         AND lp.user_id = %s
         AND lp.tier_code = lt.code
        WHERE lt.store_id = %s
          AND lt.code = COALESCE(
              (SELECT tier_code FROM LoyaltyPoint WHERE user_id = %s AND store_id = %s),
              'Bronze'
          )
        """,
        (user_id, store_id, user_id, store_id),
    ).fetchone()
    if row is None:
        return {
            "tier_code": "Bronze",
            "discount_percent": 0,
            "reservation_advance_days": 0,
            "free_tournament_entries": 0,
            "points": 0,
            "lifetime_points": 0,
            "used_free_tournament_entries": 0,
        }
    return dict(row)


def calculate_tier_discount(user_id, store_id, subtotal):
    benefits = get_user_tier_benefits(user_id, store_id)
    discount_percent = float(benefits["discount_percent"] or 0)
    discount = round(max(0.0, float(subtotal)) * discount_percent / 100, 2)
    return discount, benefits


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


def get_customer_loyalty_profile(user_id, store_id, session_limit=10):
    db = get_db()
    benefits = get_user_tier_benefits(user_id, store_id)
    user = db.execute(
        'SELECT id, username FROM "User" WHERE id = %s',
        (user_id,),
    ).fetchone()
    if user is None:
        return None

    redemption = db.execute(
        """
        SELECT COALESCE(SUM(points_spent), 0) AS points_spent,
               COUNT(*) AS redemption_count
        FROM LoyaltyRedemption
        WHERE user_id = %s AND store_id = %s
        """,
        (user_id, store_id),
    ).fetchone()

    billing = db.execute(
        """
        SELECT COUNT(b.id) AS bill_count,
               COALESCE(SUM(b.grand_total), 0) AS total_spent,
               COALESCE(SUM(b.loyalty_discount), 0) AS point_discount,
               COALESCE(SUM(b.tier_discount), 0) AS tier_discount,
               COALESCE(SUM(b.voucher_discount), 0) AS voucher_discount
        FROM Session s
        JOIN Bill b ON b.session_id = s.id
        WHERE s.user_id = %s AND s.store_id = %s
        """,
        (user_id, store_id),
    ).fetchone()

    session_summary = db.execute(
        """
        SELECT COUNT(*) AS total_sessions,
               COUNT(*) FILTER (WHERE checked_in) AS checked_in_sessions,
               COUNT(*) FILTER (WHERE checkout_status = 'checked_out') AS checked_out_sessions,
               COUNT(*) FILTER (
                   WHERE checkout_status != 'checked_out'
                     AND NOT checked_in
                     AND (
                         day::date < CURRENT_DATE
                         OR (day::date = CURRENT_DATE AND end_time <= EXTRACT(HOUR FROM NOW())::INTEGER)
                     )
               ) AS not_attended_sessions
        FROM Session
        WHERE user_id = %s AND store_id = %s
        """,
        (user_id, store_id),
    ).fetchone()

    sessions = db.execute(
        """
        SELECT s.id, s.day, s.start_time, s.end_time, s.table_num,
               s.checked_in, s.checkout_status,
               b.grand_total, b.loyalty_discount, b.tier_discount, b.voucher_discount,
               COALESCE(
                   json_agg(
                       json_build_object('id', g.id, 'name', g.name)
                       ORDER BY g.name
                   ) FILTER (WHERE g.id IS NOT NULL),
                   '[]'::json
               ) AS games
        FROM Session s
        LEFT JOIN Bill b ON b.session_id = s.id
        LEFT JOIN SessionGameCopy sgc ON sgc.session_id = s.id
        LEFT JOIN Game g ON g.id = sgc.game_id
        WHERE s.user_id = %s
          AND s.store_id = %s
          AND (
              s.checkout_status = 'checked_out'
              OR s.day::date < CURRENT_DATE
              OR (s.day::date = CURRENT_DATE AND s.end_time <= EXTRACT(HOUR FROM NOW())::INTEGER)
          )
        GROUP BY s.id, b.id
        ORDER BY s.day DESC, s.start_time DESC
        LIMIT %s
        """,
        (user_id, store_id, session_limit),
    ).fetchall()

    total_discount = (
        float(billing["point_discount"] or 0)
        + float(billing["tier_discount"] or 0)
        + float(billing["voucher_discount"] or 0)
    )

    return {
        "user": dict(user),
        "tier": benefits,
        "points": benefits["points"],
        "lifetime_points": benefits["lifetime_points"],
        "used_free_tournament_entries": benefits["used_free_tournament_entries"],
        "points_spent": redemption["points_spent"] or 0,
        "redemption_count": redemption["redemption_count"] or 0,
        "bill_count": billing["bill_count"] or 0,
        "total_spent": float(billing["total_spent"] or 0),
        "point_discount": float(billing["point_discount"] or 0),
        "tier_discount": float(billing["tier_discount"] or 0),
        "voucher_discount": float(billing["voucher_discount"] or 0),
        "total_discount": total_discount,
        "session_summary": dict(session_summary),
        "sessions": [dict(session) for session in sessions],
    }

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
        SELECT lp.user_id, u.username, lp.tier_code, lp.points AS current_points,
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
        SELECT user_id, username, tier_code, current_points, redeemed_points, lifetime_points, store_rank
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


def get_loyalty_analytics(store_id, tier_code=None):
    db = get_db()

    tiers = db.execute(
        "SELECT code FROM LoyaltyTier WHERE store_id = %s ORDER BY min_points ASC",
        (store_id,),
    ).fetchall()

    tier_distribution = db.execute(
        "SELECT * FROM vw_loyalty_tier_distribution WHERE store_id = %s",
        (store_id,),
    ).fetchall()

    redemption_overview = db.execute(
        "SELECT * FROM vw_loyalty_redemption_overview WHERE store_id = %s",
        (store_id,),
    ).fetchone()

    redemption_by_tier = db.execute(
        "SELECT * FROM vw_loyalty_redemption_by_tier WHERE store_id = %s",
        (store_id,),
    ).fetchall()

    revenue_impact = db.execute(
        "SELECT * FROM vw_loyalty_revenue_impact WHERE store_id = %s",
        (store_id,),
    ).fetchone()

    most_loyal = db.execute(
        "SELECT * FROM vw_loyalty_most_loyal WHERE store_id = %s LIMIT 10",
        (store_id,),
    ).fetchall()

    results = {
        "tier_distribution": [dict(r) for r in tier_distribution],
        "redemption_overview": dict(redemption_overview) if redemption_overview else {
            "total_redemptions": 0, "total_points_redeemed": 0,
            "avg_per_redemption": 0, "min_redemption": 0,
            "max_redemption": 0, "redemption_rate_pct": None,
        },
        "redemption_by_tier": [dict(r) for r in redemption_by_tier],
        "revenue_impact": dict(revenue_impact) if revenue_impact else {
            "total_bills": 0, "gross_revenue": 0, "total_discount": 0,
            "net_revenue": 0, "avg_discount": 0, "max_discount": 0,
            "min_discount_nonzero": None, "bills_with_discount": 0,
            "discount_pct": None,
        },
        "most_loyal": [dict(r) for r in most_loyal],
        "available_tiers": [r["code"] for r in tiers],
    }

    if tier_code:
        results["tier_distribution"] = [
            t for t in results["tier_distribution"] if t["tier"] == tier_code
        ]
        results["redemption_by_tier"] = [
            r for r in results["redemption_by_tier"] if r["tier"] == tier_code
        ]
        results["most_loyal"] = [
            c for c in results["most_loyal"] if c["tier_code"] == tier_code
        ]

    return results
