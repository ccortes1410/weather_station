import os
import time
from typing import Any, Dict, List, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()

from flask import Flask, Response, request, jsonify, render_template
import mysql.connector
import certifi

from cache import TTLCache

app = Flask(__name__)

# --- CONFIG & SECRETS ---
API_SECRET_KEY = os.getenv("API_KEY", "fallback_default_key")
TIDB_HOST = os.getenv("DB_HOST")
TIDB_USER = os.getenv("DB_USERNAME")
TIDB_PASSWORD = os.getenv("DB_PASSWORD")

# Pico logs timestamps in Chile Standard Time (UTC-4 = -14400s, see main.py)
PICO_TZ_OFFSET_SEC = -14400

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

# --- IN-MEMORY LIVE STATE & QUERY CACHE ---
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
query_cache = TTLCache(max_entries=64)


def get_db_connection() -> Any:
    return mysql.connector.connect(**db_config)


def pico_now_epoch() -> int:
    """Return current epoch shifted to the Pico's UTC-4 timestamp clock."""
    return int(time.time()) + PICO_TZ_OFFSET_SEC


def epoch_to_sql_dt(epoch_sec: int) -> str:
    t = time.gmtime(epoch_sec)
    return f"{t[0]:04d}-{t[1]:02d}-{t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}"


def sanitize_datetime_param(raw: Optional[str], is_end: bool = False) -> Optional[str]:
    """Validate YYYY-MM-DD or YYYY-MM-DD HH:MM(:SS) / YYYY-MM-DDTHH:MM(:SS)."""
    if not raw:
        return None
    val = raw.strip().replace('T', ' ')
    if len(val) == 10:
        parts = val.split('-')
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
            if 2000 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31:
                return f"{val} {'23:59:59' if is_end else '00:00:00'}"
        return None

    if len(val) in (16, 19) and ' ' in val:
        date_part, time_part = val.split(' ', 1)
        d_parts = date_part.split('-')
        t_parts = time_part.split(':')
        if (
            len(d_parts) == 3
            and all(p.isdigit() for p in d_parts)
            and len(t_parts) in (2, 3)
            and all(p.isdigit() for p in t_parts)
        ):
            y, m, d = int(d_parts[0]), int(d_parts[1]), int(d_parts[2])
            hh, mm = int(t_parts[0]), int(t_parts[1])
            ss = int(t_parts[2]) if len(t_parts) == 3 else (59 if is_end else 0)
            if (
                2000 <= y <= 2100
                and 1 <= m <= 12
                and 1 <= d <= 31
                and 0 <= hh <= 23
                and 0 <= mm <= 59
                and 0 <= ss <= 59
            ):
                return f"{y:04d}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}:{ss:02d}"
    return None


def parse_optional_int(raw: Optional[str], minimum: int = 0, maximum: int = 10000) -> Optional[int]:
    if raw is None or raw.strip() == '':
        return None
    try:
        val = int(raw.strip())
    except ValueError:
        return None
    if val < minimum:
        return minimum
    if val > maximum:
        return maximum
    return val


