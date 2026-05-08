from datetime import date

from werkzeug.security import generate_password_hash

from d20.db import get_db
from d20.db.market.market_participant import create_market_participant


def create_store(username, name, password, address):
    db = get_db()
    cursor = db.execute(
        "INSERT INTO Store (username, name, password, address) VALUES (%s, %s, %s, %s) RETURNING id",
        (username, name, generate_password_hash(password), address),
    )
    db.commit()
    store_id = cursor.fetchone()["id"]
    create_market_participant(store_id=store_id)
    return store_id


def get_store(username):
    return (
        get_db()
        .execute("SELECT * FROM store WHERE username = %s", (username,))
        .fetchone()
    )


def get_store_by_id(store_id):
    return get_db().execute("SELECT * FROM store WHERE id = %s", (store_id,)).fetchone()


def _float_metrics(row, keys):
    metrics = dict(row)
    for key in keys:
        metrics[key] = float(metrics[key] or 0)
    return metrics


def get_store_overview_metrics(store_id, target_day=None):
    db = get_db()
    target_day = target_day or date.today()
    row = db.execute(
        """
        SELECT *
        FROM vw_store_daily_revenue_summary
        WHERE store_id = %s AND activity_date = %s
        """,
        (store_id, target_day),
    ).fetchone()
    session_summary = db.execute(
        """
        SELECT
            COUNT(*) AS todays_sessions,
            COUNT(*) FILTER (WHERE checked_in) AS checked_in_sessions,
            COUNT(*) FILTER (WHERE checkout_status = 'checked_out') AS checked_out_sessions
        FROM Session
        WHERE store_id = %s AND day::date = %s
          AND is_tournament = FALSE
        """,
        (store_id, target_day),
    ).fetchone()

    metrics = dict(row) if row else {
        "store_id": store_id,
        "activity_date": target_day,
        "total_sessions": 0,
        "total_bills": 0,
        "total_revenue": 0,
        "table_revenue": 0,
        "food_revenue": 0,
        "damage_revenue": 0,
    }
    metrics["todays_sessions"] = session_summary["todays_sessions"] or 0
    metrics["checked_in_sessions"] = session_summary["checked_in_sessions"] or 0
    metrics["checked_out_sessions"] = session_summary["checked_out_sessions"] or 0
    for key in (
        "total_revenue",
        "table_revenue",
        "food_revenue",
        "damage_revenue",
    ):
        metrics[key] = float(metrics[key] or 0)
    return metrics


def get_store_analytics_summary(store_id, start_date, end_date):
    row = (
        get_db()
        .execute(
            """
            SELECT
                %s::date AS start_date,
                %s::date AS end_date,
                COALESCE(SUM(total_sessions), 0) AS total_sessions,
                COALESCE(SUM(total_bills), 0) AS total_bills,
                COALESCE(SUM(total_revenue), 0) AS total_revenue,
                COALESCE(SUM(table_revenue), 0) AS table_revenue,
                COALESCE(SUM(food_revenue), 0) AS food_revenue,
                COALESCE(SUM(damage_revenue), 0) AS damage_revenue
            FROM vw_store_daily_revenue_summary
            WHERE store_id = %s
              AND activity_date BETWEEN %s AND %s
            """,
            (start_date, end_date, store_id, start_date, end_date),
        )
        .fetchone()
    )
    return _float_metrics(
        row,
        ("total_revenue", "table_revenue", "food_revenue", "damage_revenue"),
    )


def get_store_popular_games(store_id, limit, start_date, end_date):
    return (
        get_db()
        .execute(
            """
            SELECT
                store_id,
                game_id,
                game_name,
                SUM(session_count) AS session_count,
                SUM(copy_bookings) AS copy_bookings,
                MAX(activity_date) AS last_booked
            FROM vw_store_daily_game_popularity
            WHERE store_id = %s
              AND activity_date BETWEEN %s AND %s
            GROUP BY store_id, game_id, game_name
            ORDER BY session_count DESC, copy_bookings DESC, game_name ASC
            LIMIT %s
            """,
            (store_id, start_date, end_date, limit),
        )
        .fetchall()
    )


def get_store_popular_menu_items(store_id, limit, start_date, end_date):
    rows = (
        get_db()
        .execute(
            """
            SELECT
                store_id,
                item_id,
                item_name,
                SUM(quantity_sold) AS quantity_sold,
                SUM(order_count) AS order_count,
                SUM(revenue) AS revenue
            FROM vw_store_daily_menu_item_popularity
            WHERE store_id = %s
              AND activity_date BETWEEN %s AND %s
            GROUP BY store_id, item_id, item_name
            ORDER BY quantity_sold DESC, revenue DESC, item_name ASC
            LIMIT %s
            """,
            (store_id, start_date, end_date, limit),
        )
        .fetchall()
    )

    items = []
    for row in rows:
        item = dict(row)
        item["revenue"] = float(item["revenue"] or 0)
        items.append(item)
    return items


# Table Functions
def create_table(store_id, capacity):
    db = get_db()
    next_num = db.execute(
        'SELECT COALESCE(MAX(table_num), 0) + 1 AS next_num FROM "Table" WHERE store_id = %s',
        (store_id,),
    ).fetchone()["next_num"]
    db.execute(
        'INSERT INTO "Table" (store_id, table_num, capacity) VALUES (%s, %s, %s)',
        (store_id, next_num, capacity),
    )
    db.commit()
    return next_num


def get_tables(store_id):
    return (
        get_db()
        .execute('SELECT * FROM "Table" WHERE store_id = %s', (store_id,))
        .fetchall()
    )


def get_table(store_id, table_num):
    return (
        get_db()
        .execute(
            'SELECT * FROM "Table" WHERE store_id = %s AND table_num = %s',
            (store_id, table_num),
        )
        .fetchone()
    )


def delete_table(store_id, table_num):
    db = get_db()
    db.execute(
        'DELETE FROM "Table" WHERE store_id = %s AND table_num = %s',
        (store_id, table_num),
    )
    db.commit()


def update_table(store_id, table_num, capacity):
    db = get_db()
    db.execute(
        'UPDATE "Table" SET capacity = %s WHERE store_id = %s AND table_num = %s',
        (capacity, store_id, table_num),
    )
    db.commit()
