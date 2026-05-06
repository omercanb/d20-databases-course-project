from d20.db import get_db

def create_menu_item(store_id, name, price, description=None, is_available=True):
    db = get_db()
    res = db.execute(
        "INSERT INTO MenuItem (store_id, name, price, description, is_available) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (store_id, name, price, description, is_available),
    ).fetchone()
    db.commit()
    return res["id"]

def create_food(item_id, is_vegetarian=False, allergens=None, category=None):
    db = get_db()
    db.execute(
        "INSERT INTO Food (item_id, is_vegetarian, allergens, category) VALUES (%s, %s, %s, %s)",
        (item_id, is_vegetarian, allergens, category),
    )
    db.commit()

def create_beverage(item_id, size=None, temperature=None):
    db = get_db()
    db.execute(
        "INSERT INTO Beverage (item_id, size, temperature) VALUES (%s, %s, %s)",
        (item_id, size, temperature),
    )
    db.commit()

def get_menu(store_id):
    db = get_db()
    items = db.execute(
        """
        SELECT m.id, m.name, m.price, m.description, m.is_available,
               f.is_vegetarian, f.allergens, f.category,
               b.size, b.temperature,
               CASE WHEN f.item_id IS NOT NULL THEN 'Food'
                    WHEN b.item_id IS NOT NULL THEN 'Beverage'
                    ELSE 'Other' END as item_type
        FROM MenuItem m
        LEFT JOIN Food f ON m.id = f.item_id
        LEFT JOIN Beverage b ON m.id = b.item_id
        WHERE m.store_id = %s
        ORDER BY item_type DESC, m.name ASC
        """,
        (store_id,)
    ).fetchall()
    return [dict(i) for i in items]

def get_menu_item(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM MenuItem WHERE id = %s", (item_id,)).fetchone()
    return dict(item) if item else None

def create_session_order(session_id, items_quantities):
    """
    items_quantities is a list of tuples (item_id, quantity)
    """
    if not items_quantities:
        return None
        
    db = get_db()
    # Calculate total
    total = 0.0
    for item_id, qty in items_quantities:
        item = get_menu_item(item_id)
        if item:
            total += float(item["price"]) * qty
            
    # Create order
    res = db.execute(
        "INSERT INTO SessionOrder (session_id, total_amount) VALUES (%s, %s) RETURNING id",
        (session_id, total),
    ).fetchone()
    order_id = res["id"]
    
    # Create items
    for item_id, qty in items_quantities:
        db.execute(
            "INSERT INTO SessionOrderItem (order_id, item_id, quantity) VALUES (%s, %s, %s)",
            (order_id, item_id, qty)
        )
    db.commit()
    
    # Award loyalty points
    from d20.db.session import get_session
    from d20.db.loyalty import add_points, FOOD_POINT_PER_DOLLAR
    sess = get_session(session_id)
    if sess:
        points = int(total * FOOD_POINT_PER_DOLLAR)
        if points > 0:
            add_points(sess["user_id"], sess["store_id"], points)
            
    return order_id

def get_session_orders(session_id):
    db = get_db()
    orders_raw = db.execute(
        "SELECT * FROM SessionOrder WHERE session_id = %s ORDER BY timestamp DESC",
        (session_id,)
    ).fetchall()
    
    orders = []
    for o in orders_raw:
        order = dict(o)
        items = db.execute(
            """
            SELECT m.name, m.price, oi.quantity, (m.price * oi.quantity) as subtotal
            FROM SessionOrderItem oi
            JOIN MenuItem m ON oi.item_id = m.id
            WHERE oi.order_id = %s
            """,
            (order["id"],)
        ).fetchall()
        order["items"] = [dict(i) for i in items]
        orders.append(order)
        
    return orders


def get_menu_item_full(item_id):
    """Return MenuItem joined with Food/Beverage details."""
    db = get_db()
    row = db.execute(
        """
        SELECT m.id, m.store_id, m.name, m.price, m.description, m.is_available,
               f.is_vegetarian, f.allergens, f.category,
               b.size, b.temperature,
               CASE WHEN f.item_id IS NOT NULL THEN 'Food'
                    WHEN b.item_id IS NOT NULL THEN 'Beverage'
                    ELSE 'Other' END as item_type
        FROM MenuItem m
        LEFT JOIN Food f ON m.id = f.item_id
        LEFT JOIN Beverage b ON m.id = b.item_id
        WHERE m.id = %s
        """,
        (item_id,)
    ).fetchone()
    return dict(row) if row else None


def update_menu_item(item_id, name, price, description, is_available,
                     item_type,
                     is_vegetarian=False, allergens=None, category=None,
                     size=None, temperature=None):
    db = get_db()
    db.execute(
        "UPDATE MenuItem SET name=%s, price=%s, description=%s, is_available=%s WHERE id=%s",
        (name, price, description, is_available, item_id)
    )
    if item_type == "Food":
        db.execute(
            """
            INSERT INTO Food (item_id, is_vegetarian, allergens, category)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (item_id) DO UPDATE
            SET is_vegetarian=EXCLUDED.is_vegetarian,
                allergens=EXCLUDED.allergens,
                category=EXCLUDED.category
            """,
            (item_id, is_vegetarian, allergens or None, category or None)
        )
        db.execute("DELETE FROM Beverage WHERE item_id = %s", (item_id,))
    elif item_type == "Beverage":
        db.execute(
            """
            INSERT INTO Beverage (item_id, size, temperature)
            VALUES (%s, %s, %s)
            ON CONFLICT (item_id) DO UPDATE
            SET size=EXCLUDED.size, temperature=EXCLUDED.temperature
            """,
            (item_id, size or None, temperature or None)
        )
        db.execute("DELETE FROM Food WHERE item_id = %s", (item_id,))
    db.commit()


def toggle_menu_item_availability(item_id):
    db = get_db()
    db.execute(
        "UPDATE MenuItem SET is_available = NOT is_available WHERE id = %s",
        (item_id,)
    )
    db.commit()


def delete_menu_item(item_id):
    db = get_db()
    db.execute("DELETE FROM Food WHERE item_id = %s", (item_id,))
    db.execute("DELETE FROM Beverage WHERE item_id = %s", (item_id,))
    db.execute("DELETE FROM MenuItem WHERE id = %s", (item_id,))
    db.commit()
