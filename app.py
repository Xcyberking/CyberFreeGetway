import os, logging, secrets
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from flask_jwt_extended import JWTManager

from config import Config
from models import db, User, Transaction, Payment, AdminLog
from auth import login_required, make_token
from imap_client import search_gmail
from payment_verify import verify_payment
from admin import admin_bp
from utils import upi_link, activate_plan

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("famnify")

app = Flask(__name__)
app.config.from_object(Config)
CORS(app, supports_credentials=True)
db.init_app(app)
jwt = JWTManager(app)
app.register_blueprint(admin_bp)


# ─── BOOTSTRAP: create tables + admin ───────
def bootstrap():
    db.create_all()
    if not User.query.filter_by(is_admin=True).first():
        admin = User(
            email=Config.ADMIN_EMAIL,
            full_name="Admin",
            is_admin=True,
            plan="business",
            queries_limit=10_000_000,
        )
        admin.set_password(Config.ADMIN_PASSWORD)
        db.session.add(admin)
        db.session.commit()
        log.info("✅ Admin created: %s", Config.ADMIN_EMAIL)


with app.app_context():
    bootstrap()


# ─────────────────────────────────────────────
#  PAGE ROUTES
# ─────────────────────────────────────────────
@app.route("/")            # noqa
def home():           return render_template("base.html", page="home")
@app.route("/login")
def login_page():     return render_template("login.html")
@app.route("/signup")
def signup_page():    return render_template("signup.html")
@app.route("/dashboard")
def dashboard_page(): return render_template("dashboard.html")
@app.route("/pricing")
def pricing_page():   return render_template("pricing.html", plans=Config.PLANS)
@app.route("/checkout")
def checkout_page():  return render_template("checkout.html")
@app.route("/pending")
def pending_page():   return render_template("pending.html")

# admin pages
@app.route("/admin")
@app.route("/admin/<path:sub>")
def admin_page(sub="dashboard"):
    return render_template(f"admin/{sub}.html")


# ─────────────────────────────────────────────
#  AUTH APIs
# ─────────────────────────────────────────────
@app.route("/api/auth/signup", methods=["POST"])
def api_signup():
    d = request.get_json() or {}
    email = (d.get("email") or "").strip().lower()
    pw    = d.get("password") or ""
    name  = (d.get("full_name") or "").strip()
    if not email or "@" not in email:
        return jsonify({"error": "invalid email"}), 400
    if len(pw) < 6:
        return jsonify({"error": "password min 6 chars"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "email already registered"}), 409
    u = User(email=email, full_name=name)
    u.set_password(pw)
    db.session.add(u)
    db.session.commit()
    return jsonify({"token": make_token(u), "user": u.to_dict()})


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    d = request.get_json() or {}
    email = (d.get("email") or "").strip().lower()
    pw    = d.get("password") or ""
    u = User.query.filter_by(email=email).first()
    if not u or not u.check_password(pw):
        return jsonify({"error": "invalid credentials"}), 401
    if u.is_banned:
        return jsonify({"error": "account banned"}), 403
    return jsonify({"token": make_token(u), "user": u.to_dict()})


@app.route("/api/auth/me")
@login_required
def api_me(user):
    return jsonify({"user": user.to_dict()})


# ─────────────────────────────────────────────
#  FAMPAY LOOKUP
# ─────────────────────────────────────────────
@app.route("/api/fampay")
@login_required
def api_fampay(user):
    q = (request.args.get("id") or request.args.get("utr")
         or request.args.get("transaction", "")).strip()
    if len(q) < 4:
        return jsonify({"error": "query too short"}), 400
    if not user.is_active():
        return jsonify({"error": "plan expired", "upgrade": True}), 402
    if user.queries_used >= user.queries_limit:
        return jsonify({"error": "quota exceeded", "upgrade": True}), 402

    result = search_gmail(q)
    if result.get("found"):
        for r in result["results"]:
            db.session.add(Transaction(
                user_id=user.id, query=q,
                utr=r.get("utr", ""), txn_id=r.get("txn_id", ""),
                amount=r.get("money", ""), sender=r.get("name", ""),
                status=r.get("payment", ""), date_str=r.get("date", ""),
                raw_snippet=r.get("raw_snippet", ""),
            ))
        user.queries_used += 1
        db.session.commit()
    return jsonify(result)


@app.route("/api/transactions")
@login_required
def api_transactions(user):
    page  = int(request.args.get("page", 1))
    limit = min(int(request.args.get("limit", 20)), 100)
    q = Transaction.query.filter_by(user_id=user.id)\
                         .order_by(Transaction.created_at.desc())
    return jsonify({
        "total": q.count(), "page": page, "limit": limit,
        "items": [t.to_dict() for t in q.offset((page-1)*limit).limit(limit).all()],
    })


