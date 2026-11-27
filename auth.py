from functools import wraps
from flask import jsonify
from flask_jwt_extended import (
    create_access_token, jwt_required, get_jwt_identity
)
from models import User


def make_token(user: User) -> str:
    return create_access_token(identity=str(user.id))


def current_user():
    uid = get_jwt_identity()
    return User.query.get(int(uid)) if uid else None


def login_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*a, **kw):
        user = current_user()
        if not user:
            return jsonify({"error": "user not found"}), 401
        return fn(user, *a, **kw)
    return wrapper