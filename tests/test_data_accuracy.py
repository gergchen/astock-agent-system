"""Data accuracy verification tests.

Verifies DataSourceManager fallback chain data consistency:
  K-line: mootdx TCP -> Sina HTTP (akshare)
  Real-time quotes: mootdx TCP
  Valuation: Tencent Finance HTTP

Usage:
    python -m tests.test_data_accuracy
"""

import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import pandas as pd

from astock_data.market.mootdx_quote import get_kline, get_quotes, batch_kline
from astock_data.market.tencent_finance import get_valuation
from astock_data.exceptions import DataUnavailableError


# Test targets
TEST_CODES = ["600519", "000858", "002230"]
COLS_KLINE = {"open", "high", "low", "close", "vol"}
COLS_QUOTE = {"price", "open", "high", "low", "vol", "amount"}

# Test counters
pass_count = 0
fail_count = 0
total_checks = 0


def check(name: str, ok: bool, detail: str = ""):
    global pass_count, fail_count, total_checks
    total_checks += 1
    status = "PASS" if ok else "FAIL"
    if ok:
        pass_count += 1
    else:
        fail_count += 1
    print(f"  [{status}] {name}")
    if detail:
        # Filter out non-GBK characters
        safe = detail.encode("gbk", errors="replace").decode("gbk")
        print(f"         {safe}")
    return ok


def print_header(title: str):
    safe = title.encode("gbk", errors="replace").decode("gbk")
    print(f"\n{'='*60}")
    print(f"  {safe}")
    print(f"{'='*60}")


# --- Test 1: K-line data integrity ---

def test_kline_integrity():
    print_header("1. K-line data integrity (mootdx -> Sina fallback)")

    for code in TEST_CODES:
        print(f"\n  --- {code} ---")
        try:
            df = get_kline(code, category="day", offset=120)
        except Exception as e:
            check(f"{code} get_kline raised exception", False, str(e))
            continue

        if df is None or df.empty:
            check(f"{code} returned empty data", False)
            continue

        check(f"{code} row count >= 60", len(df) >= 60, f"actual: {len(df)}")

        # Column completeness
        missing = COLS_KLINE - set(df.columns)
        check(f"{code} all columns present", not missing,
              f"missing: {missing}" if missing else "")

        # Null check
        nulls = df[list(COLS_KLINE)].isnull().sum().sum()
        null_ratio = nulls / (len(df) * len(COLS_KLINE))
        check(f"{code} null ratio < 5%", null_ratio < 0.05,
              f"null ratio: {null_ratio:.2%}")

        # Positive prices
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                valid = (df[col].dropna() > 0).all()
                check(f"{code} {col} > 0", valid)

        # Volume non-negative
        if "vol" in df.columns:
            valid_vol = (df["vol"].dropna() >= 0).all()
            check(f"{code} vol >= 0", valid_vol)

        # High/Low logic
        if all(c in df.columns for c in ["open", "high", "low", "close"]):
            valid_high = (df["high"] >= df[["open", "close"]].max(axis=1) - 0.01).all()
            valid_low = (df["low"] <= df[["open", "close"]].min(axis=1) + 0.01).all()
            check(f"{code} high >= max(open,close)", valid_high)
            check(f"{code} low <= min(open,close)", valid_low)

        # Chronological order
        if "date" in df.columns or "datetime" in df.columns:
            tcol = "date" if "date" in df.columns else "datetime"
            try:
                is_sorted = df[tcol].is_monotonic_increasing
                check(f"{code} chronological order", is_sorted)
            except Exception:
                pass

        # Moutai closing price sanity (100-3000)
        if code == "600519" and "close" in df.columns:
            close = df["close"].dropna()
            recent_close = close.iloc[-1]
            check(f"{code} latest close reasonable", 100 < recent_close < 3000,
                  f"latest close: {recent_close:.2f}")


# --- Test 2: DataSourceManager fallback chain ---

