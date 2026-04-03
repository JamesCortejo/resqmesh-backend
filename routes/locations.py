from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from db import get_db_connection

locations_bp = Blueprint("locations", __name__)


@locations_bp.route("/location/update", methods=["POST"])
@jwt_required()
def update_location():
    """
    Store current GPS location of the authenticated rescuer.
    Inserts a new row each time (keeps full history).
    """
    conn = None
    cur = None
    try:
        claims = get_jwt()
        user_id = claims.get("user_id")
        if not user_id:
            return jsonify({"error": "Invalid token"}), 401

        data = request.get_json()
        lat = data.get("latitude")
        lng = data.get("longitude")
        if lat is None or lng is None:
            return jsonify({"error": "latitude and longitude required"}), 400

        node_id = data.get("node_id")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO rescuer_locations (rescuer_id, node_id, latitude, longitude, recorded_at)
            VALUES (%s, %s, %s, %s, NOW())
        """, (user_id, node_id, lat, lng))
        conn.commit()
        return jsonify({"status": "ok", "message": "Location stored"}), 200

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# Keep the GET endpoints unchanged
@locations_bp.route("/location/rescuer/<int:rescuer_id>", methods=["GET"])
@jwt_required()
def get_rescuer_location(rescuer_id):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT latitude, longitude, recorded_at
            FROM rescuer_locations
            WHERE rescuer_id = %s
            ORDER BY recorded_at DESC
            LIMIT 1
        """, (rescuer_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "No location found for this rescuer"}), 404

        lat, lng, recorded_at = row
        return jsonify({
            "rescuer_id": rescuer_id,
            "latitude": float(lat),
            "longitude": float(lng),
            "recorded_at": recorded_at.isoformat()
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@locations_bp.route("/location/team/<int:team_id>", methods=["GET"])
@jwt_required()
def get_team_location(team_id):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT rl.latitude, rl.longitude, rl.recorded_at, u.id as rescuer_id
            FROM rescuer_locations rl
            JOIN users u ON u.id = rl.rescuer_id
            WHERE u.team_id = %s AND u.role = 'rescuer'
            ORDER BY rl.recorded_at DESC
            LIMIT 1
        """, (team_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "No location found for this team"}), 404

        lat, lng, recorded_at, rescuer_id = row
        return jsonify({
            "team_id": team_id,
            "rescuer_id": rescuer_id,
            "latitude": float(lat),
            "longitude": float(lng),
            "recorded_at": recorded_at.isoformat()
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()