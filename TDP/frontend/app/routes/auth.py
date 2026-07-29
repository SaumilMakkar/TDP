from flask import Blueprint, request, jsonify, current_app, session
from werkzeug.security import generate_password_hash
import jwt
from datetime import datetime, timedelta
import sqlite3
from app.db import get_db_connection
from app.utils import verify_password

auth_bp = Blueprint('auth', __name__)


def _get_table_columns(cursor, table_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def _ensure_users_schema(cursor):
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'")
    table_row = cursor.fetchone()
    table_sql = (table_row[0] or '').lower() if table_row else ''

    needs_legacy_migration = bool(table_sql) and ("'doctor'" in table_sql and "'provider'" not in table_sql)
    if needs_legacy_migration:
        legacy_columns = _get_table_columns(cursor, 'users')
        has_pharmacist_id = 'pharmacist_id' in legacy_columns
        has_provider_npi = 'provider_npi' in legacy_columns
        has_pbm_id = 'pbm_id' in legacy_columns

        cursor.execute("ALTER TABLE users RENAME TO users_legacy")
        cursor.execute("""
            CREATE TABLE users (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                username       TEXT UNIQUE,
                password_hash  TEXT NOT NULL,
                role           TEXT NOT NULL CHECK (role IN ('provider', 'pharmacist', 'pbm')),
                pharmacist_id  TEXT UNIQUE,
                provider_npi   TEXT UNIQUE,
                pbm_id         TEXT UNIQUE,
                is_active      INTEGER NOT NULL DEFAULT 1,
                created_at     DATETIME NOT NULL DEFAULT (datetime('now'))
            )
        """)

        pharmacist_expr = 'pharmacist_id' if has_pharmacist_id else 'NULL'
        provider_expr = 'provider_npi' if has_provider_npi else 'NULL'
        pbm_expr = 'pbm_id' if has_pbm_id else 'NULL'
        cursor.execute(f"""
            INSERT INTO users (id, username, password_hash, role, pharmacist_id, provider_npi, pbm_id, is_active, created_at)
            SELECT
                id,
                username,
                password_hash,
                CASE WHEN role = 'doctor' THEN 'provider' ELSE role END,
                {pharmacist_expr},
                {provider_expr},
                {pbm_expr},
                is_active,
                COALESCE(created_at, datetime('now'))
            FROM users_legacy
        """)
        cursor.execute("DROP TABLE users_legacy")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            username       TEXT UNIQUE,
            password_hash  TEXT NOT NULL,
            role           TEXT NOT NULL CHECK (role IN ('provider', 'pharmacist', 'pbm')),
            pharmacist_id  TEXT UNIQUE,
            provider_npi   TEXT UNIQUE,
            pbm_id         TEXT UNIQUE,
            is_active      INTEGER NOT NULL DEFAULT 1,
            created_at     DATETIME NOT NULL DEFAULT (datetime('now'))
        )
    """)

    columns = _get_table_columns(cursor, 'users')
    if 'pharmacist_id' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN pharmacist_id TEXT")
    if 'provider_npi' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN provider_npi TEXT")
    if 'pbm_id' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN pbm_id TEXT")
    if 'full_name' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN full_name TEXT")

    # Backward compatibility for partially migrated datasets.
    cursor.execute("UPDATE users SET role='provider' WHERE role='doctor'")


def _normalize_role(role_raw):
    role = (role_raw or 'pharmacist').strip().lower()
    if role == 'doctor':
        return 'provider'
    return role


def _build_display_name(user):
    if user['full_name']:
        return user['full_name']
    role = (user['role'] or '').lower()
    if role == 'pharmacist':
        return user['pharmacist_id'] or 'Pharmacist'
    if role == 'provider':
        return user['provider_npi'] or 'Provider'
    return user['pbm_id'] or 'PBM'

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.json or {}
    password = data.get('password') or ''
    role = _normalize_role(data.get('role'))
    full_name = (data.get('full_name') or data.get('name') or '').strip()
    pharmacist_id = (data.get('pharmacist_id') or '').strip().upper()
    provider_npi = (data.get('provider_npi') or '').strip()
    pbm_id = (data.get('pbm_id') or '').strip().upper()
    allowed_roles = {'pharmacist', 'provider', 'pbm'}

    if not password:
        return jsonify({'error': 'Password is required'}), 400

    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    if role not in allowed_roles:
        return jsonify({'error': 'Invalid role. Allowed roles: pharmacist, provider, pbm'}), 400

    if role == 'pharmacist' and not pharmacist_id:
        return jsonify({'error': 'Pharmacist ID is required for pharmacist registration'}), 400

    if role == 'provider':
        if not provider_npi:
            return jsonify({'error': 'Provider NPI ID is required for provider registration'}), 400
        if not provider_npi.isdigit() or len(provider_npi) != 10:
            return jsonify({'error': 'Provider NPI ID must be a 10-digit number'}), 400

    if role == 'pbm':
        if not pbm_id:
            return jsonify({'error': 'PBM ID is required for PBM registration'}), 400
        pharmacist_id = ''
        provider_npi = ''

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        _ensure_users_schema(cursor)

        if role == 'pharmacist':
            cursor.execute("SELECT id FROM users WHERE pharmacist_id=?", (pharmacist_id,))
            if cursor.fetchone():
                return jsonify({'error': 'Pharmacist ID already exists'}), 409

        if role == 'provider':
            cursor.execute("SELECT id FROM users WHERE provider_npi=?", (provider_npi,))
            if cursor.fetchone():
                return jsonify({'error': 'Provider NPI ID already exists'}), 409

        if role == 'pbm':
            cursor.execute("SELECT id FROM users WHERE pbm_id=?", (pbm_id,))
            if cursor.fetchone():
                return jsonify({'error': 'PBM ID already exists'}), 409

        generated_username = None
        if role == 'pharmacist':
            generated_username = f"pharmacist_{pharmacist_id}"
        elif role == 'provider':
            generated_username = f"provider_{provider_npi}"
        else:
            generated_username = f"pbm_{pbm_id.lower()}"

        cursor.execute(
            """
            INSERT INTO users (username, full_name, password_hash, role, pharmacist_id, provider_npi, pbm_id, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                generated_username,
                full_name or None,
                generate_password_hash(password),
                role,
                pharmacist_id or None,
                provider_npi or None,
                pbm_id or None,
            )
        )
        conn.commit()
        login_id = pharmacist_id if role == 'pharmacist' else provider_npi if role == 'provider' else pbm_id
        return jsonify({'message': 'Registration successful. Please login.', 'role': role, 'login_id': login_id}), 201
    except sqlite3.IntegrityError as e:
        conn.rollback()
        if 'users.username' in str(e):
            return jsonify({'error': 'Account already exists. Please try logging in.'}), 409
        return jsonify({'error': 'Could not register user due to a duplicate value.'}), 409
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.json or {}
    login_id = (
        data.get('login_id')
        or data.get('role_id')
        or data.get('pharmacist_id')
        or data.get('provider_npi')
        or data.get('pbm_id')
        or ''
    ).strip()
    password = data.get('password')

    if not login_id or not password:
        return jsonify({'error': 'Login ID and password are required'}), 400

    pharmacist_id = login_id.upper()
    provider_npi = login_id
    pbm_id = login_id.upper()
    username = login_id.lower()

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        _ensure_users_schema(cursor)
        conn.commit()

        cursor.execute(
            """
            SELECT *
            FROM users
            WHERE is_active=1
              AND (
                  UPPER(COALESCE(pharmacist_id, '')) = ?
                  OR COALESCE(provider_npi, '') = ?
                  OR UPPER(COALESCE(pbm_id, '')) = ?
                  OR LOWER(COALESCE(username, '')) = ?
              )
            ORDER BY created_at DESC
            """,
            (pharmacist_id, provider_npi, pbm_id, username)
        )
        candidates = cursor.fetchall()
    finally:
        conn.close()

    user = None
    for candidate in candidates:
        if verify_password(candidate, password):
            user = candidate
            break

    if not user:
        return jsonify({'error': 'Invalid credentials'}), 401

    token = jwt.encode({
        'id': user['id'],
        'role': user['role'],
        'pharmacist_id': user['pharmacist_id'],
        'provider_npi': user['provider_npi'],
        'pbm_id': user['pbm_id'],
        'exp': datetime.utcnow() + timedelta(hours=2)
    }, current_app.config['SECRET_KEY'], algorithm='HS256')

    session['user_id'] = user['id']
    session['role'] = user['role']
    session['username'] = _build_display_name(user)
    session['pharmacist_id'] = user['pharmacist_id']
    session['provider_npi'] = user['provider_npi']
    session['pbm_id'] = user['pbm_id']

    return jsonify({
        "token": token,
        "role": user["role"],
        "username": _build_display_name(user),
        "full_name": user["full_name"],
        "pharmacist_id": user["pharmacist_id"],
        "provider_npi": user["provider_npi"],
        "pbm_id": user["pbm_id"],
    })


@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out successfully'})