# ─────────────────────────────────────────────
#  UPI PAYMENT FLOW
# ─────────────────────────────────────────────
@app.route("/api/payments/start", methods=["POST"])
@login_required
def api_pay_start(user):
    d = request.get_json() or {}
    plan = d.get("plan")
    if plan not in Config.PLANS:
        return jsonify({"error": "invalid plan"}), 400
    p = Config.PLANS[plan]
    tag = secrets.token_hex(2).upper()
    note = f"{Config.UPI_NOTE_PREFIX}-{plan.upper()}-{user.id}-{tag}"
    pay = Payment(user_id=user.id, plan=plan, amount=p["price"],
                  note=note, status="pending")
    db.session.add(pay)
    db.session.commit()
    return jsonify({
        "payment_id": pay.id,
        "plan": plan, "plan_name": p["name"],
        "amount": p["price"],
        "upi_id": Config.UPI_ID, "upi_name": Config.UPI_NAME,
        "note": note, "upi_link": upi_link(p["price"], note),
    })


@app.route("/api/payments/verify", methods=["POST"])
@login_required
def api_pay_verify(user):
    d = request.get_json() or {}
    payment_id = d.get("payment_id")
    utr        = (d.get("utr") or "").strip()
    if not payment_id or not utr:
        return jsonify({"error": "payment_id and utr required"}), 400
    if not utr.isdigit() or not (10 <= len(utr) <= 18):
        return jsonify({"error": "UTR must be 10-18 digits"}), 400

    pay = Payment.query.filter_by(id=payment_id, user_id=user.id).first()
    if not pay:
        return jsonify({"error": "payment not found"}), 404
    if pay.status == "verified":
        return jsonify({"ok": True, "already": True, "payment": pay.to_dict()})
    if pay.status == "rejected":
        return jsonify({"error": "payment was rejected",
                        "reason": pay.reject_reason}), 409

    dup = Payment.query.filter(
        Payment.utr == utr, Payment.status == "verified", Payment.id != pay.id
    ).first()
    if dup:
        return jsonify({"error": "this UTR already used"}), 409

    pay.utr = utr
    db.session.commit()
    result = verify_payment(utr=utr, expected_amount=pay.amount, expected_note=pay.note)

    if not result["ok"]:
        reason = result["reason"]
        if reason.startswith("no_email_with_utr") or reason.startswith("not_found"):
            return jsonify({"ok": False, "status": "pending",
                            "message": "Payment not yet visible in email. Wait 1–2 min and retry."}), 202
        pay.status = "rejected"
        pay.reject_reason = reason
        db.session.commit()
        return jsonify({"ok": False, "status": "rejected", "reason": reason}), 400

    detail = result["detail"]
    pay.status = "verified"
    pay.verified_amount = detail.get("amount", "")
    pay.verified_sender = detail.get("sender", "")
    pay.verified_at = datetime.utcnow()
    activate_plan(user, pay.plan)
    db.session.commit()
    log.info("UPI verified user=%s plan=%s utr=%s", user.id, pay.plan, utr)
    return jsonify({"ok": True, "status": "verified",
                    "payment": pay.to_dict(), "user": user.to_dict()})


@app.route("/api/payments/history")
@login_required
def api_pay_history(user):
    items = Payment.query.filter_by(user_id=user.id)\
                         .order_by(Payment.created_at.desc()).limit(50).all()
    return jsonify({"items": [p.to_dict() for p in items]})


@app.route("/api/payments/pending")
@login_required
def api_pay_pending(user):
    items = Payment.query.filter_by(user_id=user.id, status="pending")\
                         .order_by(Payment.created_at.desc()).all()
    return jsonify({"items": [p.to_dict() for p in items]})


# ─────────────────────────────────────────────
#  CRON: recheck pending
# ─────────────────────────────────────────────
@app.route("/api/cron/recheck-pending")
def cron_recheck():
    if request.args.get("key") != Config.CRON_KEY:
        return jsonify({"error": "unauthorized"}), 401
    pend = Payment.query.filter(
        Payment.status == "pending",
        Payment.utr != "",
        Payment.created_at > datetime.utcnow() - timedelta(hours=24),
    ).limit(20).all()
    fixed = 0
    for p in pend:
        res = verify_payment(p.utr, p.amount, p.note)
        if res["ok"]:
            p.status = "verified"
            p.verified_amount = res["detail"]["amount"]
            p.verified_sender = res["detail"]["sender"]
            p.verified_at = datetime.utcnow()
            u = User.query.get(p.user_id)
            if u:
                activate_plan(u, p.plan)
            fixed += 1
    db.session.commit()
    return jsonify({"checked": len(pend), "verified": fixed})


# ─────────────────────────────────────────────
#  HEALTH
# ─────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "time": datetime.utcnow().isoformat() + "Z",
        "email": bool(Config.EMAIL_ADDRESS),
        "upi": Config.UPI_ID,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)