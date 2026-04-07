# app.py
import logging
import os
from flask import Flask, jsonify, request
from flask_cors import CORS

from config import Config
from extensions import jwt
from routes.auth import auth_bp
from routes.nodes import nodes_bp
from routes.locations import locations_bp
from routes.assignments import assignments_bp
from routes.navigation import navigation_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Enable CORS
    CORS(app)

    # Set up logging
    logging.basicConfig(level=logging.DEBUG)
    app.logger.setLevel(logging.DEBUG)

    # Initialize JWT
    jwt.init_app(app)

    # ---------- JWT Error Handlers (Debug) ----------
    @jwt.invalid_token_loader
    def invalid_token_callback(reason):
        app.logger.error(f"❌ JWT INVALID TOKEN: {reason}")
        return (
            jsonify(
                {
                    "error": "Invalid token",
                    "details": str(reason),
                }
            ),
            401,
        )

    @jwt.unauthorized_loader
    def unauthorized_callback(reason):
        app.logger.error(f"❌ JWT UNAUTHORIZED: {reason}")
        return (
            jsonify(
                {
                    "error": "Unauthorized",
                    "details": str(reason),
                }
            ),
            401,
        )

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        app.logger.error(f"❌ JWT EXPIRED: {jwt_payload}")
        return jsonify({"error": "Token has expired"}), 401

    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_payload):
        app.logger.error(f"❌ JWT REVOKED: {jwt_payload}")
        return jsonify({"error": "Token has been revoked"}), 401

    # ---------- Log Incoming Headers ----------
    @app.before_request
    def log_request_headers():
        auth_header = request.headers.get("Authorization")
        app.logger.info(f"📥 Request: {request.method} {request.path}")
        app.logger.info(f"🔐 Authorization header: {auth_header}")

    # ---------- Register Blueprints ----------
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(nodes_bp, url_prefix="/api")
    app.register_blueprint(locations_bp, url_prefix="/api")
    app.register_blueprint(assignments_bp, url_prefix="/api")
    app.register_blueprint(navigation_bp, url_prefix="/api")

    @app.route("/", methods=["GET"])
    def home():
        return jsonify({"message": "ResQMesh API is running"}), 200

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)