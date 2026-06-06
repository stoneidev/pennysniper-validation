"""
XRP data download — same as BTC pipeline.
"""
import json, time, urllib.request
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

CACHE = Path("xrp_cache")
CACHE.mkdir(exist_ok=True)


def fetch_klines(symbol, interval, start_ms, end_ms, base):
    out = []
    cur = start_ms
    while cur < end_ms:
        url = f"{base}/klines?symbol={symbol}&interval={interval}&startTime={cur}&endTime={end_ms}&limit=1000"
        req = urllib.request.Request(url, headers={"User-Agent": "xrp-val/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  err: {e}")
            time.sleep(5)
            continue
        if not data:
            break
        out.extend(data)
        cur = data[-1][0] + 1
        time.sleep(0.05)
    return out


def klines_to_df(klines):
    df = pd.DataFrame(klines, columns=[
        "open_ms", "open", "high", "low", "close", "volume",
        "close_ms", "quote_vol", "n_trades", "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    for c in ["open", "high", "low", "close", "volume", "quote_vol", "taker_buy_base", "taker_buy_quote"]:
        df[c] = df[c].astype(float)
    df["timestamp"] = pd.to_datetime(df["open_ms"], unit="ms", utc=True)
    return df[["timestamp", "open", "high", "low", "close", "volume", "quote_vol", "n_trades"]]


def fetch_funding(symbol, start_ms, end_ms):
    out = []
    cur = start_ms
    while cur < end_ms:
        url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={symbol}&startTime={cur}&endTime={end_ms}&limit=1000"
        req = urllib.request.Request(url, headers={"User-Agent": "xrp-val/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  err: {e}")
            time.sleep(5)
            continue
        if not data:
            break
        out.extend(data)
        cur = data[-1]["fundingTime"] + 1
        time.sleep(0.05)
    return out


def main():
    end = int(datetime.utcnow().timestamp() * 1000)
    start_2y = int((datetime.utcnow() - timedelta(days=730)).timestamp() * 1000)

    # Funding (fastest, smallest)
    target = CACHE / "funding_2y.csv"
    if not target.exists():
        print("Fetching XRP funding 2y...")
        f = fetch_funding("XRPUSDT", start_2y, end)
        df = pd.DataFrame(f)
        df["fundingRate"] = df["fundingRate"].astype(float)
        df["timestamp"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
        df.to_csv(target, index=False)
        print(f"  {len(df)} records")

    # Spot 1m 2y
    target = CACHE / "spot_1m_2y.csv"
    if not target.exists():
        print("Fetching XRP spot 1m 2y...")
        kl = fetch_klines("XRPUSDT", "1m", start_2y, end, "https://api.binance.com/api/v3")
        df = klines_to_df(kl)
        df.to_csv(target, index=False)
        print(f"  {len(df)} bars")

    # Daily 5y
    start_5y = int((datetime.utcnow() - timedelta(days=1825)).timestamp() * 1000)
    target = CACHE / "spot_daily_5y.csv"
    if not target.exists():
        print("Fetching XRP daily 5y...")
        kl = fetch_klines("XRPUSDT", "1d", start_5y, end, "https://api.binance.com/api/v3")
        df = klines_to_df(kl)
        df.to_csv(target, index=False)

    print("\nDone.")
    for f in sorted(CACHE.glob("*")):
        print(f"  {f.name}: {f.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
