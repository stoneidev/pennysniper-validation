"""
BTC validation Step 1: Download data from Binance public API.

No API key needed. Binance limits ~1200 requests/min — generous.

Downloads:
  1. BTC/USDT spot 1-min klines, 2 years
  2. BTC/USDT perpetual futures 1-min klines, 2 years
  3. Funding rate history, 2 years (every 8 hours)
  4. BTC/USDT spot daily klines, 5 years
"""
import json
import time
import urllib.request
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

CACHE = Path("btc_cache")
CACHE.mkdir(exist_ok=True)


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int, base_url: str) -> list:
    """Fetch klines from Binance, paginated. Each call returns up to 1000."""
    out = []
    cur = start_ms
    while cur < end_ms:
        url = (
            f"{base_url}/klines"
            f"?symbol={symbol}&interval={interval}"
            f"&startTime={cur}&endTime={end_ms}&limit=1000"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "btc-val/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  fetch error: {e}, retrying after 5s")
            time.sleep(5)
            continue
        if not data:
            break
        out.extend(data)
        cur = data[-1][0] + 1
        time.sleep(0.05)
    return out


def klines_to_df(klines: list) -> pd.DataFrame:
    df = pd.DataFrame(klines, columns=[
        "open_ms", "open", "high", "low", "close", "volume",
        "close_ms", "quote_vol", "n_trades", "taker_buy_base", "taker_buy_quote", "ignore",
    ])
    for c in ["open", "high", "low", "close", "volume", "quote_vol", "taker_buy_base", "taker_buy_quote"]:
        df[c] = df[c].astype(float)
    df["timestamp"] = pd.to_datetime(df["open_ms"], unit="ms", utc=True)
    return df[["timestamp", "open", "high", "low", "close", "volume", "quote_vol", "n_trades"]]


def fetch_funding(symbol: str, start_ms: int, end_ms: int) -> list:
    out = []
    cur = start_ms
    while cur < end_ms:
        url = (
            f"https://fapi.binance.com/fapi/v1/fundingRate"
            f"?symbol={symbol}&startTime={cur}&endTime={end_ms}&limit=1000"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "btc-val/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  funding error: {e}, retry 5s")
            time.sleep(5)
            continue
        if not data:
            break
        out.extend(data)
        cur = data[-1]["fundingTime"] + 1
        time.sleep(0.05)
    return out


def main() -> None:
    end = int(datetime.utcnow().timestamp() * 1000)
    start_2y = int((datetime.utcnow() - timedelta(days=730)).timestamp() * 1000)
    start_5y = int((datetime.utcnow() - timedelta(days=1825)).timestamp() * 1000)

    # Spot daily 5y
    target = CACHE / "spot_daily_5y.parquet"
    if not target.exists():
        target_csv = CACHE / "spot_daily_5y.csv"
        if not target_csv.exists():
            print("Fetching BTC/USDT spot daily 5y...")
            kl = fetch_klines("BTCUSDT", "1d", start_5y, end, "https://api.binance.com/api/v3")
            df = klines_to_df(kl)
            df.to_csv(target_csv, index=False)
            print(f"  saved {len(df)} daily bars")

    # Spot 1min 2y — large file (~1M rows)
    target = CACHE / "spot_1m_2y.csv"
    if not target.exists():
        print("Fetching BTC/USDT spot 1m 2y (this takes a while, ~1M bars)...")
        kl = fetch_klines("BTCUSDT", "1m", start_2y, end, "https://api.binance.com/api/v3")
        df = klines_to_df(kl)
        df.to_csv(target, index=False)
        print(f"  saved {len(df)} 1-min bars to {target}")
    else:
        print(f"Spot 1m 2y already cached")

    # Perp 1min 2y
    target = CACHE / "perp_1m_2y.csv"
    if not target.exists():
        print("Fetching BTC/USDT perp 1m 2y...")
        kl = fetch_klines("BTCUSDT", "1m", start_2y, end, "https://fapi.binance.com/fapi/v1")
        df = klines_to_df(kl)
        df.to_csv(target, index=False)
        print(f"  saved {len(df)} perp 1-min bars")
    else:
        print(f"Perp 1m 2y already cached")

    # Funding rate 2y
    target = CACHE / "funding_2y.csv"
    if not target.exists():
        print("Fetching BTC/USDT funding rate 2y...")
        f = fetch_funding("BTCUSDT", start_2y, end)
        df = pd.DataFrame(f)
        df["fundingRate"] = df["fundingRate"].astype(float)
        df["timestamp"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
        df.to_csv(target, index=False)
        print(f"  saved {len(df)} funding records")
    else:
        print(f"Funding 2y already cached")

    print("\nDone. Cache size:")
    for f in sorted(CACHE.glob("*")):
        size_mb = f.stat().st_size / 1024 / 1024
        print(f"  {f.name}: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
