from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt
from db import get_db_connection
import json

assignments_bp = Blueprint("assignments", __name__)


@assignments_bp.route("/rescuer/assignments", methods=["GET"])
@jwt_required()
def get_rescuer_assignments():
    """Get active assignments for the logged-in rescuer or their team."""
    conn = None
    cur = None
    try:
        claims = get_jwt()
        user_id = claims.get("user_id")
        if not user_id:
            return jsonify({"error": "Invalid token"}), 401

        conn = get_db_connection()
        cur = conn.cursor()
        # Get rescuer's team_id
        cur.execute(
            "SELECT team_id FROM users WHERE id = %s AND role = 'rescuer'",
            (user_id,)
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Rescuer not found"}), 404
        team_id = row[0]

        # Fetch assignments for this team or directly assigned to this rescuer
        cur.execute("""
            SELECT a.id, a.distress_id, a.team_id, a.rescuer_id, a.assigned_at,
                   a.eta_minutes, a.status,
                   ds.code, ds.reason, ds.latitude, ds.longitude, ds.timestamp,
                   ds.priority, ds.user_code, ds.first_name, ds.last_name,
                   ds.phone, ds.blood_type, ds.age,
                   n.name as node_name, n.node_id
            FROM assignments a
            JOIN distress_signals ds ON ds.id = a.distress_id
            LEFT JOIN nodes n ON n.node_id = ds.node_id
            WHERE (a.team_id = %s OR a.rescuer_id = %s)
              AND a.deleted = FALSE
              AND a.status IN ('assigned', 'en_route')
            ORDER BY a.assigned_at DESC
        """, (team_id, user_id))

        rows = cur.fetchall()
        assignments = []
        for row in rows:
            (assign_id, distress_id, assign_team_id, rescuer_id, assigned_at,
             eta_minutes, status,
             distress_code, reason, lat, lng, timestamp, priority,
             user_code, first_name, last_name, phone, blood_type, age,
             node_name, node_id) = row

            assignments.append({
                "id": assign_id,
                "distress_id": distress_id,
                "status": status,
                "assigned_at": assigned_at.isoformat(),
                "eta_minutes": eta_minutes,
                "distress": {
                    "code": distress_code,
                    "reason": reason,
                    "latitude": float(lat) if lat is not None else None,
                    "longitude": float(lng) if lng is not None else None,
                    "timestamp": timestamp.isoformat(),
                    "priority": priority,
                    "user": {
                        "firstName": first_name,
                        "lastName": last_name,
                        "phone": phone,
                        "bloodType": blood_type,
                        "age": age,
                    }
                },
                "node": {
                    "id": node_id,
                    "name": node_name
                }
            })

        return jsonify(assignments), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@assignments_bp.route("/assignment/<int:assignment_id>/resolve", methods=["POST"])
@jwt_required()
def resolve_assignment(assignment_id):
    """Mark an assignment as resolved and queue a mesh command."""
    conn = None
    cur = None
    try:
        claims = get_jwt()
        user_id = claims.get("user_id")
        if not user_id:
            return jsonify({"error": "Invalid token"}), 401

        conn = get_db_connection()
        cur = conn.cursor()

        # Verify assignment ownership and get distress details
        cur.execute("""
            SELECT a.team_id, a.rescuer_id, u.team_id as rescuer_team_id,
                   a.distress_id, ds.origin_node_id, ds.origin_distress_id
            FROM assignments a
            JOIN users u ON u.id = %s
            JOIN distress_signals ds ON ds.id = a.distress_id
            WHERE a.id = %s AND a.deleted = FALSE
        """, (user_id, assignment_id))
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "Assignment not found"}), 404

        assign_team_id, assign_rescuer_id, rescuer_team_id, distress_id, origin_node_id, origin_distress_id = row
        if assign_rescuer_id != user_id and assign_team_id != rescuer_team_id:
            return jsonify({"error": "Unauthorized"}), 403

        # Update assignment status
        cur.execute("""
            UPDATE assignments
            SET status = 'resolved', updated_at = NOW()
            WHERE id = %s
        """, (assignment_id,))

        # Update distress signal status
        cur.execute("""
            UPDATE distress_signals
            SET status = 'resolved', updated_at = NOW()
            WHERE id = %s
        """, (distress_id,))

        # Insert mesh command for the origin node
        payload = json.dumps({
            "distress_id": distress_id,
            "origin_distress_id": origin_distress_id
        })
        cur.execute("""
            INSERT INTO mesh_commands (target_node_id, command_type, payload)
            VALUES (%s, 'resolve_distress', %s)
        """, (origin_node_id, payload))

        conn.commit()

        return jsonify({"message": "Assignment resolved and mesh command queued."}), 200

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()