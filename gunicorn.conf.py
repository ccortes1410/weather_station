# Automatically loaded by Gunicorn on Render (gunicorn pms_api:app)
# Single process keeps in-memory live_chart_buffer & TTLCache unified;
# threads allow concurrent Pico pings + dashboard polls during TiDB queries.
workers = 1
threads = 4
timeout = 90
keepalive = 5
