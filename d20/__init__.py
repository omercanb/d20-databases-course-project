import os

import plox
from flask import Flask, render_template
from flask_bootstrap import Bootstrap5

from d20 import seed


def create_app(test_config=None):
    # create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    bootstrap = Bootstrap5(app)
    app.config.from_mapping(
        SECRET_KEY="dev",
        DATABASE=os.path.join(app.instance_path, "d20.sqlite"),
    )

    if test_config is None:
        # load the instance config, if it exists, when not testing
        app.config.from_pyfile("config.py", silent=True)
    else:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    app.cli.add_command(seed.seed_db_command)
    # ensure the instance folder exists
    add_date_prettify(app)
    os.makedirs(app.instance_path, exist_ok=True)

    # a simple page that says hello
    @app.route("/hello")
    def hello():
        return "Hello, World!"

    @app.route("/test")
    def test():
        return render_template("test.html")

    from . import db

    db.init_app(app)

    from .routes import auth

    app.register_blueprint(auth.bp)

    # from .routes import blog
    #
    # app.register_blueprint(blog.bp)
    # app.add_url_rule("/", endpoint="index")

    from .routes import stores

    app.register_blueprint(stores.bp)

    from .routes import market

    app.register_blueprint(market.bp)
    app.add_url_rule("/", endpoint="index")

    return app


def add_date_prettify(app):
    @app.template_filter("pretty_date")
    def pretty_date(value):
        from datetime import datetime

        dt = datetime.fromisoformat(value)
        return dt.strftime("%d %b %Y, %H:%M:%S")