def test_fallback_chain():
    print_header("2. DataSourceManager fallback chain")

    from astock_data.market.mootdx_quote import _get_kline_manager
    mgr = _get_kline_manager()
    health = mgr.get_health()
    print(f"\n  Source health:")
    for name, h in health.items():
        print(f"    {name}: alive={h['alive']}, fail_count={h['fail_count']}")

    heartbeat = mgr.check_heartbeat()
    print(f"\n  Heartbeat results:")
    for name, alive in heartbeat.items():
        status = "REACHABLE" if alive else "UNREACHABLE"
        print(f"    {name}: {status}")

    # At least one source must be alive
    any_alive = any(h["alive"] for h in health.values())
    check("At least one data source available", any_alive,
          f"health: {health}")


# --- Test 3: Batch K-line ---

def test_batch_kline():
    print_header("3. Batch K-line fetch")

    start = time.time()
    results = batch_kline(TEST_CODES, category="day", offset=60, max_workers=3)
    elapsed = time.time() - start

    check(f"Batch {len(TEST_CODES)} stocks completed", len(results) > 0,
          f"success: {len(results)}/{len(TEST_CODES)}, elapsed: {elapsed:.1f}s")

    for code in TEST_CODES:
        df = results.get(code)
        if df is not None and not df.empty:
            check(f"{code} batch rows >= 30", len(df) >= 30, f"actual: {len(df)}")


# --- Test 4: Real-time quotes ---

def test_quotes():
    print_header("4. Real-time quotes (mootdx)")

    try:
        df = get_quotes(TEST_CODES)
    except Exception as e:
        check("get_quotes() (mootdx unreachable, no fallback)", False,
              f"expected: {e}")
        return

    if df is None or df.empty:
        check("get_quotes() returned empty", False)
        return

    check(f"Quote rows == {len(TEST_CODES)}", len(df) == len(TEST_CODES),
          f"actual rows: {len(df)}")

    # Column completeness
    quote_cols = {"price", "open", "high", "low", "vol", "amount", "last_close"}
    missing = quote_cols - set(df.columns)
    check("All quote columns present", not missing,
          f"missing: {missing}" if missing else "")

    # Positive prices
    for col in ["price", "open", "high", "low", "last_close"]:
        if col in df.columns:
            valid = (df[col].dropna() > 0).all()
            check(f"Quote {col} > 0", valid)


# --- Test 5: Tencent Finance valuation ---

def test_valuation():
    print_header("5. Tencent Finance valuation")

    try:
        val = get_valuation(TEST_CODES)
    except Exception as e:
        check("get_valuation()", False, f"exception: {e}")
        return

    if not val:
        check("Valuation data empty", False)
        return

    check(f"Valuation codes == {len(TEST_CODES)}", len(val) == len(TEST_CODES),
          f"actual: {len(val)}")

    for code in TEST_CODES:
        item = val.get(code, {})
        if not item:
            check(f"{code} valuation data present", False)
            continue

        check(f"{code} price > 0", item.get("price", 0) > 0,
              f"price: {item.get('price', 0)}")
        check(f"{code} PE_TTM > 0", item.get("pe_ttm", 0) > 0,
              f"PE_TTM: {item.get('pe_ttm', 0)}")
        check(f"{code} PB > 0", item.get("pb", 0) > 0,
              f"PB: {item.get('pb', 0)}")
        check(f"{code} market_cap > 0", item.get("mcap_yi", 0) > 0,
              f"market_cap: {item.get('mcap_yi', 0)} billion")

    # Moutai PE sanity (usually 10-60)
    moutai = val.get("600519", {})
    if moutai.get("pe_ttm", 0) > 0:
        pe = moutai["pe_ttm"]
        check("Moutai PE_TTM reasonable", 5 < pe < 100, f"PE_TTM: {pe:.2f}")


# --- Summary ---

def summary():
    print(f"\n{'='*60}")
    if fail_count == 0:
        title = "ALL TESTS PASSED"
    else:
        title = f"SOME TESTS FAILED ({fail_count})"
    print(f"  Result: {title}")
    print(f"  Passed: {pass_count}/{total_checks} ({pass_count/total_checks*100:.1f}%)")
    print(f"{'='*60}")
    return fail_count == 0


if __name__ == "__main__":
    print("=" * 60)
    print(f"  Data Accuracy Verification Test")
    print(f"  Targets: {', '.join(TEST_CODES)}")
    print(f"  Time: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    test_kline_integrity()
    test_fallback_chain()
    test_batch_kline()
    test_quotes()
    test_valuation()

    ok = summary()
    sys.exit(0 if ok else 1)
