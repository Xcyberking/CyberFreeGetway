from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from sqlalchemy import func
from models import db, User, Payment, Transaction, AdminLog
from auth import admin_required
from utils import activate_plan
from config import Config

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _log(admin_id, action, target="", detail=""):
    db.session.add(AdminLog(admin_id=admin_id, action=action,
                            target=str(target), detail=str(detail)[:500]))


# ─── OVERVIEW ────────────────────────────────
@admin_bp.route("/stats")
@admin_required
def stats(admin):
    now = datetime.utcnow()
    month_ago = now - timedelta(days=30)

    total_users     = User.query.count()
    active_users    = User.query.filter(User.plan != "free").count()
    banned_users    = User.query.filter_by(is_banned=True).count()
    total_txns      = Transaction.query.count()
    total_payments  = Payment.query.count()

    verified_payments = Payment.query.filter_by(status="verified").all()
    revenue = sum(p.amount for p in verified_payments)

    revenue_30d = sum(p.amount for p in verified_payments
                      if p.verified_at and p.verified_at >= month_ago)

    new_users_30d = User.query.filter(User.created_at >= month_ago).count()

    pending = Payment.query.filter_by(status="pending").count()
    verified = Payment.query.filter_by(status="verified").count()
    rejected = Payment.query.filter_by(status="rejected").count()

    # last 7 days revenue chart
    chart = []
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        day_rev = sum(p.amount for p in verified_payments
                      if p.verified_at and start <= p.verified_at < end)
        chart.append({"date": start.strftime("%d %b"), "revenue": day_rev})

    return jsonify({
        "total_users": total_users,
        "active_users": active_users,
        "banned_users": banned_users,
        "new_users_30d": new_users_30d,
        "total_transactions": total_txns,
        "total_payments": total_payments,
        "total_revenue": revenue,
        "revenue_30d": revenue_30d,
        "payments_pending": pending,
        "payments_verified": verified,
        "payments_rejected": rejected,
        "revenue_chart": chart,
    })


# ─── USERS ───────────────────────────────────
@admin_bp.route("/users")
@admin_required
def list_users(admin):
    page  = int(request.args.get("page", 1))
    limit = min(int(request.args.get("limit", 25)), 100)
    q     = (request.args.get("q") or "").strip()

    query = User.query
    if q:
        query = query.filter(User.email.ilike(f"%{q}%"))
    total = query.count()
    users = query.order_by(User.created_at.desc())\
                 .offset((page-1)*limit).limit(limit).all()
    return jsonify({
        "total": total, "page": page, "limit": limit,
        "items": [u.to_dict() for u in users],
    })


@admin_bp.route("/users/<int:uid>", methods=["GET"])
@admin_required
def get_user(admin, uid):
    u = User.query.get_or_404(uid)
    payments = Payment.query.filter_by(user_id=uid)\
                            .order_by(Payment.created_at.desc()).limit(20).all()
    txns = Transaction.query.filter_by(user_id=uid)\
                            .order_by(Transaction.created_at.desc()).limit(20).all()
    return jsonify({
        "user": u.to_dict(),
        "payments": [p.to_dict() for p in payments],
        "transactions": [t.to_dict() for t in txns],
    })


@admin_bp.route("/users/<int:uid>/plan", methods=["POST"])
@admin_required
def set_user_plan(admin, uid):
    u = User.query.get_or_404(uid)
    data = request.get_json() or {}
    plan = data.get("plan")
    if plan != "free" and plan not in Config.PLANS:
        return jsonify({"error": "invalid plan"}), 400
    if plan == "free":
        u.plan = "free"
        u.plan_expires = None
        u.queries_limit = 50
    else:
        activate_plan(u, plan)
    _log(admin.id, "set_plan", u.email, plan)
    db.session.commit()
    return jsonify({"ok": True, "user": u.to_dict()})


@admin_bp.route("/users/<int:uid>/ban", methods=["POST"])
@admin_required
def ban_user(admin, uid):
    u = User.query.get_or_404(uid)
    if u.is_admin:
        return jsonify({"error": "cannot ban admin"}), 400
    u.is_banned = not u.is_banned
    _log(admin.id, "toggle_ban", u.email, u.is_banned)
    db.session.commit()
    return jsonify({"ok": True, "banned": u.is_banned})


