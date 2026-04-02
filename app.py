import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone

app = Flask(__name__)
CORS(app)

logging.basicConfig(level=logging.INFO)

DATABASE_URL = os.environ.get("DATABASE_URL")
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRES_HOURS = int(os.environ.get("JWT_EXPIRES_HOURS", "24"))

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")
if not JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY is not set")


def get_db_connection():
    """
    Create a fresh DB connection per request.
    This is simple and avoids stale connection issues on Render.
    """
    return psycopg2.connect(DATABASE_URL)


def make_token(user_id: int, code: str, role: str):
    payload = {
        "sub": str(user_id),
        "code": code,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRES_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


@app.route("/", methods=["GET"])
def home():
    return jsonify({"message": "ResQMesh API is running"}), 200


@app.route("/health", methods=["GET"])
def health():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1;")
        cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({"status": "ok", "database": "connected"}), 200
    except Exception as e:
        app.logger.exception("Health check failed")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/auth/rescuer/login", methods=["POST"])
def rescuer_login():
    conn = None
    cur = None

    try:
        data = request.get_json(silent=True) or {}

        # The mobile app sends rescuer ID in `phone`, but in your DB you use `code`
        code = (data.get("phone") or data.get("code") or "").strip()
        password = data.get("password") or ""

        if not code or not password:
            return jsonify({
                "error": "Missing credentials",
                "details": "code/phone and password are required"
            }), 400

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT id, code, first_name, middle_name, last_name, role, team_id, password_hash
            FROM users
            WHERE code = %s
              AND role = 'rescuer'
              AND deleted = FALSE
            LIMIT 1
            """,
            (code,)
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"error": "Invalid credentials"}), 401

        user_id, user_code, first_name, middle_name, last_name, role, team_id, password_hash = row

        if not password_hash:
            return jsonify({"error": "Invalid credentials"}), 401

        # Handle bytes / memoryview / string safely
        if isinstance(password_hash, memoryview):
            password_hash = password_hash.tobytes()
        if isinstance(password_hash, bytes):
            password_hash = password_hash.decode("utf-8")

        if not bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")):
            return jsonify({"error": "Invalid credentials"}), 401

        access_token = make_token(user_id, user_code, role)

        return jsonify({
            "access_token": access_token,
            "user": {
                "id": user_id,
                "code": user_code,
                "first_name": first_name,
                "middle_name": middle_name,
                "last_name": last_name,
                "role": role,
                "team_id": team_id,
                "password_hash": password_hash
            }
        }), 200

    except Exception as e:
        app.logger.exception("Rescuer login failed")
        return jsonify({
            "error": "Internal server error",
            "details": str(e)
        }), 500

    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


@app.route("/auth/civilian/login", methods=["POST"])
def civilian_login():
    conn = None
    cur = None

    try:
        data = request.get_json(silent=True) or {}

        phone = (data.get("phone") or "").strip()
        password = data.get("password") or ""

        if not phone or not password:
            return jsonify({
                "error": "Missing credentials",
                "details": "phone and password are required"
            }), 400

        conn = get_db_connection()
        cur = conn.cursor()

        # For civilians, identify by phone_hash if that's what you use for login
        # If you actually log civilians in by code, change this query accordingly.
        cur.execute(
            """
            SELECT id, code, first_name, middle_name, last_name, role, team_id, password_hash
            FROM users
            WHERE phone_hash = %s
              AND role = 'civilian'
              AND deleted = FALSE
            LIMIT 1
            """,
            (phone,)
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"error": "Invalid credentials"}), 401

        user_id, user_code, first_name, middle_name, last_name, role, team_id, password_hash = row

        if not password_hash:
            return jsonify({"error": "Invalid credentials"}), 401

        if isinstance(password_hash, memoryview):
            password_hash = password_hash.tobytes()
        if isinstance(password_hash, bytes):
            password_hash = password_hash.decode("utf-8")

        if not bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")):
            return jsonify({"error": "Invalid credentials"}), 401

        access_token = make_token(user_id, user_code, role)

        return jsonify({
            "access_token": access_token,
            "user": {
                "id": user_id,
                "code": user_code,
                "first_name": first_name,
                "middle_name": middle_name,
                "last_name": last_name,
                "role": role,
                "team_id": team_id,
                "password_hash": password_hash
            }
        }), 200

    except Exception as e:
        app.logger.exception("Civilian login failed")
        return jsonify({
            "error": "Internal server error",
            "details": str(e)
        }), 500

    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))