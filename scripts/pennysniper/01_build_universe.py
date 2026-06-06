"""
Step 1: Build penny stock universe.

Pull NASDAQ-listed tickers, filter by recent price ($1-$10) and minimum
average volume. Saves universe.csv for downstream steps.

Note on bias: yfinance does not include delisted tickers. Stocks that went
to zero or got delisted are silently absent from this universe. This means
our backtest will systematically OVERESTIMATE returns (survivorship bias).
"""
import io
import time
import pandas as pd
import yfinance as yf
import urllib.request

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OUT_CSV = "universe.csv"

PRICE_MIN = 1.0
PRICE_MAX = 10.0
MIN_AVG_DOLLAR_VOL = 1_000_000  # $1M ADV (relaxed from PRD's $5M for sample size)
LOOKBACK_DAYS = 90


def fetch_nasdaq_symbols() -> list[str]:
    print("Fetching NASDAQ-listed tickers...")
    req = urllib.request.Request(
        NASDAQ_LISTED_URL,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    df = pd.read_csv(io.StringIO(text), sep="|")
    # Last row is a footer "File Creation Time"
    df = df[df["Symbol"].notna() & ~df["Symbol"].str.contains("File", na=False)]
    # Exclude test issues, ETFs (rough)
    df = df[df.get("Test Issue", "N") == "N"]
    df = df[df.get("ETF", "N") == "N"]
    # Exclude tickers with non-standard chars (warrants, units)
    df = df[~df["Symbol"].str.contains(r"\$|\.|=", regex=True, na=False)]
    symbols = df["Symbol"].tolist()
    print(f"  Found {len(symbols)} candidate symbols")
    return symbols


def screen_universe(symbols: list[str], batch_size: int = 100) -> pd.DataFrame:
    """Download recent OHLCV in batches and filter to penny range."""
    rows = []
    n_batches = (len(symbols) + batch_size - 1) // batch_size
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        b_idx = i // batch_size + 1
        print(f"  Batch {b_idx}/{n_batches}: downloading {len(batch)} tickers...")
        try:
            data = yf.download(
                tickers=" ".join(batch),
                period=f"{LOOKBACK_DAYS}d",
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="ticker",
            )
        except Exception as e:
            print(f"    batch error: {e}")
            continue

        for sym in batch:
            try:
                if sym not in data.columns.get_level_values(0):
                    continue
                d = data[sym].dropna()
                if len(d) < 20:
                    continue
                last_close = float(d["Close"].iloc[-1])
                if not (PRICE_MIN <= last_close <= PRICE_MAX):
                    continue
                avg_dollar_vol = float((d["Close"] * d["Volume"]).tail(20).mean())
                if avg_dollar_vol < MIN_AVG_DOLLAR_VOL:
                    continue
                rows.append(
                    {
                        "symbol": sym,
                        "last_close": last_close,
                        "avg_dollar_vol_20d": avg_dollar_vol,
                        "n_bars": len(d),
                    }
                )
            except Exception:
                continue
        time.sleep(0.5)
    return pd.DataFrame(rows).sort_values("avg_dollar_vol_20d", ascending=False)


def main() -> None:
    symbols = fetch_nasdaq_symbols()
    df = screen_universe(symbols)
    df.to_csv(OUT_CSV, index=False)
    print(f"\nSaved {len(df)} penny-stock candidates to {OUT_CSV}")
    print(df.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
