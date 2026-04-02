from flask import Flask, request, jsonify
import psycopg2
import bcrypt
import jwt
import os

app = Flask(__name__)

JWT_SECRET = os.environ.get("JWT_SECRET_KEY")

DATABASE_URL = os.environ.get("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)

@app.route('/')
def home():
    return "ResQMesh API is running"

@app.route('/auth/rescuer/login', methods=['POST'])
def login():
    data = request.json
    code = data.get('phone')
    password = data.get('password')

    cur = conn.cursor()
    cur.execute("""
        SELECT id, code, first_name, last_name, role, team_id, password_hash
        FROM users
        WHERE code = %s AND role = 'rescuer' AND deleted = FALSE
    """, (code,))
    
    user = cur.fetchone()

    if not user:
        return jsonify({'error': 'User not found'}), 401

    user_id, code, first_name, last_name, role, team_id, password_hash = user

    if not bcrypt.checkpw(password.encode(), password_hash.encode()):
        return jsonify({'error': 'Wrong password'}), 401

    token = jwt.encode({'id': user_id}, JWT_SECRET, algorithm='HS256')

    return jsonify({
        'access_token': token,
        'user': {
            'id': user_id,
            'code': code,
            'first_name': first_name,
            'last_name': last_name,
            'role': role,
            'team_id': team_id,
            'password_hash': password_hash
        }
    })

if __name__ == '__main__':
    app.run()