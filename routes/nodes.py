from flask import Blueprint, jsonify, request
from db import get_db_connection

nodes_bp = Blueprint("nodes", __name__)

# Nodes are considered inactive if last_seen is older than 3 minutes (180 seconds)
INACTIVE_SECONDS = 180

# Distress signals older than this are considered stale (in seconds)
DISTRESS_ACTIVE_SECONDS = 3600   # 1 hour


@nodes_bp.route("/nodes", methods=["GET"])
def get_nodes():
    """
    Returns all non-deleted nodes with additional fields:
    - distress: boolean (true if there is an active distress signal for this node
                 that is younger than DISTRESS_ACTIVE_SECONDS)
    - status: 'distress', 'online', or 'inactive' (based on last_seen)
    """
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Query that joins with recent active distress signals using origin_node_id
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
                SELECT origin_node_id, COUNT(*) AS active_count
                FROM distress_signals
                WHERE status = 'active'
                  AND deleted = FALSE
                  AND timestamp > NOW() - INTERVAL '%s seconds'
                GROUP BY origin_node_id
            ) d ON n.node_id = d.origin_node_id
            WHERE n.deleted = FALSE
        """
        cur.execute(query, (INACTIVE_SECONDS, DISTRESS_ACTIVE_SECONDS))
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
                "signal": None
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
    Returns the most recent active distress signal for a given node,
    but only if it is younger than DISTRESS_ACTIVE_SECONDS.
    """
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                id, code, reason, latitude, longitude, timestamp, status, priority,
                user_code, first_name, last_name, phone, blood_type, age
            FROM distress_signals
            WHERE origin_node_id = %s
              AND status = 'active'
              AND deleted = FALSE
              AND timestamp > NOW() - INTERVAL '%s seconds'
            ORDER BY timestamp DESC
            LIMIT 1
        """, (node_id, DISTRESS_ACTIVE_SECONDS))

        row = cur.fetchone()
        if not row:
            return jsonify({"error": "No recent active distress for this node"}), 404

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
                "occupation": "",
                "address": ""
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