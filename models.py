from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = "users"
    id            = db.Column(db.Integer, primary_key=True)
    email         = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name     = db.Column(db.String(120))
    plan          = db.Column(db.String(20), default="free")
    plan_expires  = db.Column(db.DateTime)
    queries_used  = db.Column(db.Integer, default=0)
    queries_limit = db.Column(db.Integer, default=50)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):   self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)
    def is_active(self):
        if self.plan == "free": return True
        return bool(self.plan_expires and self.plan_expires > datetime.utcnow())

    def to_dict(self):
        return {
            "id": self.id, "email": self.email, "full_name": self.full_name,
            "plan": self.plan,
            "plan_expires": self.plan_expires.isoformat() if self.plan_expires else None,
            "queries_used": self.queries_used,
            "queries_limit": self.queries_limit,
            "is_active": self.is_active(),
        }


class Transaction(db.Model):
    __tablename__ = "transactions"
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    utr          = db.Column(db.String(64), index=True)
    txn_id       = db.Column(db.String(64))
    amount       = db.Column(db.String(32))
    sender       = db.Column(db.String(120))
    status       = db.Column(db.String(20))
    date_str     = db.Column(db.String(64))
    raw_snippet  = db.Column(db.Text)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "utr": self.utr, "txn_id": self.txn_id,
            "amount": self.amount, "sender": self.sender,
            "status": self.status, "date": self.date_str,
            "snippet": self.raw_snippet,
            "created_at": self.created_at.isoformat(),
        }


class Payment(db.Model):
    """UPI payment — verified via email."""
    __tablename__ = "payments"
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    plan          = db.Column(db.String(20), nullable=False)
    amount        = db.Column(db.Integer, nullable=False)   # INR rupees
    utr           = db.Column(db.String(64), index=True, nullable=False)
    status        = db.Column(db.String(20), default="pending")  # pending|verified|rejected
    note          = db.Column(db.String(120))               # FAMNIFY-PRO-<uid>
    verified_amount = db.Column(db.String(32))
    verified_sender = db.Column(db.String(120))
    verified_at   = db.Column(db.DateTime)
    reject_reason = db.Column(db.String(255))
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "plan": self.plan, "amount": self.amount,
            "utr": self.utr, "status": self.status, "note": self.note,
            "verified_amount": self.verified_amount,
            "verified_sender": self.verified_sender,
            "created_at": self.created_at.isoformat(),
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "reject_reason": self.reject_reason,
        }