@admin_bp.route("/users/<int:uid>/quota", methods=["POST"])
@admin_required
def reset_quota(admin, uid):
    u = User.query.get_or_404(uid)
    u.queries_used = 0
    _log(admin.id, "reset_quota", u.email)
    db.session.commit()
    return jsonify({"ok": True})


@admin_bp.route("/users/<int:uid>", methods=["DELETE"])
@admin_required
def delete_user(admin, uid):
    u = User.query.get_or_404(uid)
    if u.is_admin:
        return jsonify({"error": "cannot delete admin"}), 400
    Transaction.query.filter_by(user_id=uid).delete()
    Payment.query.filter_by(user_id=uid).delete()
    _log(admin.id, "delete_user", u.email)
    db.session.delete(u)
    db.session.commit()
    return jsonify({"ok": True})


# ─── PAYMENTS ────────────────────────────────
@admin_bp.route("/payments")
@admin_required
def list_payments(admin):
    page   = int(request.args.get("page", 1))
    limit  = min(int(request.args.get("limit", 25)), 100)
    status = request.args.get("status")
    q      = Payment.query
    if status:
        q = q.filter_by(status=status)
    total = q.count()
    items = q.order_by(Payment.created_at.desc())\
             .offset((page-1)*limit).limit(limit).all()
    return jsonify({
        "total": total, "page": page, "limit": limit,
        "items": [p.to_dict() for p in items],
    })


@admin_bp.route("/payments/<int:pid>/approve", methods=["POST"])
@admin_required
def approve_payment(admin, pid):
    p = Payment.query.get_or_404(pid)
    if p.status == "verified":
        return jsonify({"ok": True, "already": True})
    u = User.query.get(p.user_id)
    if not u:
        return jsonify({"error": "user missing"}), 404
    p.status = "verified"
    p.verified_at = datetime.utcnow()
    p.verified_amount = str(p.amount)
    p.verified_sender = p.verified_sender or "Admin-approved"
    activate_plan(u, p.plan)
    _log(admin.id, "approve_payment", f"#{p.id}", f"user={u.email} plan={p.plan}")
    db.session.commit()
    return jsonify({"ok": True, "payment": p.to_dict()})


@admin_bp.route("/payments/<int:pid>/reject", methods=["POST"])
@admin_required
def reject_payment(admin, pid):
    p = Payment.query.get_or_404(pid)
    data = request.get_json() or {}
    p.status = "rejected"
    p.reject_reason = (data.get("reason") or "rejected by admin")[:255]
    _log(admin.id, "reject_payment", f"#{p.id}", p.reject_reason)
    db.session.commit()
    return jsonify({"ok": True, "payment": p.to_dict()})


# ─── TRANSACTIONS ────────────────────────────
@admin_bp.route("/transactions")
@admin_required
def list_transactions(admin):
    page  = int(request.args.get("page", 1))
    limit = min(int(request.args.get("limit", 25)), 100)
    q     = (request.args.get("q") or "").strip()
    query = Transaction.query
    if q:
        query = query.filter(
            (Transaction.utr.ilike(f"%{q}%")) |
            (Transaction.txn_id.ilike(f"%{q}%")) |
            (Transaction.sender.ilike(f"%{q}%"))
        )
    total = query.count()
    items = query.order_by(Transaction.created_at.desc())\
                 .offset((page-1)*limit).limit(limit).all()
    return jsonify({
        "total": total, "page": page, "limit": limit,
        "items": [t.to_dict() for t in items],
    })


# ─── LOGS ────────────────────────────────────
@admin_bp.route("/logs")
@admin_required
def list_logs(admin):
    page  = int(request.args.get("page", 1))
    limit = min(int(request.args.get("limit", 50)), 200)
    total = AdminLog.query.count()
    items = AdminLog.query.order_by(AdminLog.created_at.desc())\
                          .offset((page-1)*limit).limit(limit).all()
    return jsonify({"total": total, "page": page, "limit": limit,
                    "items": [l.to_dict() for l in items]})