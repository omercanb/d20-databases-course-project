from werkzeug.security import generate_password_hash

from flaskr.db import get_db


def create_user(username, password):
    db = get_db()
    cursor = db.execute(
        "insert into User (username, password) values (?, ?)",
        (username, generate_password_hash(password)),
    )
    db.commit()
    return cursor.lastrowid  # returns the new id


def get_user(username):
    return (
        get_db()
        .execute("SELECT * FROM user WHERE username = ?", (username,))
        .fetchone()
    )


def get_user_by_id(user_id):
    return get_db().execute("SELECT * FROM user WHERE id = ?", (user_id,)).fetchone()
