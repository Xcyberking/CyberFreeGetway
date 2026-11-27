import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "jwt-dev-secret")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=12)

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///famnify.db"
    ).replace("postgres://", "postgresql://")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    EMAIL_ADDRESS  = os.environ.get("EMAIL_ADDRESS", "")
    EMAIL_APP_PASS = os.environ.get("EMAIL_APP_PASS", "")

    UPI_ID          = os.environ.get("UPI_ID", "pay@famnify")
    UPI_NAME        = os.environ.get("UPI_NAME", "Famnify")
    UPI_NOTE_PREFIX = os.environ.get("UPI_NOTE_PREFIX", "FAMNIFY")

    ADMIN_EMAIL    = os.environ.get("ADMIN_EMAIL", "admin@famnify.local")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")
    CRON_KEY       = os.environ.get("CRON_KEY", "dev-cron-key")

    PLANS = {
        "starter":  {"name": "Starter",  "price": 99,  "days": 30, "queries": 1000},
        "pro":      {"name": "Pro",      "price": 299, "days": 30, "queries": 10000},
        "business": {"name": "Business", "price": 999, "days": 30, "queries": 100000},
    }