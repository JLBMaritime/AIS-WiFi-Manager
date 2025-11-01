#!/usr/bin/env python3
"""
AIS-WiFi Manager Application Entry Point
Run this script to start the web server
"""
from app import app
from app.database import init_db
from app.ais_manager import ais_manager
import os
import sys

if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Check if running as root (required for network operations)
    if os.geteuid() != 0:
        print("Warning: This application should be run with sudo for full functionality")
        print("Example: sudo python3 run.py")
        print()
    
    # Start AIS manager automatically
    print("Starting AIS Manager...")
    success, message = ais_manager.start()
    if success:
        print(f"✓ {message}")
    else:
        print(f"⚠ AIS Manager: {message}")
    print()
    
    # Run the Flask app
    print("Starting AIS-WiFi Manager Web Server...")
    print("=" * 50)
    print("Access the web interface at:")
    print("  - http://AIS.local")
    print("  - http://192.168.4.1")
    print()
    print("Login Credentials:")
    print("  - Username: JLBMaritime")
    print("  - Password: Admin")
    print("=" * 50)
    print()
    
    # Run on all interfaces, port 80 (requires sudo)
    try:
        app.run(host='0.0.0.0', port=80, debug=False)
    except PermissionError:
        print("Error: Permission denied. Please run with sudo to use port 80")
        print("Alternatively, running on port 5000...")
        app.run(host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\nShutting down...")
        ais_manager.stop()
        sys.exit(0)
