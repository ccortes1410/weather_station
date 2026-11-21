import os
from datetime import datetime, timezone
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

db_config = {
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

latest_live_data = {
    'time_full': 'Waiting for Pico...',
    'pm1': 0,
    'pm25': 0,
    'pm10': 0
}
live_chart_buffer = []
last_received_utc = None


def get_db_connection():
    return mysql.connector.connect(**db_config)


def compute_sensor_meta():
    """Compute online/stale/offline status from server-side UTC receipt time."""
    if last_received_utc is None:
        return {
            'status': 'offline',
            'has_data': False,
            'seconds_since_update': None,
            'last_received_utc': None,
            'buffer_size': len(live_chart_buffer),
            'buffer_capacity': LIVE_BUFFER_CAPACITY,
            'poll_interval_ms': 5000
        }

    now_utc = datetime.now(timezone.utc)
    elapsed = max(0, int((now_utc - last_received_utc).total_seconds()))

    if elapsed <= ONLINE_THRESHOLD_SEC:
        status = 'online'
    elif elapsed <= STALE_THRESHOLD_SEC:
        status = 'stale'
    else:
        status = 'offline'

    return {
        'status': status,
        'has_data': True,
        'seconds_since_update': elapsed,
        'last_received_utc': last_received_utc.isoformat(),
        'buffer_size': len(live_chart_buffer),
        'buffer_capacity': LIVE_BUFFER_CAPACITY,
        'poll_interval_ms': 5000
    }


def compute_session_stats():
    """Compute min/avg/max across the current in-memory live chart buffer."""
    if not live_chart_buffer:
        return None

    stats = {'count': len(live_chart_buffer)}
    for key in ('pm1', 'pm25', 'pm10'):
        values = [row[key] for row in live_chart_buffer if isinstance(row.get(key), (int, float))]
        if values:
            stats[key] = {
                'min': min(values),
                'avg': round(sum(values) / len(values), 1),
                'max': max(values)
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
    global latest_live_data, live_chart_buffer, last_received_utc

    # Security Check
    if request.headers.get('X-API-Key') != API_SECRET_KEY:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(force=True, silent=True)
    if not data:
        print("FAILED TO PARSE JSON. RAW BODY:", request.data)
        return jsonify({"error": "Invalid payload"}), 400

    # SCENARIO A: Pico sent a live ping (Dictionary)
    if isinstance(data, dict):
        timestamp_str = str(data.get('timestamp', ''))
        pm1 = int(data.get('pm1', 0))
        pm25 = int(data.get('pm25', 0))
        pm10 = int(data.get('pm10', 0))

        latest_live_data = {
            'time_full': timestamp_str,
            'pm1': pm1,
            'pm25': pm25,
            'pm10': pm10
        }
        last_received_utc = datetime.now(timezone.utc)

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
            if cursor:
                cursor.close()
            if conn:
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
    rows = []
    db_error = None

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
        if cursor:
            cursor.close()
        if conn:
            conn.close()

    return render_template(
        'history.html',
        active_page='history',
        rows=rows,
        db_error=db_error
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
