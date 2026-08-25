import os
from flask import Flask, request, jsonify
import mysql.connector
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)


# --- NEW GLOBAL VARIABLES ---
latest_live_data = None
data_buffer = []
live_chart_buffer = []

# Now you can safely pull your secrets using os.environ.get()
API_SECRET_KEY = os.environ.get("API_KEY", "fallback_default_key")
TIDB_HOST = os.environ.get("DB_HOST")
TIDB_USER = os.environ.get("DB_USER")
TIDB_PASSWORD = os.environ.get("DB_PASSWORD")

# --- UPDATE THESE WITH YOUR MYSQL CREDENTIALS ---
db_config = {
    'host': '{TIDB_HOST}',
    'user': '{TIDB_USER}',        # Change this if you use a different user
    'password': '{TIDB_PASSWORD}',         # Enter your MySQL password here
    'database': 'pms_data'
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

def init_db():
    # Connect without specifying the database so we can create it if it's missing
    conn = mysql.connector.connect(
        host=db_config['host'],
        user=db_config['user'],
        password=db_config['password'],
        database="pms_data",
    )
    c = conn.cursor()
    c.execute("CREATE DATABASE IF NOT EXISTS pms_data")
    c.execute("USE pms_data")

    current_day = datetime.now().strftime('%Y-%m-%d')

    # Create the table
    c.execute('''CREATE TABLE IF NOT EXISTS readings
                 (id INT AUTO_INCREMENT PRIMARY KEY,
                  timestamp DATETIME,
                  pm1 INT,
                  pm25 INT,
                  pm10 INT)''')
    conn.commit()
    conn.close()

@app.route('/api/data', methods=['GET'])
def get_dashboard_data():
    global latest_live_data
    try:
        conn = get_db_connection()
        c = conn.cursor(dictionary=True)
        c.execute("""
            SELECT timestamp, pm1, pm25, pm10 
            FROM (
                SELECT timestamp, pm1, pm25, pm10 
                FROM readings 
                ORDER BY timestamp DESC 
                LIMIT 20
            ) sub 
            ORDER BY timestamp ASC
        """)
        rows = c.fetchall()
        conn.close()

        history = []
        # Convert MySQL datetime objects to strings for JSON compatibility
        for row in rows:
            time_short = row['timestamp'].strftime('%H:%M:%S') if hasattr(row['timestamp'], 'strftime') else str(row['timestamps'])[11:19]
            history.append({
                'time_short': time_short,
                'pm1': row['pm1'],
                'pm25': row['pm25'],
                'pm10': row['pm10']
            })

        # Send back BOTH the 60-sec history and the 2-sec live data
        return jsonify({
            "history": history,
            "live": latest_live_data,
            "live_chart": live_chart_buffer
        })
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500
    
@app.route('/', methods=['GET'])
def home():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Air Quality Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 30px; background-color: #f8f9fa; }
            h1 { color: #333; margin-bottom: 20px; }
            .dashboard-container { display: flex; flex-wrap: wrap; gap: 20px; align-items: flex-start; }
            .card { background: #ffffff; border-radius: 12px; padding: 24px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); min-width: 280px; flex: 1; }
            .metric { margin-bottom: 16px; }
            .metric-label { font-size: 0.9em; color: #666; font-weight: 600; text-transform: uppercase; }
            .metric-value { font-size: 2.2em; font-weight: bold; margin-top: 4px; }
            .pm1-color { color: #22bgff; }
            .pm25-color { color: #007bff; }
            .pm10-color { color: #28a745; }
            .chart-container { background: #ffffff; border-radius: 12px; padding: 24px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); flex: 2; min-width: 350px; }
            .unit { font-size: 0.5em; color: #555; }
        </style>
    </head>
    <body>
        <h1>Live Air Quality Monitor</h1>
        
        <div class="dashboard-container">
            <div class="card">
                <h2>Latest Reading</h2>
                <p id="update-time" style="color: #888; font-size: 0.85em;">Fetching data...</p>
                <hr style="border: 0; border-top: 1px solid #eee; margin: 15px 0;">

                <div class="metric">
                    <div class="metric-label">PM 1.0 Concentration</div>
                    <div class="metric-value pm1-color" id="pm1-val">-- <span class="unit">µg/m³</span></div>
                </div>

                <div class="metric">
                    <div class="metric-label">PM 2.5 Concentration</div>
                    <div class="metric-value pm25-color" id="pm25-val">-- <span class="unit">µg/m³</span></div>
                </div>
                
                <div class="metric">
                    <div class="metric-label">PM 10 Concentration</div>
                    <div class="metric-value pm10-color" id="pm10-val">-- <span class="unit">µg/m³</span></div>
                </div>
            </div>
            
            <div class="chart-container">
                <canvas id="airQualityChart" height="200"></canvas>
            </div>
        </div>

        <script>
            // 1. Initialize the empty chart
            const ctx = document.getElementById('airQualityChart').getContext('2d');
            let airChart = new Chart(ctx, {
                type: 'line',
                data: { labels: [], datasets: [
                    { label: 'PM 1.0', data: [], borderColor: '#22bgff', backgroundColor: 'rgba(255,145,56,0.1)', borderWidth: 2, fill: true, tension: 0.3},
                    { label: 'PM 2.5', data: [], borderColor: '#007bff', backgroundColor: 'rgba(0,123,255,0.1)', borderWidth: 2, fill: true, tension: 0.3 },
                    { label: 'PM 10', data: [], borderColor: '#28a745', backgroundColor: 'rgba(40,167,69,0.1)', borderWidth: 2, fill: true, tension: 0.3 }
                ]},
                options: { responsive: true, animation: { duration: 800 }, scales: { y: { beginAtZero: true } } }
            });

            // 2. Define the function to fetch data and update the screen
            function fetchData() {
                // The timestamp makes every request look like a brand new, unique URL
                fetch('/api/data?t=' + new Date().getTime())
                    .then(response => response.json())
                    .then(data => {
                        // 1. Update the big numbers instantly (Every 2 seconds)
                        if (data.live) {
                            document.getElementById('update-time').innerText = 'Updated: ' + data.live.time_full;
                            document.getElementById('pm1-val').innerHTML = data.live.pm1 + ' <span class="unit">µg/m³</span>';
                            document.getElementById('pm25-val').innerHTML = data.live.pm25 + ' <span class="unit">µg/m³</span>';
                            document.getElementById('pm10-val').innerHTML = data.live.pm10 + ' <span class="unit">µg/m³</span>';
                        }

                        if (data.live_chart && data.live_chart.length > 0) {
                            airChart.data.labels = data.live_chart.map(row => row.time_short);
                            airChart.data.datasets[0].data = data.live_chart.map(row => row.pm1);
                            airChart.data.datasets[1].data = data.live_chart.map(row => row.pm25);
                            airChart.data.datasets[2].data = data.live_chart.map(row => row.pm10);
                            airChart.update();
                        }
                    })
                    .catch(err => console.error("Error fetching data: ", err));
            }

            // 3. Run immediately on load, then poll every 60 seconds (60000 ms)
            fetchData();
            setInterval(fetchData, 1000);
        </script>
    </body>
    </html>
    """
    return html

@app.route('/api/sensor', methods=['POST'])
def receive_data():
    global latest_live_data, last_db_write
    data = request.get_json()

    if not data or data['live_data']['pm1'] not in data or data['live_data']['pm25'] not in data or data['live_data']['pm10'] not in data:
        return jsonify({"error": "Invalid payload"}), 400

    current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 1. Update live memory for the web dashboard (every second)
    latest_live_data = {
        'time_full': current_time_str,
        'pm1': data['pm1'],
        'pm25': data['pm25'],
        'pm10': data['pm10']
    }

    # 2. Add the current reading to our RAM buffer
    # Notice we are using a Tuple ( ) inside the list for MySQL formatting
    data_buffer = data['data_buffer']

    # data_buffer.append({
    #     'timestamp': current_time_str, 
    #     'pm1': int(data['pm1']),
    #     'pm25': int(data['pm25']),
    #     'pm10': int(data['pm10'])

    # })
    print(f"Elements in buffer: {len(data_buffer)}")

    # Maintain a 60 second rolling window for the live chart
    time_short = current_time_str.split(' ')[1] # Get the HH:MM:SS
    live_chart_buffer.append({
        'time_short': time_short,
        'pm1': int(data['live_data']['pm1']),
        'pm25': int(data['live_data']['pm25']),
        'pm10': int(data['live_data']['pm10'])
    })

    if len(live_chart_buffer) > 300 :
        live_chart_buffer.pop(0)

    # 3. Once the packet reaches 60 elements, send it to the database
    if len(data_buffer) >= 60:
        try:
            conn = get_db_connection()
            c = conn.cursor()

            sql = "INSERT INTO readings (timestamp, pm1, pm25, pm10) VALUES (%(timestamp)s, %(pm1)s, %(pm25)s, %(pm10)s)"
            
            c.executemany(sql, data_buffer)
            conn.commit()
            conn.close()

            print("\n=======================================================")
            print(f"SUCCESS: Bulk saved {len(data_buffer)} readings to MySQL.")
            print("=======================================================\n")

            # Empty the packet to start collecting the next minute of data
            data_buffer.clear()

            # Tell the bridge the bulk was sent.
            return jsonify({"status": "bulk_success"}), 201

        except mysql.connector.Error as err:
            print(f"MySQL Error: {err}")
            return jsonify({"error": "Database error"}), 500
    return jsonify({"status": "success"}), 201

@app.route('/history', methods=['GET'])
def view_history():
    try:
        conn = get_db_connection()
        # dictionary=True allows us to access columns by name (e.g., row['pm25'])
        c = conn.cursor(dictionary=True) 
        
        # Fetch the last 100 readings, newest first
        c.execute("SELECT timestamp, pm1, pm25, pm10 FROM readings ORDER BY timestamp DESC LIMIT 100")
        rows = c.fetchall()
        conn.close()
        
        # Start building the HTML page
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Air Quality History</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; }
                table { border-collapse: collapse; width: 100%; max-width: 600px; }
                th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
                th { background-color: #f2f2f2; }
                tr:nth-child(even) { background-color: #f9f9f9; }
            </style>
        </head>
        <body>
            <h2>Last 100 Air Quality Readings</h2>
            <table>
                <tr>
                    <th>Timestamp</th>
                    <th>PM 1.5 (µg/m³)</th>
                    <th>PM 2.5 (µg/m³)</th>
                    <th>PM 10 (µg/m³)</th>
                </tr>
        """
        
        # Loop through the data and create a table row for each reading
        for row in rows:
            html += f"""
                <tr>
                    <td>{row['timestamp']}</td>
                    <td>{row['pm1']}</td>
                    <td>{row['pm25']}</td>
                    <td>{row['pm10']}</td>
                </tr>
            """
            
        # Close the HTML tags
        html += """
            </table>
        </body>
        </html>
        """
        
        return html
        
    except mysql.connector.Error as err:
        return f"<h3>Database Error:</h3><p>{err}</p>"

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)