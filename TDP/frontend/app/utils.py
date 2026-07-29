import jwt
from functools import wraps
from flask import request, jsonify, current_app
from werkzeug.security import check_password_hash

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        if 'Authorization' in request.headers:
            parts = request.headers['Authorization'].split(" ")
            if len(parts) == 2:
                token = parts[1]

        if not token:
            return jsonify({'error': 'Token missing'}), 401

        try:
            data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            request.user = data
        except Exception:
            return jsonify({'error': 'Invalid/Expired token'}), 401

        return f(*args, **kwargs)
    return decorated


def role_required(roles):
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if request.user['role'] not in roles:
                return jsonify({'error': 'Forbidden'}), 403
            return f(*args, **kwargs)
        return decorated
    return wrapper


def verify_password(user, password):
    """
    Supports real Werkzeug hashes and a demo fallback for placeholder seed hashes.
    """
    password_hash = user['password_hash']

    if password_hash and '$hash' in password_hash:
        return password == 'password123'

    return check_password_hash(password_hash, password)
