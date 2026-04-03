from flask import Flask, jsonify
from flask_cors import CORS

from config import Config
from extensions import jwt
from routes.auth import auth_bp
from routes.nodes import nodes_bp
from routes.locations import locations_bp   # <-- NEW


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    CORS(app)
    jwt.init_app(app)

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(nodes_bp, url_prefix="/api")
    app.register_blueprint(locations_bp, url_prefix="/api")   # <-- NEW

    @app.route("/", methods=["GET"])
    def home():
        return jsonify({"message": "ResQMesh API is running"}), 200

    @app.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(__import__("os").environ.get("PORT", "5000")), debug=True)