import os
from json import dumps

from dotenv import load_dotenv
load_dotenv()

import plox
from flask import Flask, render_template
from flask_bootstrap import Bootstrap5
from minio import Minio

from d20 import seed


def create_app(test_config=None):
    # create and configure the app
    app = Flask(__name__)
    bootstrap = Bootstrap5(app)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", os.urandom(32).hex()),
        DATABASE_URL=os.environ.get("DATABASE_URL", "postgresql://localhost/d20"),
        MINIO_ENDPOINT=os.environ.get("MINIO_ENDPOINT", "localhost:9000"),
        MINIO_ACCESS_KEY=os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),
        MINIO_SECRET_KEY=os.environ.get("MINIO_SECRET_KEY", "minioadmin"),
        MINIO_BUCKET=os.environ.get("MINIO_BUCKET", "game-images"),
        MINIO_SECURE=os.environ.get("MINIO_SECURE", "false").lower() == "true",
    )

    if test_config is not None:
        # load the test config if passed in
        app.config.from_mapping(test_config)

    app.cli.add_command(seed.seed_db_command)
    add_date_prettify(app)

    # a simple page that says hello
    @app.route("/hello")
    def hello():
        return "Hello, World!"

    @app.route("/test")
    def test():
        return render_template("test.html")

    from . import db

    db.init_app(app)
    if not app.config.get("TESTING"):
        init_minio(app)

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


def init_minio(app):
    client = Minio(
        endpoint=app.config["MINIO_ENDPOINT"],
        access_key=app.config["MINIO_ACCESS_KEY"],
        secret_key=app.config["MINIO_SECRET_KEY"],
        secure=app.config["MINIO_SECURE"],
    )
    app.extensions["minio"] = client

    try:
        bucket = app.config["MINIO_BUCKET"]
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket}/*"],
                }
            ],
        }
        client.set_bucket_policy(bucket, dumps(policy))
    except Exception as exc:
        app.logger.warning("MinIO init skipped: %s", exc)


def add_date_prettify(app):
    @app.template_filter("pretty_date")
    def pretty_date(value):
        from datetime import datetime

        dt = datetime.fromisoformat(value)
        return dt.strftime("%d %b %Y, %H:%M:%S")
