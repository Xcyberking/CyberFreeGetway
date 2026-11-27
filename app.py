import os, logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token

from config import Config
from models import db, User, Transaction, Payment
from auth import login_required
from imap_client import search_gmail
from payment_verify import verify_payment

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("famnify")

app = Flask(__name__)
app.config.from_object(Config)
CORS(app, supports_credentials=True)
db.init_app(app)
jwt = JWTManager(app)

with app.app_context():
    db.create_all()


# ─────────────────────────────────────────────
#  PAGE ROUTES
# ─────────────────────────────────────────────
@app.route("/")
def home():           return render_template("base.html", page="home")
@app.route("/login")
def login_page():     return render_template("login.html")
@app.route("/signup")
def signup_page():    return render_template("signup.html")
@app.route("/dashboard")
def dashboard_page(): return render_template("dashboard.html")
@app.route("/pricing")
def pricing_page():   return render_template("pricing.html", plans=Config.PLANS)


# ─────────────────────────────────────────────
#  AUTH
# ─────────────────────────────────────────────
@app.route("/api/auth/signup", methods=["POST"])
def api_signup():
    d = request.get_json() or {}
    email = (d.get("email") or "").strip().lower()
    pw    = d.get("password") or ""
    name  = (d.get("full_name") or "").strip()
    if not email or "@" not in email: return jsonify({"error":"invalid email"}), 400
    if len(pw) < 6: return jsonify({"error":"password min 6 chars"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error":"email already registered"}), 409
    u = User(email=email, full_name=name); u.set_password(pw)
    db.session.add(u); db.session.commit()
    return jsonify({"token": create_access_token(identity=str(u.id)), "user": u.to_dict()})


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    d = request.get_json() or {}
    email = (d.get("email") or "").strip().lower()
    pw    = d.get("password") or ""
    u = User.query.filter_by(email=email).first()
    if not u or not u.check_password(pw):
        return jsonify({"error":"invalid credentials"}), 401
    return jsonify({"token": create_access_token(identity=str(u.id)), "user": u.to_dict()})


@app.route("/api/auth/me")
@login_required
def api_me(user):
    return jsonify({"user": user.to_dict()})


# ─────────────────────────────────────────────
#  TRANSACTION LOOKUP (as before)
# ─────────────────────────────────────────────
@app.route("/api/fampay")
@login_required
def api_fampay(user):
    q = (request.args.get("id") or request.args.get("utr")
         or request.args.get("transaction", "")).strip()
    if len(q) < 4: return jsonify({"error":"query too short"}), 400

    if not user.is_active():
        return jsonify({"error":"plan expired", "upgrade": True}), 402
    if user.queries_used >= user.queries_limit:
        return jsonify({"error":"quota exceeded", "upgrade": True}), 402

    result = search_gmail(q)
    if result.get("found"):
        for r in result["results"]:
            db.session.add(Transaction(
                user_id=user.id, utr=r.get("utr",""), txn_id=r.get("txn_id",""),
                amount=r.get("money",""), sender=r.get("name",""),
                status=r.get("payment",""), date_str=r.get("date",""),
                raw_snippet=r.get("raw_snippet",""),
            ))
        user.queries_used += 1
        db.session.commit()
    return jsonify(result)


@app.route("/api/transactions")
@login_required
def api_transactions(user):
    page  = int(request.args.get("page", 1))
    limit = min(int(request.args.get("limit", 20)), 100)
    q = Transaction.query.filter_by(user_id=user.id).order_by(Transaction.created_at.desc())
    return jsonify({
        "total": q.count(), "page": page, "limit": limit,
        "items": [t.to_dict() for t in q.offset((page-1)*limit).limit(limit).all()]
    })


# ─────────────────────────────────────────────
#  UPI PAYMENT FLOW (no gateway)
# ─────────────────────────────────────────────

def _upi_link(amount: int, note: str) -> str:
    """Build a standard UPI deep-link so user's app opens pre-filled."""
    from urllib.parse import quote
    return (
        f"upi://pay?pa={quote(Config.UPI_ID)}"
        f"&pn={quote(Config.UPI_NAME)}"
        f"&am={amount}"
        f"&cu=INR"
        f"&tn={quote(note)}"
    )


@app.route("/api/payments/start", methods=["POST"])
@login_required
def api_pay_start(user):
    """Step 1: user picks a plan -> we return UPI details + create pending Payment."""
    d = request.get_json() or {}
    plan = d.get("plan")
    if plan not in Config.PLANS:
        return jsonify({"error": "invalid plan"}), 400

    p = Config.PLANS[plan]
    # Unique note: FAMNIFY-PRO-<userid>-<random4>
    import secrets
    tag = secrets.token_hex(2).upper()
    note = f"{Config.UPI_NOTE_PREFIX}-{plan.upper()}-{user.id}-{tag}"

    pay = Payment(
        user_id=user.id, plan=plan, amount=p["price"],
        utr="", note=note, status="pending"
    )
    db.session.add(pay); db.session.commit()

    return jsonify({
        "payment_id": pay.id,
        "plan": plan,
        "plan_name": p["name"],
        "amount": p["price"],
        "upi_id": Config.UPI_ID,
        "upi_name": Config.UPI_NAME,
        "note": note,
        "upi_link": _upi_link(p["price"], note),
        "instructions": [
            f"Open GPay/PhonePe/Paytm and pay ₹{p['price']} to {Config.UPI_ID}",
            f"Use note/remark exactly: {note}",
            "After paying, paste the 12-digit UTR below",
        ],
    })


@app.route("/api/payments/verify", methods=["POST"])
@login_required
def api_pay_verify(user):
    """
    Step 2: user submits UTR -> we scan Gmail for matching UPI credit.
    On match -> mark verified + activate plan.
    """
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

    # prevent one UTR being used twice
    dup = Payment.query.filter(
        Payment.utr == utr,
        Payment.status == "verified",
        Payment.id != pay.id
    ).first()
    if dup:
        return jsonify({"error": "this UTR already used for another payment"}), 409

    # Save UTR + try email verification
    pay.utr = utr
    db.session.commit()

    result = verify_payment(utr=utr, expected_amount=pay.amount, expected_note=pay.note)

    if not result["ok"]:
        # if hard failure (amount mismatch etc.) -> reject; if just "not found yet" -> keep pending
        reason = result["reason"]
        if reason.startswith("no_email_with_utr") or reason.startswith("not_found"):
            db.session.commit()
            return jsonify({
                "ok": False, "status": "pending",
                "message": "Payment not yet visible in email. Wait 1–2 minutes and retry, "
                           "or check the UTR you entered.",
            }), 202

        pay.status = "rejected"
        pay.reject_reason = reason
        db.session.commit()
        return jsonify({"ok": False, "status": "rejected", "reason": reason}), 400

    # ✅ verified
    detail = result["detail"]
    pay.status = "verified"
    pay.verified_amount = detail.get("amount", "")
    pay.verified_sender = detail.get("sender", "")
    pay.verified_at = datetime.utcnow()

    # activate plan on user
    plan = Config.PLANS[pay.plan]
    user.plan = pay.plan
    user.queries_limit = plan["queries"]
    user.queries_used = 0
    base = (user.plan_expires if (user.plan_expires and user.plan_expires > datetime.utcnow())
            else datetime.utcnow())
    user.plan_expires = base + timedelta(days=plan["days"])

    db.session.commit()
    log.info("UPI payment verified user=%s plan=%s utr=%s amount=%s",
             user.id, pay.plan, utr, detail.get("amount"))
    return jsonify({
        "ok": True, "status": "verified",
        "payment": pay.to_dict(),
        "user": user.to_dict(),
    })


@app.route("/api/payments/history")
@login_required
def api_pay_history(user):
    items = Payment.query.filter_by(user_id=user.id)\
                         .order_by(Payment.created_at.desc()).limit(50).all()
    return jsonify({"items": [p.to_dict() for p in items]})


@app.route("/api/payments/pending")
@login_required
def api_pay_pending(user):
    """For the 'waiting for verification' page."""
    items = Payment.query.filter_by(user_id=user.id, status="pending")\
                         .order_by(Payment.created_at.desc()).all()
    return jsonify({"items": [p.to_dict() for p in items]})


# ─────────────────────────────────────────────
#  HEALTH
# ─────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "time": datetime.utcnow().isoformat() + "Z",
        "email": bool(Config.EMAIL_ADDRESS),
        "upi":   Config.UPI_ID,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)