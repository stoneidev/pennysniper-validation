"""
Position tracking CLI.

Records every buy/sell so you can compare paper-trading or real trades against
the system's signals. Single JSON source of truth: data/positions.json.

Commands:
  buy SYMBOL  --price X  --shares N  [--date YYYY-MM-DD] [--note "..."]
  sell SYMBOL --price X  --reason {tp_hit|time_exit|stop_loss|manual}
                         [--date YYYY-MM-DD] [--note "..."]
  status               # current open positions + cumulative summary
  list  [--all]        # list closed positions (or all)
  cancel SYMBOL        # remove a buy that was never executed (open only)
  edit ID FIELD VALUE  # fix typos (e.g., edit 20260602-NTCL buy_price 1.05)

If a SYMBOL has multiple open positions, use the position ID instead.
ID format: YYYYMMDD-SYMBOL (or YYYYMMDD-SYMBOL-N if duplicate same day).

After every state-changing command, the positions HTML report is regenerated.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
POS_FILE = REPO / "data" / "positions.json"
CONFIG = REPO / "config" / "current_rule.json"
CACHE = REPO / "data" / "daily_cache"


def load() -> dict:
    if not POS_FILE.exists():
        return {"positions": []}
    with open(POS_FILE) as f:
        return json.load(f)


def save(data: dict):
    POS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(POS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def make_id(symbol: str, buy_date: str, existing_ids: list) -> str:
    base = f"{buy_date.replace('-', '')}-{symbol}"
    if base not in existing_ids:
        return base
    n = 2
    while f"{base}-{n}" in existing_ids:
        n += 1
    return f"{base}-{n}"


def get_open_position(data: dict, symbol: str):
    """Return the (single) open position for a symbol, or error if 0 or >1."""
    opens = [p for p in data["positions"]
             if p["symbol"].upper() == symbol.upper() and p.get("sell_date") is None]
    if not opens:
        return None, "no_open"
    if len(opens) > 1:
        return None, "multiple"
    return opens[0], "ok"


def latest_close(symbol: str):
    csv = CACHE / f"{symbol}.csv"
    if not csv.exists():
        return None, None
    df = pd.read_csv(csv, parse_dates=["Date"]).sort_values("Date")
    if len(df) == 0:
        return None, None
    last = df.iloc[-1]
    return float(last["Close"]), str(last["Date"].date())


def cmd_buy(args):
    data = load()
    sym = args.symbol.upper()
    buy_date = args.date or pd.Timestamp.now().strftime("%Y-%m-%d")
    existing_ids = [p["id"] for p in data["positions"]]
    pid = make_id(sym, buy_date, existing_ids)

    # Pull active rule for context
    rule = None
    tp_target = None
    max_hold_until = None
    rule_str = None
    if CONFIG.exists():
        rule = json.load(open(CONFIG))
        tp_target = round(args.price * rule["tp_ratio"], 4)
        # Approximate max hold (calendar days = trading days * 7/5 + buffer)
        cal_days = int(rule["hold_d"] * 7 / 5) + 3
        max_hold_until = (pd.Timestamp(buy_date) + pd.Timedelta(days=cal_days)).strftime("%Y-%m-%d")
        rule_str = (f"{rule['cons_d']}d/${rule['entry_lo']:.2f}-${rule['entry_hi']:.2f}"
                    f"/+{(rule['tp_ratio']-1)*100:.0f}%/{rule['hold_d']}d")

    pos = {
        "id": pid,
        "symbol": sym,
        "buy_date": buy_date,
        "buy_price": float(args.price),
        "shares": int(args.shares),
        "cost_krw": int(args.price * args.shares * (args.fx or 1400)),
        "rule_used": rule_str,
        "tp_target": tp_target,
        "max_hold_until": max_hold_until,
        "notes": args.note or "",
        "sell_date": None,
        "sell_price": None,
        "exit_reason": None,
        "realized_pnl_pct": None,
    }
    data["positions"].append(pos)
    save(data)
    print(f"BUY recorded: {pid}")
    print(f"  {sym} × {args.shares} @ ${args.price:.4f} on {buy_date}")
    if tp_target:
        print(f"  TP target: ${tp_target:.4f}  Max hold until: {max_hold_until}")
        print(f"  Rule used: {rule_str}")


def cmd_sell(args):
    data = load()
    sym = args.symbol.upper()
    pos, status = get_open_position(data, sym)
    if status == "no_open":
        print(f"ERROR: no open position for {sym}", file=sys.stderr)
        sys.exit(1)
    if status == "multiple":
        print(f"ERROR: multiple open positions for {sym}. Use position ID via edit/cancel.", file=sys.stderr)
        sys.exit(1)

    sell_date = args.date or pd.Timestamp.now().strftime("%Y-%m-%d")
    pos["sell_date"] = sell_date
    pos["sell_price"] = float(args.price)
    pos["exit_reason"] = args.reason
    pos["realized_pnl_pct"] = float(args.price) / pos["buy_price"] - 1.0
    pos["realized_pnl_krw"] = int(pos["shares"] * (args.price - pos["buy_price"]) * (args.fx or 1400))
    if args.note:
        pos["notes"] = (pos.get("notes", "") + " | " + args.note).strip(" |")

    save(data)
    print(f"SELL recorded: {pos['id']}")
    print(f"  {sym} × {pos['shares']} @ ${args.price:.4f} on {sell_date}")
    print(f"  Bought ${pos['buy_price']:.4f} → Sold ${args.price:.4f}")
    print(f"  P&L: {pos['realized_pnl_pct']*100:+.2f}%  ({pos['realized_pnl_krw']:+,d} KRW est.)")
    print(f"  Reason: {args.reason}")


def cmd_status(args):
    data = load()
    open_pos = [p for p in data["positions"] if p.get("sell_date") is None]
    closed_pos = [p for p in data["positions"] if p.get("sell_date") is not None]

    print(f"\n=== OPEN POSITIONS ({len(open_pos)}) ===\n")
    if not open_pos:
        print("  (none)")
    else:
        print(f"  {'ID':<22} {'SYM':<6} {'BUY DATE':<11} {'BUY':>8} {'SHRS':>6} "
              f"{'CURRENT':>9} {'PNL%':>7} {'TP$':>8} {'STATUS':<14}")
        for p in sorted(open_pos, key=lambda x: x["buy_date"]):
            cur, cur_date = latest_close(p["symbol"])
            if cur:
                pnl = (cur / p["buy_price"] - 1) * 100
                cur_s = f"${cur:.2f}"
                pnl_s = f"{pnl:+.1f}%"
            else:
                cur_s = "—"
                pnl_s = "—"
            tp_s = f"${p['tp_target']:.2f}" if p.get("tp_target") else "—"
            today = pd.Timestamp.now().normalize()
            mh = pd.Timestamp(p["max_hold_until"]) if p.get("max_hold_until") else None
            if mh and today > mh:
                stat = "EXPIRED"
            elif p.get("tp_target") and cur and cur >= p["tp_target"]:
                stat = "TP REACHED"
            else:
                days_held = (today - pd.Timestamp(p["buy_date"])).days
                stat = f"holding {days_held}d"
            print(f"  {p['id']:<22} {p['symbol']:<6} {p['buy_date']:<11} "
                  f"${p['buy_price']:>7.2f} {p['shares']:>6} {cur_s:>9} "
                  f"{pnl_s:>7} {tp_s:>8} {stat:<14}")

    print(f"\n=== CLOSED ({len(closed_pos)}) — last 10 ===\n")
    if not closed_pos:
        print("  (none)")
    else:
        recent = sorted(closed_pos, key=lambda x: x["sell_date"], reverse=True)[:10]
        print(f"  {'ID':<22} {'SYM':<6} {'BUY':>8} {'SELL':>8} {'PNL%':>7} {'REASON':<12}")
        for p in recent:
            print(f"  {p['id']:<22} {p['symbol']:<6} ${p['buy_price']:>7.2f} "
                  f"${p['sell_price']:>7.2f} {p['realized_pnl_pct']*100:>+6.1f}% "
                  f"{p['exit_reason'] or '—':<12}")

    # Cumulative stats
    if closed_pos:
        rets = [p["realized_pnl_pct"] for p in closed_pos]
        wr = sum(1 for r in rets if r > 0) / len(rets)
        avg = sum(rets) / len(rets)
        krw = sum(p.get("realized_pnl_krw", 0) for p in closed_pos)
        print(f"\n=== CUMULATIVE (closed only) ===")
        print(f"  Trades:    {len(closed_pos)}")
        print(f"  Win rate:  {wr*100:.1f}%")
        print(f"  Mean P&L:  {avg*100:+.2f}%")
        print(f"  Total KRW: {krw:+,d}")


def cmd_list(args):
    data = load()
    rows = data["positions"]
    if not args.all:
        rows = [p for p in rows if p.get("sell_date") is not None]
    rows = sorted(rows, key=lambda x: x.get("sell_date") or x["buy_date"], reverse=True)
    print(f"\n{len(rows)} positions{'(all)' if args.all else ' (closed)'}:\n")
    for p in rows:
        if p.get("sell_date"):
            print(f"  {p['id']:<22}  {p['symbol']:<5}  "
                  f"${p['buy_price']:.2f} → ${p['sell_price']:.2f}  "
                  f"{p['realized_pnl_pct']*100:+.1f}%  ({p['exit_reason']})")
        else:
            print(f"  {p['id']:<22}  {p['symbol']:<5}  ${p['buy_price']:.2f}  OPEN")


def cmd_cancel(args):
    data = load()
    target = args.symbol.upper()
    before = len(data["positions"])
    data["positions"] = [p for p in data["positions"]
                         if not (p["symbol"].upper() == target and p.get("sell_date") is None)]
    removed = before - len(data["positions"])
    save(data)
    print(f"Cancelled {removed} open position(s) for {target}")


def cmd_edit(args):
    data = load()
    target = None
    for p in data["positions"]:
        if p["id"] == args.id:
            target = p
            break
    if target is None:
        print(f"ERROR: id {args.id} not found")
        sys.exit(1)
    field = args.field
    val = args.value
    # Type coercion
    if field in ("buy_price", "sell_price", "tp_target", "realized_pnl_pct"):
        val = float(val)
    elif field in ("shares", "cost_krw", "realized_pnl_krw"):
        val = int(val)
    target[field] = val
    save(data)
    print(f"Updated {args.id}: {field} = {val}")


def main():
    p = argparse.ArgumentParser(description="Position tracker for PennySniper")
    sub = p.add_subparsers(dest="command", required=True)

    pb = sub.add_parser("buy", help="Record a buy")
    pb.add_argument("symbol")
    pb.add_argument("--price", type=float, required=True)
    pb.add_argument("--shares", type=int, required=True)
    pb.add_argument("--date", help="YYYY-MM-DD (default: today)")
    pb.add_argument("--fx", type=float, help="USD/KRW exchange rate (default 1400)")
    pb.add_argument("--note", help="optional note")

    ps = sub.add_parser("sell", help="Record a sell")
    ps.add_argument("symbol")
    ps.add_argument("--price", type=float, required=True)
    ps.add_argument("--reason", choices=["tp_hit", "time_exit", "stop_loss", "manual"], required=True)
    ps.add_argument("--date", help="YYYY-MM-DD (default: today)")
    ps.add_argument("--fx", type=float)
    ps.add_argument("--note")

    sub.add_parser("status", help="Show current state")
    pl = sub.add_parser("list", help="List positions")
    pl.add_argument("--all", action="store_true")

    pc = sub.add_parser("cancel", help="Remove an open position")
    pc.add_argument("symbol")

    pe = sub.add_parser("edit", help="Edit a single field of a position")
    pe.add_argument("id")
    pe.add_argument("field")
    pe.add_argument("value")

    args = p.parse_args()
    funcs = {
        "buy": cmd_buy, "sell": cmd_sell, "status": cmd_status,
        "list": cmd_list, "cancel": cmd_cancel, "edit": cmd_edit,
    }
    funcs[args.command](args)

    if args.command in {"buy", "sell", "cancel", "edit"}:
        subprocess.run(
            [sys.executable, str(Path(__file__).with_name("positions_report.py"))],
            check=False,
        )


if __name__ == "__main__":
    main()
