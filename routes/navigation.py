# navigation.py
import os
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt, jwt_required

from db import get_db_connection

navigation_bp = Blueprint("navigation", __name__)

ORS_API_KEY = os.getenv("ORS_API_KEY", "")
ORS_PROFILE = os.getenv("ORS_PROFILE", "driving-car")
ORS_TIMEOUT_SECONDS = int(os.getenv("ORS_TIMEOUT_SECONDS", "15"))


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _calculate_eta_minutes(duration_s: Any) -> Optional[int]:
    try:
        if duration_s is None:
            return None
        return max(1, int(round(float(duration_s) / 60.0)))
    except (TypeError, ValueError):
        return None


def _call_ors_route(
    start_lat: float,
    start_lng: float,
    dest_lat: float,
    dest_lng: float,
) -> Tuple[Optional[List[List[float]]], Optional[float], Optional[float], Optional[int], Optional[str]]:
    if not ORS_API_KEY:
        return None, None, None, None, "ORS_API_KEY is not configured"

    ors_payload = {
        "coordinates": [
            [float(start_lng), float(start_lat)],
            [float(dest_lng), float(dest_lat)],
        ]
    }

    try:
        ors_response = requests.post(
            f"https://api.openrouteservice.org/v2/directions/{ORS_PROFILE}/geojson",
            json=ors_payload,
            headers={
                "Authorization": ORS_API_KEY,
                "Content-Type": "application/json",
            },
            timeout=ORS_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        return None, None, None, None, f"Failed to reach ORS: {e}"

    if ors_response.status_code != 200:
        return None, None, None, None, f"ORS request failed: {ors_response.text}"

    ors_data = ors_response.json()
    features = ors_data.get("features") or []
    if not features:
        return None, None, None, None, "ORS returned no route"

    feature = features[0]
    properties = feature.get("properties") or {}
    summary = properties.get("summary") or {}
    geometry = feature.get("geometry") or {}
    route_coordinates = geometry.get("coordinates") or []

    distance_m = summary.get("distance")
    duration_s = summary.get("duration")
    eta_minutes = _calculate_eta_minutes(duration_s)

    return route_coordinates, distance_m, duration_s, eta_minutes, None


def _fetch_active_assignment_for_rescuer(cur, user_id: int, team_id: int):
    cur.execute(
        """
        SELECT
            a.id,
            a.distress_id,
            a.team_id,
            a.rescuer_id,
            a.assigned_at,
            a.eta_minutes,
            a.status,
            ds.code,
            ds.reason,
            ds.latitude,
            ds.longitude,
            ds.timestamp,
            ds.priority,
            ds.first_name,
            ds.last_name,
            ds.phone,
            ds.blood_type,
            ds.age
        FROM assignments a
        JOIN distress_signals ds ON ds.id = a.distress_id
        WHERE (a.rescuer_id = %s OR a.team_id = %s)
          AND a.deleted = FALSE
          AND a.status IN ('assigned', 'en_route')
        ORDER BY a.assigned_at DESC
        LIMIT 1
        """,
        (user_id, team_id),
    )
    return cur.fetchone()


def _fetch_latest_active_assignment_global(cur):
    cur.execute(
        """
        SELECT
            a.id,
            a.distress_id,
            a.team_id,
            a.rescuer_id,
            a.assigned_at,
            a.eta_minutes,
            a.status,
            ds.code,
            ds.reason,
            ds.latitude,
            ds.longitude,
            ds.timestamp,
            ds.priority,
            ds.first_name,
            ds.last_name,
            ds.phone,
            ds.blood_type,
            ds.age
        FROM assignments a
        JOIN distress_signals ds ON ds.id = a.distress_id
        WHERE a.deleted = FALSE
          AND a.status IN ('assigned', 'en_route')
          AND ds.deleted = FALSE
          AND ds.status = 'active'
        ORDER BY a.assigned_at DESC
        LIMIT 1
        """
    )
    return cur.fetchone()


def _fetch_latest_rescuer_location(cur, rescuer_id: int):
    cur.execute(
        """
        SELECT latitude, longitude, recorded_at
        FROM rescuer_locations
        WHERE rescuer_id = %s
        ORDER BY recorded_at DESC
        LIMIT 1
        """,
        (rescuer_id,),
    )
    return cur.fetchone()


def _build_live_route_response(
    assignment_row,
    location_row,
    route_coordinates,
    distance_m,
    duration_s,
    eta_minutes,
):
    (
        assignment_id,
        distress_id,
        assign_team_id,
        rescuer_id,
        assigned_at,
        eta_minutes_db,
        assignment_status,
        distress_code,
        reason,
        dest_lat,
        dest_lng,
        distress_timestamp,
        priority,
        first_name,
        last_name,
        phone,
        blood_type,
        age,
    ) = assignment_row

    start_lat, start_lng, recorded_at = location_row

    return {
        "assignment": {
            "id": assignment_id,
            "distress_id": distress_id,
            "team_id": assign_team_id,
            "rescuer_id": rescuer_id,
            "assigned_at": assigned_at.isoformat() if assigned_at else None,
            "eta_minutes": eta_minutes if eta_minutes is not None else eta_minutes_db,
            "status": assignment_status,
            "distress": {
                "code": distress_code,
                "reason": reason,
                "latitude": _to_float(dest_lat),
                "longitude": _to_float(dest_lng),
                "timestamp": distress_timestamp.isoformat() if distress_timestamp else None,
                "priority": priority,
                "user": {
                    "firstName": first_name,
                    "lastName": last_name,
                    "phone": phone,
                    "bloodType": blood_type,
                    "age": age,
                },
            },
        },
        "rescuer_location": {
            "latitude": _to_float(start_lat),
            "longitude": _to_float(start_lng),
            "recorded_at": recorded_at.isoformat() if recorded_at else None,
        },
        "route": {
            "distance_m": distance_m,
            "duration_s": duration_s,
            "eta_minutes": eta_minutes,
            "coordinates": route_coordinates or [],
        },
    }


@navigation_bp.route("/rescuer/route/live", methods=["GET"])
@jwt_required()
def get_live_rescuer_route():
    """
    Returns the current rescuer's active assignment route and ETA.
    Also persists the calculated ETA in the assignments table for offline civilian use.
    """
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
            "SELECT team_id FROM users WHERE id = %s AND role = 'rescuer'",
            (user_id,),
        )
        user_row = cur.fetchone()
        if not user_row:
            return jsonify({"error": "Rescuer not found"}), 404
        team_id = user_row[0]

        assignment = _fetch_active_assignment_for_rescuer(cur, user_id, team_id)
        if not assignment:
            return jsonify({"error": "No active assignment found"}), 404

        (
            assignment_id,
            distress_id,
            _assign_team_id,
            _rescuer_id,
            _assigned_at,
            _eta_minutes_db,
            _assignment_status,
            _distress_code,
            _reason,
            dest_lat,
            dest_lng,
            _distress_timestamp,
            _priority,
            _first_name,
            _last_name,
            _phone,
            _blood_type,
            _age,
        ) = assignment

        location = _fetch_latest_rescuer_location(cur, user_id)
        if not location:
            return jsonify({"error": "Rescuer location not found"}), 400

        if dest_lat is None or dest_lng is None:
            return jsonify({"error": "Destination coordinates not found"}), 400

        start_lat, start_lng, _recorded_at = location
        route_coordinates, distance_m, duration_s, eta_minutes, route_error = _call_ors_route(
            float(start_lat),
            float(start_lng),
            float(dest_lat),
            float(dest_lng),
        )

        if route_coordinates is None:
            return jsonify({"error": "ORS request failed", "details": route_error}), 502

        if eta_minutes is not None:
            cur.execute(
                """
                UPDATE assignments
                SET eta_minutes = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (eta_minutes, assignment_id),
            )
            conn.commit()

        return jsonify(
            _build_live_route_response(
                assignment,
                location,
                route_coordinates,
                distance_m,
                duration_s,
                eta_minutes,
            )
        ), 200

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@navigation_bp.route("/route/live/public", methods=["GET"])
@navigation_bp.route("/public/route/live", methods=["GET"])
def get_public_live_route():
    """
    Public: Return the most recent active assignment live route for civilians.
    No JWT required.
    """
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        assignment = _fetch_latest_active_assignment_global(cur)
        if not assignment:
            return jsonify({"error": "No active assignment found"}), 404

        (
            assignment_id,
            _distress_id,
            _assign_team_id,
            rescuer_id,
            _assigned_at,
            _eta_minutes_db,
            _assignment_status,
            _distress_code,
            _reason,
            dest_lat,
            dest_lng,
            _distress_timestamp,
            _priority,
            _first_name,
            _last_name,
            _phone,
            _blood_type,
            _age,
        ) = assignment

        if not rescuer_id:
            return jsonify({"error": "No rescuer assigned"}), 404

        location = _fetch_latest_rescuer_location(cur, rescuer_id)
        if not location:
            return jsonify({"error": "Rescuer location not found"}), 404

        if dest_lat is None or dest_lng is None:
            return jsonify({"error": "Destination coordinates not found"}), 400

        start_lat, start_lng, _recorded_at = location
        route_coordinates, distance_m, duration_s, eta_minutes, route_error = _call_ors_route(
            float(start_lat),
            float(start_lng),
            float(dest_lat),
            float(dest_lng),
        )

        if route_coordinates is None:
            return jsonify({"error": "Live route unavailable", "details": route_error}), 503

        if eta_minutes is not None:
            cur.execute(
                """
                UPDATE assignments
                SET eta_minutes = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (eta_minutes, assignment_id),
            )
            conn.commit()

        return jsonify(
            _build_live_route_response(
                assignment,
                location,
                route_coordinates,
                distance_m,
                duration_s,
                eta_minutes,
            )
        ), 200

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"error": "Live route unavailable", "details": str(e)}), 503
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@navigation_bp.route("/node/<node_id>/distress/eta", methods=["GET"])
def get_node_distress_eta(node_id):
    """Public: Return ETA for the active distress on a given node."""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # Supports origin_node_id-based routing.
        cur.execute(
            """
            SELECT id
            FROM distress_signals
            WHERE origin_node_id = %s
              AND status = 'active'
              AND deleted = FALSE
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (node_id,),
        )
        distress_row = cur.fetchone()
        if not distress_row:
            return jsonify({"eta_minutes": None}), 200

        distress_id = distress_row[0]

        cur.execute(
            """
            SELECT eta_minutes
            FROM assignments
            WHERE distress_id = %s
              AND status IN ('assigned', 'en_route')
              AND deleted = FALSE
            ORDER BY assigned_at DESC
            LIMIT 1
            """,
            (distress_id,),
        )
        assign_row = cur.fetchone()
        eta = assign_row[0] if assign_row else None

        return jsonify({"eta_minutes": eta}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@navigation_bp.route("/distress/<int:distress_id>/eta", methods=["GET"])
@navigation_bp.route("/public/distress/<int:distress_id>/eta", methods=["GET"])
def get_distress_eta(distress_id):
    """Public: Return ETA for a specific distress ID."""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT eta_minutes
            FROM assignments
            WHERE distress_id = %s
              AND status IN ('assigned', 'en_route')
              AND deleted = FALSE
            ORDER BY assigned_at DESC
            LIMIT 1
            """,
            (distress_id,),
        )
        assign_row = cur.fetchone()
        eta = assign_row[0] if assign_row else None

        return jsonify({"eta_minutes": eta}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()