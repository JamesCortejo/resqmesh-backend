import bcrypt

from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    get_jwt,
    jwt_required,
)

from db import get_db_connection

auth_bp = Blueprint("auth", __name__)


def normalize_hash(value):
    if value is None:
        return None
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return str(value)


@auth_bp.route("/rescuer/login", methods=["POST"])
def rescuer_login():
    conn = None
    cur = None

    try:
        data = request.get_json(silent=True) or {}

        code = (data.get("code") or "").strip()
        password = data.get("password") or ""
        node_id = data.get("nodeId")

        if not code or not password:
            return jsonify({
                "error": "Missing credentials",
                "details": "code and password are required"
            }), 400

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                u.id, u.code, u.first_name, u.middle_name, u.last_name,
                u.role, u.team_id, u.password_hash,
                u.phone_encrypted, u.age, u.address_encrypted, u.occupation,
                rt.name AS team_name
            FROM users u
            LEFT JOIN rescue_teams rt ON rt.id = u.team_id
            WHERE u.code = %s
              AND u.role = 'rescuer'
              AND u.deleted = FALSE
            LIMIT 1
            """,
            (code,)
        )

        row = cur.fetchone()

        if not row:
            return jsonify({"error": "Invalid credentials"}), 401

        (
            user_id, user_code, first_name, middle_name, last_name,
            role, team_id, password_hash,
            phone_encrypted, age, address_encrypted, occupation,
            team_name
        ) = row

        password_hash = normalize_hash(password_hash)

        if not password_hash:
            return jsonify({"error": "Invalid credentials"}), 401

        if not bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")):
            return jsonify({"error": "Invalid credentials"}), 401

        access_token = create_access_token(
            identity=str(user_id),
            additional_claims={
                "user_id": user_id,
                "code": user_code,
                "role": role,
            }
        )

        if node_id is not None:
            cur.execute(
                """
                INSERT INTO rescuer_sessions (rescuer_id, node_id, last_seen_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (rescuer_id)
                DO UPDATE SET
                    node_id = EXCLUDED.node_id,
                    last_seen_at = NOW()
                """,
                (user_id, node_id)
            )
            conn.commit()

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
                "team_name": team_name,
                "phone": phone_encrypted,
                "age": age,
                "address": address_encrypted,
                "occupation": occupation,
                "password_hash": password_hash,
            }
        }), 200

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({
            "error": "Internal server error",
            "details": str(e)
        }), 500

    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()


@auth_bp.route("/logout", methods=["POST"])
@jwt_required()
def logout():
    conn = None
    cur = None

    try:
        claims = get_jwt()
        user_id = claims.get("user_id")

        if not user_id:
            return jsonify({"error": "Invalid token"}), 401

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "DELETE FROM rescuer_sessions WHERE rescuer_id = %s",
            (user_id,)
        )
        conn.commit()

        return jsonify({"message": "Logged out successfully"}), 200

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({
            "error": "Logout failed",
            "details": str(e)
        }), 500

    finally:
        if cur is not None:
            cur.close()
        if conn is not None:
            conn.close()