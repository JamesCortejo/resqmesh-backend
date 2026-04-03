from flask import Blueprint, jsonify
from db import get_db_connection

nodes_bp = Blueprint("nodes", __name__)


@nodes_bp.route("/nodes", methods=["GET"])
def get_nodes():
    conn = None
    cur = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT 
                node_id,
                name,
                latitude,
                longitude,
                last_seen,
                status,
                users_connected
            FROM nodes
            WHERE deleted = FALSE
        """)

        rows = cur.fetchall()

        nodes = []
        for row in rows:
            (
                node_id,
                name,
                lat,
                lng,
                last_seen,
                status,
                users_connected
            ) = row

            nodes.append({
                "id": node_id,
                "name": name,
                "lat": float(lat) if lat else None,
                "lng": float(lng) if lng else None,
                "lastSeen": last_seen.isoformat() if last_seen else None,
                "status": status,
                "users": users_connected or 0,
                "distress": False,  # optional for now
                "signal": None      # no signal in cloud
            })

        return jsonify(nodes), 200

    except Exception as e:
        return jsonify({
            "error": "Failed to fetch nodes",
            "details": str(e)
        }), 500

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()