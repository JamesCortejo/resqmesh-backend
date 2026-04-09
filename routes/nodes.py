from flask import Blueprint, jsonify
from db import get_db_connection

nodes_bp = Blueprint("nodes", __name__)

INACTIVE_SECONDS = 180
DISTRESS_ACTIVE_SECONDS = 3600


@nodes_bp.route("/nodes", methods=["GET"])
def get_nodes():
    """
    Returns non-deleted nodes with active distress metadata.
    Added active_distress_id so civilian clients can query distress ETA directly.
    """
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        query = """
            SELECT
                n.node_id,
                n.name,
                n.latitude,
                n.longitude,
                n.last_seen,
                n.users_connected,
                ad.distress_id,
                ad.distress_timestamp,
                CASE WHEN ad.distress_id IS NOT NULL THEN true ELSE false END AS has_distress,
                CASE
                    WHEN ad.distress_id IS NOT NULL THEN 'distress'
                    WHEN n.last_seen > NOW() - INTERVAL '%s seconds' THEN 'online'
                    ELSE 'inactive'
                END AS computed_status
            FROM nodes n
            LEFT JOIN LATERAL (
                SELECT
                    ds.id AS distress_id,
                    ds.timestamp AS distress_timestamp
                FROM distress_signals ds
                WHERE ds.origin_node_id = n.node_id
                  AND ds.status = 'active'
                  AND ds.deleted = FALSE
                  AND ds.timestamp > NOW() - INTERVAL '%s seconds'
                ORDER BY ds.timestamp DESC
                LIMIT 1
            ) ad ON TRUE
            WHERE n.deleted = FALSE
        """
        cur.execute(query, (INACTIVE_SECONDS, DISTRESS_ACTIVE_SECONDS))
        rows = cur.fetchall()

        nodes = []
        for row in rows:
            (
                node_id,
                name,
                lat,
                lng,
                last_seen,
                users_connected,
                active_distress_id,
                distress_timestamp,
                distress,
                status,
            ) = row

            nodes.append(
                {
                    "id": node_id,
                    "node_id": node_id,
                    "name": name,
                    "lat": float(lat) if lat is not None else None,
                    "lng": float(lng) if lng is not None else None,
                    "lastSeen": last_seen.isoformat() if last_seen else None,
                    "users": users_connected or 0,
                    "distress": distress,
                    "status": status,
                    "active_distress_id": active_distress_id,
                    "active_distress_timestamp": distress_timestamp.isoformat() if distress_timestamp else None,
                    "signal": None,
                }
            )
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
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
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
            """,
            (node_id, DISTRESS_ACTIVE_SECONDS),
        )

        row = cur.fetchone()
        if not row:
            return jsonify({"error": "No recent active distress for this node"}), 404

        (
            id_,
            code,
            reason,
            lat,
            lng,
            ts,
            status,
            priority,
            _user_code,
            first_name,
            last_name,
            phone,
            blood_type,
            age,
        ) = row

        return jsonify(
            {
                "id": id_,
                "code": code,
                "reason": reason,
                "lat": float(lat) if lat is not None else None,
                "lng": float(lng) if lng is not None else None,
                "timestamp": ts.isoformat() if ts else None,
                "status": status,
                "priority": priority,
                "user": {
                    "firstName": first_name,
                    "lastName": last_name,
                    "phone": phone,
                    "bloodType": blood_type,
                    "age": age,
                    "occupation": "",
                    "address": "",
                },
            }
        ), 200

    except Exception as e:
        return jsonify({"error": "Failed to fetch distress details", "details": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@nodes_bp.route("/nodes/<node_id>/heartbeat", methods=["POST"])
def node_heartbeat(node_id):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE nodes
            SET last_seen = NOW(), updated_at = NOW()
            WHERE node_id = %s AND deleted = FALSE
            """,
            (node_id,),
        )
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