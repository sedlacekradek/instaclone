from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
import secrets
from flask_mail import Mail
from dotenv import load_dotenv
import os
import timeago
import datetime as dt
from flask_migrate import Migrate
from elasticsearch import Elasticsearch


load_dotenv()
mail = Mail()
db = SQLAlchemy()


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = secrets.token_hex(16)
    app.config['MAX_CONTENT_LENGTH'] = 6 * 1024 * 1024  # max upload size 6MB

    # database config
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("SQLALCHEMY_DATABASE_URI")
    db.init_app(app)
    from .models import User  # cannot be imported before db initialized
    migrate = Migrate(app, db, render_as_batch=True)

    # mail config
    app.config['MAIL_SERVER'] = 'smtp.gmail.com'
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_SSL'] = False
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv("MAIL_DEFAULT_SENDER")
    app.config['MAIL_USERNAME'] = os.getenv("MAIL_USERNAME")
    app.config['MAIL_PASSWORD'] = os.getenv("MAIL_PASSWORD")
    mail.init_app(app)

    # elasticsearch
    app.elasticsearch = Elasticsearch(os.getenv("ELASTICSEARCH_URL")) if os.getenv("ELASTICSEARCH_URL") else None

    # db context
    with app.app_context():
        db.create_all()


    # blueprints
    from .views import views
    from .auth import auth
    app.register_blueprint(views, url_prefix="/")
    app.register_blueprint(auth, url_prefix="/")

    # login manager
    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(id):
        return User.query.get(int(id))

    # jinja custom filters
    @app.template_filter("datetime_format")
    def datetime_format(value):
        # "time ago format" - alternative to flask_moment module
        # 1) takes date_created value from models given by func.now()
        # 2) take current UTC time from datetime module
        # 3) converts datetime object to be timezone naive
        # 4) use timeago module
        now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        return timeago.format(value, now)

    return app