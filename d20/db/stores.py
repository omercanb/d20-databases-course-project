from werkzeug.security import generate_password_hash

from d20.db import get_db
from d20.db.market.market_participant import create_market_participant


def create_store(username, name, password):
    db = get_db()
    cursor = db.execute(
        f"insert into Store (username, name, password) values (?, ?, ?)",
        (username, name, generate_password_hash(password)),
    )
    db.commit()
    # We also need to create a market participant entity for the dynamic pricing part
    store_id = cursor.lastrowid  # returns the new id
    create_market_participant(store_id=store_id)
    return store_id


def get_store(username):
    return (
        get_db()
        .execute("SELECT * FROM store WHERE username = ?", (username,))
        .fetchone()
    )


def get_store_by_id(store_id):
    return get_db().execute("SELECT * FROM store WHERE id = ?", (store_id,)).fetchone()


# Table Functions
def create_table(store_id, capacity):
    db = get_db()
    next_num = db.execute(
        'select coalesce(max(table_num), 0) + 1 from "Table" where store_id = ?',
        (store_id,),
    ).fetchone()[0]
    db.execute(
        'insert into "Table" (store_id, table_num, capacity) values (?, ?, ?)',
        (store_id, next_num, capacity),
    )
    db.commit()
    return next_num


def get_tables(store_id):
    return (
        get_db()
        .execute('select * from "Table" where store_id = ?', (store_id,))
        .fetchall()
    )


def get_table(store_id, table_num):
    return (
        get_db()
        .execute(
            'select * from "Table" where store_id = ? and table_num = ?',
            (store_id, table_num),
        )
        .fetchone()
    )


def delete_table(store_id, table_num):
    db = get_db()
    db.execute(
        'delete from "Table" where store_id = ? and table_num = ?',
        (store_id, table_num),
    )
    db.commit()


def update_table(store_id, table_num, capacity):
    db = get_db()
    db.execute(
        'update "Table" set capacity = ? where store_id = ? and table_num = ?',
        (capacity, store_id, table_num),
    )
    db.commit()