def build_history_filters(args: Any) -> Dict[str, Any]:
    """Parse request query arguments into validated SQL WHERE clauses and metadata."""
    preset = (args.get('range') or '24h').strip().lower()
    if preset not in ('1h', '24h', '7d', '30d', 'all', 'custom'):
        preset = '24h'

    start_raw = args.get('start')
    end_raw = args.get('end')
    start_dt = sanitize_datetime_param(start_raw, is_end=False)
    end_dt = sanitize_datetime_param(end_raw, is_end=True)

    if start_dt or end_dt:
        preset = 'custom'

    now_ep = pico_now_epoch()
    span_hours = 24

    if preset == '1h':
        start_dt = epoch_to_sql_dt(now_ep - 3600)
        end_dt = None
        span_hours = 1
    elif preset == '24h':
        start_dt = epoch_to_sql_dt(now_ep - 86400)
        end_dt = None
        span_hours = 24
    elif preset == '7d':
        start_dt = epoch_to_sql_dt(now_ep - 7 * 86400)
        end_dt = None
        span_hours = 168
    elif preset == '30d':
        start_dt = epoch_to_sql_dt(now_ep - 30 * 86400)
        end_dt = None
        span_hours = 720
    elif preset == 'all':
        start_dt = None
        end_dt = None
        span_hours = 720
    else:
        # Custom range: estimate span to pick bucket granularity
        span_hours = 168
        if start_dt and end_dt and start_dt > end_dt:
            start_dt, end_dt = end_dt[:10] + ' 00:00:00', start_dt[:10] + ' 23:59:59'
        if start_dt and end_dt:
            try:
                sy, sm, sd = int(start_dt[0:4]), int(start_dt[5:7]), int(start_dt[8:10])
                ey, em, ed = int(end_dt[0:4]), int(end_dt[5:7]), int(end_dt[8:10])
                approx_days = max(1, (ey - sy) * 365 + (em - sm) * 30 + (ed - sd) + 1)
                span_hours = approx_days * 24
            except ValueError:
                span_hours = 168

    level = (args.get('level') or 'all').strip().lower()
    valid_levels = ('all', 'good_only', 'regular_plus', 'alert_plus', 'preemergency_plus', 'emergency_plus')
    if level not in valid_levels:
        level = 'all'

    min_pm25 = parse_optional_int(args.get('min_pm25'), 0, 5000)
    max_pm25 = parse_optional_int(args.get('max_pm25'), 0, 5000)
    if min_pm25 is not None and max_pm25 is not None and min_pm25 > max_pm25:
        min_pm25, max_pm25 = max_pm25, min_pm25

    limit_val = parse_optional_int(args.get('limit'), 10, 1000) or 100
    sort_dir = 'ASC' if (args.get('sort') or 'desc').strip().lower() == 'asc' else 'DESC'

    clauses: List[str] = []
    params: List[Any] = []

    if start_dt is not None:
        clauses.append("timestamp >= %s")
        params.append(start_dt)
    if end_dt is not None:
        clauses.append("timestamp <= %s")
        params.append(end_dt)

    if level == 'good_only':
        clauses.append("(pm25 < 50 AND pm10 < 150)")
    elif level == 'regular_plus':
        clauses.append("(pm25 >= 50 OR pm10 >= 150)")
    elif level == 'alert_plus':
        clauses.append("(pm25 >= 80 OR pm10 >= 195)")
    elif level == 'preemergency_plus':
        clauses.append("(pm25 >= 110 OR pm10 >= 240)")
    elif level == 'emergency_plus':
        clauses.append("(pm25 >= 170 OR pm10 >= 330)")

    if min_pm25 is not None:
        clauses.append("pm25 >= %s")
        params.append(min_pm25)
    if max_pm25 is not None:
        clauses.append("pm25 <= %s")
        params.append(max_pm25)

    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    # Choose bucket expression based on span_hours (using %s param to avoid %% escaping issues)
    if span_hours <= 2:
        bucket_label = '1 min'
        bucket_expr = "DATE_FORMAT(timestamp, %s)"
        bucket_fmt = "%Y-%m-%d %H:%i:00"
        ttl_sec = 60
    elif span_hours <= 48:
        bucket_label = '5 min'
        bucket_expr = "CONCAT(DATE_FORMAT(timestamp, %s), LPAD((MINUTE(timestamp) DIV 5) * 5, 2, '0'), ':00')"
        bucket_fmt = "%Y-%m-%d %H:"
        ttl_sec = 180
    elif span_hours <= 336:
        bucket_label = '1 hour'
        bucket_expr = "DATE_FORMAT(timestamp, %s)"
        bucket_fmt = "%Y-%m-%d %H:00:00"
        ttl_sec = 300
    else:
        bucket_label = '6 hours'
        bucket_expr = "CONCAT(DATE_FORMAT(timestamp, %s), LPAD((HOUR(timestamp) DIV 6) * 6, 2, '0'), ':00:00')"
        bucket_fmt = "%Y-%m-%d "
        ttl_sec = 600

    cache_key = (
        f"hist|{preset}|{start_dt or ''}|{end_dt or ''}|{level}|"
        f"{min_pm25 if min_pm25 is not None else ''}|"
        f"{max_pm25 if max_pm25 is not None else ''}|{limit_val}|{sort_dir}"
    )

    return {
        'preset': preset,
        'start_input': (start_raw or '').strip(),
        'end_input': (end_raw or '').strip(),
        'start_dt': start_dt,
        'end_dt': end_dt,
        'level': level,
        'min_pm25': min_pm25,
        'max_pm25': max_pm25,
        'limit': limit_val,
        'sort': sort_dir.lower(),
        'sort_sql': sort_dir,
        'where_sql': where_sql,
        'params': params,
        'bucket_label': bucket_label,
        'bucket_expr': bucket_expr,
        'bucket_fmt': bucket_fmt,
        'ttl_sec': ttl_sec,
        'cache_key': cache_key
    }


