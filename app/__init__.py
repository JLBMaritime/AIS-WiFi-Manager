"""
AIS-WiFi Manager
Flask application initialization with HTTP authentication
"""
from flask import Flask
from flask_httpauth import HTTPBasicAuth
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
auth = HTTPBasicAuth()

# Authentication credentials
USERS = {
    "JLBMaritime": "Admin"
}

@auth.verify_password
def verify_password(username, password):
    if username in USERS and USERS[username] == password:
        return username
    return None

from app import routes
