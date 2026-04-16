from werkzeug.security import generate_password_hash

from d20.db import get_db
from d20.db.market.market_participant import create_market_participant


def create_user(username, password):
    db = get_db()
    cursor = db.execute(
        "insert into User (username, password) values (?, ?)",
        (username, generate_password_hash(password)),
    )
    db.commit()
    customer_id = cursor.lastrowid  # returns the new id
    create_market_participant(customer_id=customer_id)
    return customer_id


def get_user(username):
    return (
        get_db()
        .execute("SELECT * FROM user WHERE username = ?", (username,))
        .fetchone()
    )


def get_user_by_id(user_id):
    return get_db().execute("SELECT * FROM user WHERE id = ?", (user_id,)).fetchone()
