import psycopg2
import psycopg2.extras

import click
from flask import current_app, g


class DBConnection:
    """Small adapter so existing app code can keep calling db.execute(...)."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return cur

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_db():
    if "db" not in g:
        conn = psycopg2.connect(
            current_app.config["DATABASE_URL"],
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        conn.autocommit = False
        g.db = DBConnection(conn)
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as f:
        sql = f.read().decode("utf8")
    with db.cursor() as cur:
        cur.execute(sql)
    db.commit()


@click.command("init-db")
def init_db_command():
    """Clear the existing data and create new tables."""
    init_db()
    click.echo("Initialized the database.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
