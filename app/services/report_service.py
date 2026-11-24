"""CSV / JSON / printable-HTML exports. Everything is masked first so no secret can reach a report."""
from __future__ import annotations

import csv
import html
import json
from datetime import date, datetime
from pathlib import Path

from app.core.logger import mask_obj


def _plain(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return "" if v is None else v


def prepare(rows: list[dict], columns: list[str] | None = None) -> tuple[list[str], list[dict]]:
    rows = [mask_obj({k: _plain(v) for k, v in r.items()}) for r in rows]
    cols = columns or (list(rows[0].keys()) if rows else [])
    return cols, [{c: r.get(c, "") for c in cols} for r in rows]


def export_csv(rows: list[dict], path: Path, columns: list[str] | None = None) -> Path:
    cols, data = prepare(rows, columns)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:        # BOM so Excel reads Persian correctly
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(data)
    return Path(path)


def export_json(rows: list[dict], path: Path, columns: list[str] | None = None) -> Path:
    _cols, data = prepare(rows, columns)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return Path(path)


def to_html(title: str, rows: list[dict], columns: list[str] | None = None, rtl: bool = False) -> str:
    cols, data = prepare(rows, columns)
    th = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(r[c]))}</td>" for c in cols) + "</tr>" for r in data)
    return (f"<html><head><meta charset='utf-8'><style>body{{font-family:Segoe UI,Vazirmatn,sans-serif;font-size:10pt}}"
            f"table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #888;padding:3px}}"
            f"th{{background:#ddd}}</style></head><body dir='{'rtl' if rtl else 'ltr'}'><h2>{html.escape(title)}</h2>"
            f"<table><tr>{th}</tr>{body}</table></body></html>")
