"""Builds app/localization/{fa,en,zh}.json from scripts/i18n/*. Fails if a key lacks a translation."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from i18n import ui_strings, page_strings, field_strings  # noqa: E402,F401

OUT = Path(__file__).resolve().parents[1] / "app" / "localization"
D = ui_strings.D
bad = [k for k, v in D.items() if len(v) != 3 or (not v[0] and not k.endswith((".h",)))]
if bad:
    sys.exit(f"incomplete: {bad[:10]}")
import re
for k, v in D.items():
    ph = [set(re.findall(r"\{(\w+)\}", s)) for s in v]
    if not (ph[0] == ph[1] == ph[2]) and not k.startswith("field."):
        sys.exit(f"placeholder mismatch in {k}: {ph}")
for i, lang in enumerate(("en", "fa", "zh")):
    (OUT / f"{lang}.json").write_text(json.dumps({k: v[i] for k, v in sorted(D.items())}, ensure_ascii=False, indent=1), encoding="utf-8")
print("keys:", len(D))
