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

    # Gmail IMAP (same purana setup)
    EMAIL_ADDRESS  = os.environ.get("EMAIL_ADDRESS", "")
    EMAIL_APP_PASS = os.environ.get("EMAIL_APP_PASS", "")

    # 🆕 UPI collection details (tumhara apna UPI ID)
    UPI_ID      = os.environ.get("UPI_ID", "pay@famnify")
    UPI_NAME    = os.environ.get("UPI_NAME", "Famnify")
    UPI_NOTE_PREFIX = "FAMNIFY"   # note = FAMNIFY-PRO-<userid>

    # Plans (INR rupees, not paise)
    PLANS = {
        "starter":  {"name": "Starter",  "price": 99,   "days": 30, "queries": 1000},
        "pro":      {"name": "Pro",      "price": 299,  "days": 30, "queries": 10000},
        "business": {"name": "Business", "price": 999,  "days": 30, "queries": 100000},
    }