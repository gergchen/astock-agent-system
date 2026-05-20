"""Output formatters: JSON, table, CSV."""

import json
import csv
import io
from typing import Any


def to_json(data: Any, ensure_ascii: bool = False) -> str:
    """Pretty-print data as JSON string."""
    return json.dumps(data, indent=2, ensure_ascii=ensure_ascii, default=str)


def to_table(data: list[dict]) -> str:
    """Render list-of-dicts as an aligned plain-text table."""
    if not data:
        return "(empty)"
    keys = list(data[0].keys())
    col_widths = {k: len(str(k)) for k in keys}
    rows = []
    for row in data:
        str_row = {k: str(v) if v is not None else "" for k, v in row.items()}
        for k in keys:
            col_widths[k] = max(col_widths[k], len(str_row.get(k, "")))
        rows.append(str_row)

    def _row(values):
        return " | ".join(str(v).ljust(col_widths[k]) for k, v in zip(keys, values))

    lines = [_row(keys), "-+-".join("-" * col_widths[k] for k in keys)]
    for row in rows:
        lines.append(_row([row.get(k, "") for k in keys]))
    return "\n".join(lines)


def to_csv_str(data: list[dict]) -> str:
    """Render list-of-dicts as CSV string."""
    if not data:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)
    return buf.getvalue()


def output(data: Any, fmt: str = "json"):
    """Unified output dispatcher for CLI."""
    if fmt == "json":
        return to_json(data)
    elif fmt == "table":
        if isinstance(data, list):
            return to_table(data)
        return to_json(data)
    elif fmt == "csv":
        if isinstance(data, list):
            return to_csv_str(data)
        return to_json(data)
    else:
        return to_json(data)
