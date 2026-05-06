from d20.db import get_db

SESSION_POINTS_PER_HOUR = 5
FOOD_POINT_PER_DOLLAR = 1
RATING_POINTS = 5
REDEMPTION_RATE = 0.10  # 1 point = $0.10 discount

def add_points(user_id, store_id, amount):
    """UPSERT points for a user at a specific store."""
    if amount <= 0:
        return

    db = get_db()
    db.execute(
        """
        INSERT INTO LoyaltyPoint (user_id, store_id, points)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, store_id) DO UPDATE
        SET points = LoyaltyPoint.points + EXCLUDED.points,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, store_id, int(amount)),
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

def redeem_points(user_id, store_id, amount, description=None):
    """Deduct points and record a redemption."""
    current_points = get_user_points(user_id, store_id)
    if amount > current_points:
        raise ValueError(f"Insufficient points balance. You have {current_points} points.")

    db = get_db()
    # Deduct from balance
    db.execute(
        "UPDATE LoyaltyPoint SET points = points - %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s AND store_id = %s",
        (amount, user_id, store_id),
    )
    # Record redemption
    db.execute(
        "INSERT INTO LoyaltyRedemption (user_id, store_id, points_spent, description) VALUES (%s, %s, %s, %s)",
        (user_id, store_id, amount, description),
    )
    db.commit()
    return amount * REDEMPTION_RATE

def get_store_loyalty_stats(store_id):
    """Get aggregate loyalty stats for a store."""
    db = get_db()
    
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
    
    total_awarded = total_active_points + total_spent_points
    
    # Average points per user
    avg_points = db.execute(
        "SELECT AVG(points) as avg FROM LoyaltyPoint WHERE store_id = %s",
        (store_id,),
    ).fetchone()["avg"] or 0
    
    # Top 5 loyal customers (by lifetime points)
    top_customers = db.execute(
        """
        SELECT u.username, lp.points as current_points, 
               (lp.points + COALESCE((SELECT SUM(points_spent) FROM LoyaltyRedemption lr WHERE lr.user_id = lp.user_id AND lr.store_id = lp.store_id), 0)) as lifetime_points
        FROM LoyaltyPoint lp
        JOIN "User" u ON lp.user_id = u.id
        WHERE lp.store_id = %s
        ORDER BY lifetime_points DESC
        LIMIT 5
        """,
        (store_id,),
    ).fetchall()
    
    return {
        "total_awarded": total_awarded,
        "total_active": total_active_points,
        "total_spent": total_spent_points,
        "avg_points": round(float(avg_points), 2),
        "top_customers": [dict(c) for c in top_customers]
    }
