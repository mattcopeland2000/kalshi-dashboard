import os
import requests
import psycopg2
import time
from datetime import date, datetime, timezone

DATABASE_URL = os.environ.get("DATABASE_URL")
BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

def setup_database(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_volumes (
                trade_date   DATE PRIMARY KEY,
                total_volume NUMERIC,
                trade_count  BIGINT,
                captured_at  TIMESTAMPTZ DEFAULT now()
            );
        """)
        conn.commit()

def day_to_timestamps(d):
    start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)
    end   = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)
    return int(start.timestamp()), int(end.timestamp())

def fetch_volume_for_day(d):
    min_ts, max_ts = day_to_timestamps(d)
    total_volume = 0
    trade_count  = 0
    cursor = None
    page = 1

    while True:
        print(f"  Page {page}...")
        params = {
            "limit":  1000,
            "min_ts": min_ts,
            "max_ts": max_ts,
        }
        if cursor:
            params["cursor"] = cursor

        response = requests.get(f"{BASE_URL}/markets/trades", params=params)

        if response.status_code == 429:
            print("  Rate limited, waiting 5 seconds...")
            time.sleep(5)
            continue

        response.raise_for_status()
        data = response.json()

        trades = data.get("trades", [])
        for trade in trades:
            count = float(trade.get("count_fp", 0))
            total_volume += count
            trade_count  += 1

        cursor = data.get("cursor")
        if not cursor or not trades:
            break

        page += 1
        time.sleep(0.5)

    return total_volume, trade_count

def save_day(conn, d, total_volume, trade_count):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO daily_volumes (trade_date, total_volume, trade_count)
            VALUES (%s, %s, %s)
            ON CONFLICT (trade_date) DO UPDATE
            SET total_volume = EXCLUDED.total_volume,
                trade_count  = EXCLUDED.trade_count,
                captured_at  = now();
        """, (d, total_volume, trade_count))
        conn.commit()

def get_existing_dates(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT trade_date FROM daily_volumes ORDER BY trade_date;")
        return set(row[0] for row in cur.fetchall())

def main():
    print("Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)

    print("Setting up database...")
    setup_database(conn)

    existing_dates = get_existing_dates(conn)
    today = date.today()

    # Fetch historical data going back 90 days if not already stored
    from datetime import timedelta
    start_date = today - timedelta(days=90)
    current = start_date

    while current <= today:
        if current in existing_dates and current != today:
            print(f"Skipping {current} (already stored)")
            current += timedelta(days=1)
            continue

        print(f"Fetching trades for {current}...")
        total_volume, trade_count = fetch_volume_for_day(current)
        print(f"  {current}: {total_volume:,.0f} contracts across {trade_count:,} trades")
        save_day(conn, current, total_volume, trade_count)
        current += timedelta(days=1)

        if current <= today:
            time.sleep(1)

    conn.close()
    print("Done.")

if __name__ == "__main__":
    main()
