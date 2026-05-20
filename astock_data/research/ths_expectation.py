"""同花顺 Institutional Consensus EPS via akshare.

akshare.stock_profit_forecast_ths() wraps THS earnings forecasts.
"""

import akshare as ak

from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import AKShareError


@retry()
@rate_limit("akshare")
def get_consensus_eps(code: str, indicator: str = "预测年报每股收益") -> dict:
    """Fetch institutional consensus EPS forecasts.

    Args:
        code: 6-digit stock code.
        indicator: "预测年报每股收益" (most stable), "预测年报净利润",
                   "预测详细指标", "业绩预测详表-机构".

    Returns:
        Dict with keys: years (list of year strings),
        forecasts (list of {year, analyst_count, min, mean, max, industry_avg}).
    """
    try:
        df = ak.stock_profit_forecast_ths(symbol=str(code).zfill(6), indicator=indicator)
    except Exception as e:
        raise AKShareError(f"一致预期 fetch failed for {code}: {e}") from e

    if df is None or df.empty:
        return {"years": [], "forecasts": [], "covered": False}

    forecasts = []
    years = sorted(df["年度"].unique())
    for _, row in df.iterrows():
        forecasts.append({
            "year": str(row["年度"]),
            "analyst_count": int(row.get("预测机构数", 0) or 0),
            "min_eps": float(row.get("最小值", 0) or 0),
            "mean_eps": float(row.get("均值", 0) or 0),
            "max_eps": float(row.get("最大值", 0) or 0),
            "industry_avg": float(row.get("行业平均数", 0) or 0),
        })

    return {
        "years": [str(y) for y in years],
        "forecasts": forecasts,
        "covered": True,
    }
