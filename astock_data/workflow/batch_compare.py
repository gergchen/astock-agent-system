"""Workflow B: Batch stock comparison — side-by-side valuation ranking."""

from .valuation import full_valuation


def batch_compare(codes: list[str]) -> list[dict]:
    """Compare multiple stocks side-by-side on key valuation metrics.

    Args:
        codes: List of 6-digit stock codes.

    Returns:
        List of valuation dicts sorted by PEG (lower = better value).
    """
    results = []
    for code in codes:
        try:
            r = full_valuation(code)
            results.append(r)
        except Exception as e:
            results.append({
                "code": str(code).zfill(6),
                "name": "ERROR",
                "error": str(e),
            })

    # Sort by PEG (cheaper first), with None/Inf at end
    def _sort_key(r):
        peg = r.get("peg")
        if peg is None or peg == float("inf"):
            return (1, float("inf"))
        return (0, peg)

    results.sort(key=_sort_key)
    return results