def fetch_history_bundle(flt: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Fetch filtered summary, bucketed series, hourly pattern, and raw table rows (TTL-cached)."""
    cached = query_cache.get(flt['cache_key'])
    if cached is not None:
        return cached, True

    conn = None
    cursor = None
    where_sql: str = flt['where_sql']
    params: List[Any] = flt['params']

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Summary statistics across the filtered window
        cursor.execute(
            f"SELECT COUNT(*) AS total_count, "
            f"ROUND(AVG(pm1), 1) AS avg_pm1, MIN(pm1) AS min_pm1, MAX(pm1) AS max_pm1, "
            f"ROUND(AVG(pm25), 1) AS avg_pm25, MIN(pm25) AS min_pm25, MAX(pm25) AS max_pm25, "
            f"ROUND(AVG(pm10), 1) AS avg_pm10, MIN(pm10) AS min_pm10, MAX(pm10) AS max_pm10, "
            f"MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts "
            f"FROM readings {where_sql}",
            params if params else None
        )
        summary_row = cursor.fetchone() or {}
        summary = {
            'total_count': int(summary_row.get('total_count') or 0),
            'avg_pm1': float(summary_row['avg_pm1']) if summary_row.get('avg_pm1') is not None else None,
            'min_pm1': int(summary_row['min_pm1']) if summary_row.get('min_pm1') is not None else None,
            'max_pm1': int(summary_row['max_pm1']) if summary_row.get('max_pm1') is not None else None,
            'avg_pm25': float(summary_row['avg_pm25']) if summary_row.get('avg_pm25') is not None else None,
            'min_pm25': int(summary_row['min_pm25']) if summary_row.get('min_pm25') is not None else None,
            'max_pm25': int(summary_row['max_pm25']) if summary_row.get('max_pm25') is not None else None,
            'avg_pm10': float(summary_row['avg_pm10']) if summary_row.get('avg_pm10') is not None else None,
            'min_pm10': int(summary_row['min_pm10']) if summary_row.get('min_pm10') is not None else None,
            'max_pm10': int(summary_row['max_pm10']) if summary_row.get('max_pm10') is not None else None,
            'first_ts': str(summary_row['first_ts']) if summary_row.get('first_ts') is not None else None,
            'last_ts': str(summary_row['last_ts']) if summary_row.get('last_ts') is not None else None
        }

        # 2. Time-bucketed trend series (capped to 1000 buckets for UI smoothness)
        bucket_expr = flt['bucket_expr']
        bucket_params = [flt['bucket_fmt']] + params
        cursor.execute(
            f"SELECT {bucket_expr} AS bucket, "
            f"ROUND(AVG(pm1), 1) AS pm1, "
            f"ROUND(AVG(pm25), 1) AS pm25, "
            f"ROUND(AVG(pm10), 1) AS pm10, "
            f"MIN(pm25) AS min_pm25, "
            f"MAX(pm25) AS max_pm25, "
            f"COUNT(*) AS samples "
            f"FROM readings {where_sql} "
            f"GROUP BY bucket ORDER BY bucket ASC LIMIT 1000",
            bucket_params
        )
        raw_series = cursor.fetchall() or []
        series: List[Dict[str, Any]] = []
        for r in raw_series:
            series.append({
                'bucket': str(r.get('bucket') or ''),
                'pm1': float(r['pm1']) if r.get('pm1') is not None else 0.0,
                'pm25': float(r['pm25']) if r.get('pm25') is not None else 0.0,
                'pm10': float(r['pm10']) if r.get('pm10') is not None else 0.0,
                'min_pm25': int(r['min_pm25']) if r.get('min_pm25') is not None else 0,
                'max_pm25': int(r['max_pm25']) if r.get('max_pm25') is not None else 0,
                'samples': int(r.get('samples') or 0)
            })

        # 3. Hourly time-of-day profile (0..23)
        cursor.execute(
            f"SELECT HOUR(timestamp) AS hr, "
            f"ROUND(AVG(pm25), 1) AS avg_pm25, "
            f"ROUND(AVG(pm10), 1) AS avg_pm10, "
            f"COUNT(*) AS samples "
            f"FROM readings {where_sql} "
            f"GROUP BY hr ORDER BY hr ASC",
            params if params else None
        )
        hourly_rows = cursor.fetchall() or []
        by_hour: Dict[int, Dict[str, Any]] = {}
        for hr_row in hourly_rows:
            if hr_row.get('hr') is not None:
                h = int(hr_row['hr'])
                by_hour[h] = {
                    'hour': h,
                    'label': f"{h:02d}:00",
                    'pm25': float(hr_row['avg_pm25']) if hr_row.get('avg_pm25') is not None else 0.0,
                    'pm10': float(hr_row['avg_pm10']) if hr_row.get('avg_pm10') is not None else 0.0,
                    'samples': int(hr_row.get('samples') or 0)
                }

        hourly_profile: List[Dict[str, Any]] = []
        for h in range(24):
            if h in by_hour:
                hourly_profile.append(by_hour[h])
            else:
                hourly_profile.append({'hour': h, 'label': f"{h:02d}:00", 'pm25': None, 'pm10': None, 'samples': 0})

        # 4. Raw table rows matching the filter
        sort_sql = flt['sort_sql']
        limit_val = int(flt['limit'])
        cursor.execute(
            f"SELECT timestamp, pm1, pm25, pm10 FROM readings "
            f"{where_sql} ORDER BY timestamp {sort_sql} LIMIT %s",
            params + [limit_val]
        )
        fetched_rows = cursor.fetchall() or []
        rows: List[Dict[str, Any]] = []
        for row in fetched_rows:
            rows.append({
                'timestamp': str(row.get('timestamp') or ''),
                'pm1': int(row['pm1']) if row.get('pm1') is not None else 0,
                'pm25': int(row['pm25']) if row.get('pm25') is not None else 0,
                'pm10': int(row['pm10']) if row.get('pm10') is not None else 0
            })

        bundle: Dict[str, Any] = {
            'filters': {
                'range': flt['preset'],
                'start': flt['start_input'] or (flt['start_dt'][:10] if flt['start_dt'] else ''),
                'end': flt['end_input'] or (flt['end_dt'][:10] if flt['end_dt'] else ''),
                'start_dt': flt['start_dt'],
                'end_dt': flt['end_dt'],
                'level': flt['level'],
                'min_pm25': flt['min_pm25'],
                'max_pm25': flt['max_pm25'],
                'limit': flt['limit'],
                'sort': flt['sort'],
                'bucket_label': flt['bucket_label']
            },
            'summary': summary,
            'series': series,
            'hourly_profile': hourly_profile,
            'rows': rows
        }

        query_cache.set(flt['cache_key'], bundle, flt['ttl_sec'])
        return bundle, False
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


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


@app.route('/api/stats', methods=['GET'])
def get_rolling_stats():
    """Return 24-hour rolling averages & peak hour from TiDB (cached 5 min in RAM)."""
    cache_key = 'rolling_24h_stats'
    cached = query_cache.get(cache_key)
    if cached is not None:
        resp = jsonify(cached)
        resp.headers['X-Cache'] = 'HIT'
        return resp

    cutoff_dt = epoch_to_sql_dt(pico_now_epoch() - 86400)
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT COUNT(*) AS samples, "
            "ROUND(AVG(pm1), 1) AS avg_pm1, "
            "ROUND(AVG(pm25), 1) AS avg_pm25, MIN(pm25) AS min_pm25, MAX(pm25) AS max_pm25, "
            "ROUND(AVG(pm10), 1) AS avg_pm10, MIN(pm10) AS min_pm10, MAX(pm10) AS max_pm10 "
            "FROM readings WHERE timestamp >= %s",
            [cutoff_dt]
        )
        row = cursor.fetchone() or {}

        cursor.execute(
            "SELECT HOUR(timestamp) AS hr, ROUND(AVG(pm25), 1) AS avg_pm25 "
            "FROM readings WHERE timestamp >= %s "
            "GROUP BY hr ORDER BY avg_pm25 DESC LIMIT 1",
            [cutoff_dt]
        )
        peak_row = cursor.fetchone()

        payload: Dict[str, Any] = {
            'window': '24h',
            'since': cutoff_dt,
            'samples': int(row.get('samples') or 0),
            'avg_pm1': float(row['avg_pm1']) if row.get('avg_pm1') is not None else None,
            'avg_pm25': float(row['avg_pm25']) if row.get('avg_pm25') is not None else None,
            'min_pm25': int(row['min_pm25']) if row.get('min_pm25') is not None else None,
            'max_pm25': int(row['max_pm25']) if row.get('max_pm25') is not None else None,
            'avg_pm10': float(row['avg_pm10']) if row.get('avg_pm10') is not None else None,
            'min_pm10': int(row['min_pm10']) if row.get('min_pm10') is not None else None,
            'max_pm10': int(row['max_pm10']) if row.get('max_pm10') is not None else None,
            'peak_hour': f"{int(peak_row['hr']):02d}:00" if peak_row and peak_row.get('hr') is not None else None,
            'peak_hour_pm25': float(peak_row['avg_pm25']) if peak_row and peak_row.get('avg_pm25') is not None else None
        }
        query_cache.set(cache_key, payload, 300)
        resp = jsonify(payload)
        resp.headers['X-Cache'] = 'MISS'
        return resp
    except mysql.connector.Error as err:
        return jsonify({'error': str(err), 'samples': 0}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


@app.route('/api/history', methods=['GET'])
def api_history():
    flt = build_history_filters(request.args)
    try:
        bundle, hit = fetch_history_bundle(flt)
        resp = jsonify(bundle)
        resp.headers['X-Cache'] = 'HIT' if hit else 'MISS'
        return resp
    except mysql.connector.Error as err:
        return jsonify({'error': str(err)}), 500


@app.route('/api/export', methods=['GET'])
def export_csv():
    """Download filtered historical readings as a CSV file."""
    flt = build_history_filters(request.args)
    where_sql = flt['where_sql']
    params = flt['params']
    sort_sql = flt['sort_sql']

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT timestamp, pm1, pm25, pm10 FROM readings "
            f"{where_sql} ORDER BY timestamp {sort_sql} LIMIT 100000",
            params if params else None
        )
        all_rows = cursor.fetchall() or []
    except mysql.connector.Error as err:
        return jsonify({'error': str(err)}), 500
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

    def generate():
        yield "timestamp,pm1,pm25,pm10\r\n"
        for r in all_rows:
            ts = str(r[0]) if r[0] is not None else ""
            p1 = r[1] if r[1] is not None else ""
            p25 = r[2] if r[2] is not None else ""
            p10 = r[3] if r[3] is not None else ""
            yield f"{ts},{p1},{p25},{p10}\r\n"

    label = flt['preset']
    if flt['start_dt'] and flt['end_dt']:
        label = f"{flt['start_dt'][:10]}_to_{flt['end_dt'][:10]}"
    elif flt['start_dt']:
        label = f"from_{flt['start_dt'][:10]}"

    filename = f"air_quality_{label}.csv"
    return Response(
        generate(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


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
            'pm25_raw': pm25,
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
            query_cache.clear()

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
    # Default to 'all' if no range parameter was provided so existing data is always visible immediately
    args_dict: Dict[str, str] = {}
    for k, v in request.args.items():
        args_dict[k] = v
    if 'range' not in args_dict and 'start' not in args_dict and 'end' not in args_dict:
        args_dict['range'] = '7d'

    flt = build_history_filters(args_dict)
    bundle: Optional[Dict[str, Any]] = None
    db_error: Optional[str] = None

    try:
        bundle, _ = fetch_history_bundle(flt)
        # If 7d had 0 readings (e.g. sensor was paused), automatically widen default initial view to 'all'
        if (
            bundle['summary']['total_count'] == 0
            and 'range' not in request.args
            and 'start' not in request.args
            and 'end' not in request.args
        ):
            args_dict['range'] = 'all'
            flt = build_history_filters(args_dict)
            bundle, _ = fetch_history_bundle(flt)
    except mysql.connector.Error as err:
        db_error = str(err)

    rows = bundle['rows'] if bundle else []
    return render_template(
        'history.html',
        active_page='history',
        rows=rows,
        initial_bundle=bundle,
        db_error=db_error
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
