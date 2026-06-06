"""Quick: fetch funding rate only, run analysis without waiting for 1m bars."""
import json, urllib.request, time
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

CACHE = Path("btc_cache")
CACHE.mkdir(exist_ok=True)
target = CACHE / "funding_2y.csv"

if not target.exists():
    end = int(datetime.utcnow().timestamp() * 1000)
    start = int((datetime.utcnow() - timedelta(days=730)).timestamp() * 1000)
    out = []
    cur = start
    print("Fetching funding rate 2y...")
    while cur < end:
        url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&startTime={cur}&endTime={end}&limit=1000"
        req = urllib.request.Request(url, headers={"User-Agent": "btc-val/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  err: {e}")
            time.sleep(5)
            continue
        if not data: break
        out.extend(data)
        cur = data[-1]["fundingTime"] + 1
        time.sleep(0.05)
    df = pd.DataFrame(out)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df["timestamp"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df.to_csv(target, index=False)
    print(f"Saved {len(df)} records")
else:
    print(f"Already cached: {target}")
