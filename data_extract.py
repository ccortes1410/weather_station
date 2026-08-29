import os
from dotenv import load_dotenv

import csv

import mysql.connector
import certifi

from datetime import datetime, timedelta

load_dotenv()
# Database configuration
TIDB_HOST = os.getenv("DB_HOST")
TIDB_USER = os.getenv("DB_USERNAME")
TIDB_PASSWORD = os.getenv("DB_PASSWORD")


db_config = {
    'host': TIDB_HOST,
    'user': TIDB_USER,        # Change this if you use a different user
    'password': TIDB_PASSWORD,         # Enter your MySQL password here
    'database': 'pms_data',
    'port': 4000,
    'ssl_verify_cert': True,
    'ssl_verify_identity': False,
    'ssl_ca': certifi.where()
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

def file_exists(filename):
    try:
        os.stat(path=filename)
        return True
    except:
        return False

def fetch_data(cols: list[str], date):

    if isinstance(date, str):
         date_sql = date.strip('\'')
        # year = int(date.split('-')[0])
        # month = int(date.split('-')[1])
        # day = int(date.split('-')[2])
    else:
         date_sql = date

    cols_sql = ""

    # date_sql = f"`{datetime.date(year, month, day)}`"

    for i in range(0, len(cols)):
        if i != len(cols) - 1:
            cols_sql += f"`{cols[i]}`, "
        else:
            cols_sql += f"`{cols[i]}`"

    conn = get_db_connection()
    c = conn.cursor()

    sql = f"SELECT `timestamp` as `date`, {cols_sql} FROM `readings` WHERE DATE(`timestamp`) = '{date_sql}';"
    c.execute(sql)

    data = c.fetchall()
    conn.close()

    return data

today = datetime.today()

for i in range(0,7):
    target_date = today - timedelta(days=i)
    target_date = datetime.date(target_date).isoformat()
    target_date_file = str.split(target_date, '-')[0] + '_' + str.split(target_date, '-')[1] + '_' + str.split(target_date, '-')[2]

    filepath = f"data/pm_data_{target_date_file}.csv"

    if file_exists(filepath):

        pm_data = fetch_data(['pm1', 'pm25', 'pm10'], target_date)
        
        headers = ["date", "pm1", "pm25", "pm10"]

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            try:
                writer.writerow(headers)
                for row in pm_data:
                    writer.writerow(row)
                f.close()
            except Exception as e:
                print(f"Error writing data to file: {e}")
                f.close()
    else:
        pm_data = fetch_data(['pm1', 'pm25', 'pm10'], target_date)
                
        headers = ["date", "pm1", "pm25", "pm10"]

        with open(filepath, "a", newline="") as f:
            writer = csv.writer(f)
            try:
                writer.writerow(headers)
                for row in pm_data:
                    writer.writerow(row)
                f.close()
            except Exception as e:
                print(f"Error writing data to file: {e}")
                f.close()
