"""
Database management for saved WiFi networks
"""
import sqlite3
from datetime import datetime
import os

DB_PATH = 'wifi_manager.db'

def init_db():
    """Initialize the database with required tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS saved_networks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ssid TEXT UNIQUE NOT NULL,
            connected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def add_saved_network(ssid):
    """Add a network to saved networks or update last_used if exists"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO saved_networks (ssid, connected_at, last_used)
            VALUES (?, ?, ?)
            ON CONFLICT(ssid) DO UPDATE SET last_used = ?
        ''', (ssid, datetime.now(), datetime.now(), datetime.now()))
        conn.commit()
    except Exception as e:
        print(f"Error adding saved network: {e}")
    finally:
        conn.close()

def get_saved_networks():
    """Get all saved networks ordered by last used"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT ssid, connected_at, last_used
        FROM saved_networks
        ORDER BY last_used DESC
    ''')
    
    networks = cursor.fetchall()
    conn.close()
    
    return [{'ssid': row[0], 'connected_at': row[1], 'last_used': row[2]} 
            for row in networks]

def forget_network(ssid):
    """Remove a network from saved networks"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute('DELETE FROM saved_networks WHERE ssid = ?', (ssid,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error forgetting network: {e}")
        return False
    finally:
        conn.close()

def network_exists(ssid):
    """Check if a network is in saved networks"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM saved_networks WHERE ssid = ?', (ssid,))
    count = cursor.fetchone()[0]
    conn.close()
    
    return count > 0
