import os
import time
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

from flask import Flask, request, jsonify, render_template
import mysql.connector
import certifi

app = Flask(__name__)

# --- CONFIG & SECRETS ---
API_SECRET_KEY = os.getenv("API_KEY", "fallback_default_key")
TIDB_HOST = os.getenv("DB_HOST")
TIDB_USER = os.getenv("DB_USERNAME")
TIDB_PASSWORD = os.getenv("DB_PASSWORD")

db_config: Dict[str, Any] = {
    'host': TIDB_HOST,
    'user': TIDB_USER,
    'password': TIDB_PASSWORD,
    'database': 'pms_data',
    'port': 4000,
    'ssl_verify_cert': True,
    'ssl_verify_identity': False,
    'ssl_ca': certifi.where()
}

# --- IN-MEMORY LIVE STATE (zero TiDB load on dashboard polls) ---
LIVE_BUFFER_CAPACITY = 300
ONLINE_THRESHOLD_SEC = 30
STALE_THRESHOLD_SEC = 300

latest_live_data: Dict[str, Any] = {
    'time_full': 'Waiting for Pico...',
    'pm1': 0,
    'pm25': 0,
    'pm10': 0
}
live_chart_buffer: List[Dict[str, Any]] = []
last_received_ts: Optional[float] = None


def get_db_connection() -> Any:
    return mysql.connector.connect(**db_config)


def compute_sensor_meta() -> Dict[str, Any]:
    """Compute online/stale/offline status from server-side UTC epoch receipt time."""
    if last_received_ts is None:
        return {
            'status': 'offline',
            'has_data': False,
            'seconds_since_update': None,
            'last_received_utc': None,
            'buffer_size': len(live_chart_buffer),
            'buffer_capacity': LIVE_BUFFER_CAPACITY,
            'poll_interval_ms': 5000
        }

    elapsed = max(0, int(time.time() - last_received_ts))

    if elapsed <= ONLINE_THRESHOLD_SEC:
        status = 'online'
    elif elapsed <= STALE_THRESHOLD_SEC:
        status = 'stale'
    else:
        status = 'offline'

    t = time.gmtime(int(last_received_ts))
    iso_utc = f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d}T{t[3]:02d}:{t[4]:02d}:{t[5]:02d}Z"

    return {
        'status': status,
        'has_data': True,
        'seconds_since_update': elapsed,
        'last_received_utc': iso_utc,
        'buffer_size': len(live_chart_buffer),
        'buffer_capacity': LIVE_BUFFER_CAPACITY,
        'poll_interval_ms': 5000
    }


def compute_session_stats() -> Optional[Dict[str, Any]]:
    """Compute min/avg/max across the current in-memory live chart buffer."""
    if not live_chart_buffer:
        return None

    stats: Dict[str, Any] = {'count': len(live_chart_buffer)}
    for key in ('pm1', 'pm25', 'pm10'):
        values: List[float] = []
        for row in live_chart_buffer:
            val = row.get(key)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                values.append(float(val))

        if values:
            stats[key] = {
                'min': int(min(values)),
                'avg': round(sum(values) / len(values), 1),
                'max': int(max(values))
            }
        else:
            stats[key] = {'min': 0, 'avg': 0.0, 'max': 0}
    return stats


# --------------------------------------------
#  API ROUTES
# --------------------------------------------
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'ok',
        'sensor': compute_sensor_meta()['status']
    }), 200


@app.route('/api/data', methods=['GET'])
def get_dashboard_data():
    # Return only fast RAM memory to stay within TiDB limits
    return jsonify({
        'live': latest_live_data,
        'live_chart': live_chart_buffer,
        'meta': compute_sensor_meta(),
        'session_stats': compute_session_stats()
    })


@app.route('/api/sensor', methods=['POST'])
def receive_data():
    global latest_live_data, live_chart_buffer, last_received_ts

    # Security Check
    if request.headers.get('X-API-Key') != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(force=True, silent=True)
    if not data:
        print("FAILED TO PARSE JSON. RAW BODY:", request.data)
        return jsonify({"error": "Invalid payload"}), 400

    # SCENARIO A: Pico sent a live ping (Dictionary)
    if isinstance(data, dict):
        timestamp_str = str(data.get('timestamp') or '')
        pm1 = int(data.get('pm1') or 0)
        pm25 = int(data.get('pm25') or 0)
        pm10 = int(data.get('pm10') or 0)

        latest_live_data = {
            'time_full': timestamp_str,
            'pm1': pm1,
            'pm25': pm25,
            'pm10': pm10
        }
        last_received_ts = time.time()

        # Add to the scrolling chart
        time_short = timestamp_str.split(' ')[1] if ' ' in timestamp_str else timestamp_str
        live_chart_buffer.append({
            'time_short': time_short,
            'pm1': pm1,
            'pm25': pm25,
            'pm10': pm10
        })

        # Keep only the most recent LIVE_BUFFER_CAPACITY pings in RAM
        if len(live_chart_buffer) > LIVE_BUFFER_CAPACITY:
            live_chart_buffer.pop(0)

        return jsonify({"status": "live memory updated"}), 200

    # SCENARIO B: Pico sent the bulk buffer (List)
    elif isinstance(data, list):
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            sql = (
                "INSERT INTO readings (timestamp, pm1, pm25, pm10) "
                "VALUES (%(timestamp)s, %(pm1)s, %(pm25)s, %(pm10)s)"
            )
            cursor.executemany(sql, data)
            conn.commit()

            print(f"SUCCESS: Bulk saved {len(data)} readings to TiDB.")
            return jsonify({"status": "bulk_success"}), 201
        except mysql.connector.Error as err:
            print(f"MySQL Error: {err}")
            return jsonify({"error": "Database error"}), 400
        finally:
            if cursor is not None:
                cursor.close()
            if conn is not None:
                conn.close()

    return jsonify({"error": "Format unknown"}), 400


# --------------------------------------------
#  HTML VIEWS
# --------------------------------------------
@app.route('/', methods=['GET'])
def home():
    return render_template('index.html', active_page='live')


@app.route('/history', methods=['GET'])
def view_history():
    conn = None
    cursor = None
    rows: List[Dict[str, Any]] = []
    db_error: Optional[str] = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT timestamp, pm1, pm25, pm10 FROM readings "
            "ORDER BY timestamp DESC LIMIT 100"
        )
        rows = cursor.fetchall()
    except mysql.connector.Error as err:
        db_error = str(err)
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

    return render_template(
        'history.html',
        active_page='history',
        rows=rows,
        db_error=db_error
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
