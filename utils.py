import os
from datetime import datetime, timedelta
from urllib.parse import quote
from config import Config


def upi_link(amount: int, note: str) -> str:
    return (
        f"upi://pay?pa={quote(Config.UPI_ID)}"
        f"&pn={quote(Config.UPI_NAME)}"
        f"&am={amount}&cu=INR&tn={quote(note)}"
    )


def activate_plan(user, plan_key: str):
    plan = Config.PLANS[plan_key]
    user.plan = plan_key
    user.queries_limit = plan["queries"]
    user.queries_used = 0
    base = (user.plan_expires if (user.plan_expires and user.plan_expires > datetime.utcnow())
            else datetime.utcnow())
    user.plan_expires = base + timedelta(days=plan["days"])