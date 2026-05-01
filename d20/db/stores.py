from werkzeug.security import generate_password_hash

from d20.db import get_db
from d20.db.market.market_participant import create_market_participant


def create_store(username, name, password):
    db = get_db()
    cursor = db.execute(
        "INSERT INTO Store (username, name, password) VALUES (%s, %s, %s) RETURNING id",
        (username, name, generate_password_hash(password)),
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
    return (
        get_db()
        .execute("SELECT * FROM store WHERE id = %s", (store_id,))
        .fetchone()
    )


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
