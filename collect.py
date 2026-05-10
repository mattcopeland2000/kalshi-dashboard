import os
import requests
import psycopg2
import time
from datetime import date

DATABASE_URL = os.environ.get("DATABASE_URL")

def setup_database(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS volume_snapshots (
                snapshot_date DATE PRIMARY KEY,
                total_volume  BIGINT,
                market_count  INT,
                captured_at   TIMESTAMPTZ DEFAULT now()
            );
        """)
        conn.commit()

def fetch_total_volume():
    total_volume = 0
    market_count = 0
    cursor = None
    base_url = "https://external-api.kalshi.com/trade-api/v2/markets"

    page = 1
    while True:
        print(f"Fetching page {page}...")
        params = {"limit": 200, "status": "open"}
        if cursor:
            params["cursor"] = cursor

        response = requests.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()

        markets = data.get("markets", [])
        print(f"Page {page} returned {len(markets)} markets")
        for market in markets:
            total_volume += market.get("volume", 0)
            market_count += 1

        cursor = data.get("cursor")
        if not cursor:
            print("No more pages, done fetching.")
            break

        print(f"Waiting 3 seconds before next page...")
        time.sleep(3)
        page += 1

    return total_volume, market_count

def save_snapshot(conn, total_volume, market_count):
    today = date.today()
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO volume_snapshots (snapshot_date, total_volume, market_count)
            VALUES (%s, %s, %s)
            ON CONFLICT (snapshot_date) DO UPDATE
            SET total_volume = EXCLUDED.total_volume,
                market_count = EXCLUDED.market_count,
                captured_at  = now();
        """, (today, total_volume, market_count))
        conn.commit()

def main():
    print("Connecting to database...")
    conn = psycopg2.connect(DATABASE_URL)

    print("Setting up database table if needed...")
    setup_database(conn)

    print("Fetching volume data from Kalshi...")
    total_volume, market_count = fetch_total_volume()
    print(f"Total volume: {total_volume:,} contracts across {market_count} markets")

    print("Saving snapshot to database...")
    save_snapshot(conn, total_volume, market_count)

    conn.close()
    print("Done.")

if __name__ == "__main__":
    main()

