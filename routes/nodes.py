from flask import Blueprint, jsonify, request
from db import get_db_connection
from datetime import datetime, timedelta

nodes_bp = Blueprint("nodes", __name__)

# Nodes are considered inactive if last_seen is older than 3 minutes (180 seconds)
INACTIVE_SECONDS = 180


@nodes_bp.route("/nodes", methods=["GET"])
def get_nodes():
    """
    Returns all non-deleted nodes with additional fields:
    - distress: boolean (true if there is an active distress signal for this node)
    - status: 'distress', 'online', or 'inactive' (based on last_seen)
    """
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Query that joins with active distress signals
        query = """
            SELECT
                n.node_id,
                n.name,
                n.latitude,
                n.longitude,
                n.last_seen,
                n.users_connected,
                CASE WHEN d.active_count > 0 THEN true ELSE false END AS has_distress,
                CASE
                    WHEN d.active_count > 0 THEN 'distress'
                    WHEN n.last_seen > NOW() - INTERVAL '%s seconds' THEN 'online'
                    ELSE 'inactive'
                END AS computed_status
            FROM nodes n
            LEFT JOIN (
                SELECT node_id, COUNT(*) AS active_count
                FROM distress_signals
                WHERE status = 'active' AND deleted = FALSE
                GROUP BY node_id
            ) d ON n.node_id = d.node_id
            WHERE n.deleted = FALSE
        """
        cur.execute(query, (INACTIVE_SECONDS,))
        rows = cur.fetchall()

        nodes = []
        for row in rows:
            (node_id, name, lat, lng, last_seen, users_connected, distress, status) = row
            nodes.append({
                "id": node_id,
                "name": name,
                "lat": float(lat) if lat is not None else None,
                "lng": float(lng) if lng is not None else None,
                "lastSeen": last_seen.isoformat() if last_seen else None,
                "users": users_connected or 0,
                "distress": distress,          # boolean
                "status": status,              # "distress", "online", "inactive"
                "signal": None                 # not used in cloud mode
            })
        return jsonify(nodes), 200

    except Exception as e:
        return jsonify({"error": "Failed to fetch nodes", "details": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@nodes_bp.route("/node/<node_id>/distress", methods=["GET"])
def get_node_distress(node_id):
    """
    Returns the most recent active distress signal for a given node.
    Used by the frontend to show the distress details card.
    """
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Fetch the latest active distress for this node
        cur.execute("""
            SELECT
                id, code, reason, latitude, longitude, timestamp, status, priority,
                user_code, first_name, last_name, phone, blood_type, age
            FROM distress_signals
            WHERE node_id = %s AND status = 'active' AND deleted = FALSE
            ORDER BY timestamp DESC
            LIMIT 1
        """, (node_id,))

        row = cur.fetchone()
        if not row:
            return jsonify({"error": "No active distress for this node"}), 404

        (id, code, reason, lat, lng, ts, status, priority,
         user_code, first_name, last_name, phone, blood_type, age) = row

        return jsonify({
            "id": id,
            "code": code,
            "reason": reason,
            "lat": float(lat) if lat is not None else None,
            "lng": float(lng) if lng is not None else None,
            "timestamp": ts.isoformat(),
            "status": status,
            "priority": priority,
            "user": {
                "firstName": first_name,
                "lastName": last_name,
                "phone": phone,
                "bloodType": blood_type,
                "age": age,
                "occupation": "",   # optional – not stored in distress_signals
                "address": ""       # optional – not stored here
            }
        }), 200

    except Exception as e:
        return jsonify({"error": "Failed to fetch distress details", "details": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@nodes_bp.route("/nodes/<node_id>/heartbeat", methods=["POST"])
def node_heartbeat(node_id):
    """
    Updates the last_seen timestamp of a node to keep it 'online'.
    Mesh nodes should call this endpoint every minute or so.
    """
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE nodes
            SET last_seen = NOW(), updated_at = NOW()
            WHERE node_id = %s AND deleted = FALSE
        """, (node_id,))
        conn.commit()

        if cur.rowcount == 0:
            return jsonify({"error": "Node not found"}), 404

        return jsonify({"status": "ok", "message": "Heartbeat recorded"}), 200

    except Exception as e:
        return jsonify({"error": "Failed to update heartbeat", "details": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()