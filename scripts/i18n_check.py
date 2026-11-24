"""Lists every translation key referenced by the code. Usage: python scripts/i18n_check.py [--missing]"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAT = re.compile(r"""(?:\bt|\btr_|\btr|self\.t|ctx\.tr|self\.tr_|tr\.tr_in\(\s*[^,]+,\s*|\.t)\(\s*f?["']([A-Za-z0-9_.{}\[\]' ]+)["']""")
FIELD = re.compile(r"""(?:FieldRow\(\s*[\w.]+,\s*|\bF\(\s*"[\w.]+",\s*)"(\w+)"\s*,\s*"(\w+)\"""")


def used_keys() -> set[str]:
    keys: set[str] = set()
    for f in (ROOT / "app").rglob("*.py"):
        src = f.read_text(encoding="utf-8")
        for m in PAT.finditer(src):
            k = m.group(1)
            if "{" in k:
                continue
            keys.add(k)
        for m in FIELD.finditer(src):
            for s in "tdhe":
                keys.add(f"field.{m.group(1)}.{s}")
    return keys


if __name__ == "__main__":
    ks = sorted(used_keys())
    if "--missing" in sys.argv:
        for lang in ("en", "fa", "zh"):
            have = set(json.loads((ROOT / "app/localization" / f"{lang}.json").read_text(encoding="utf-8")))
            miss = [k for k in ks if k not in have]
            print(lang, "missing:", len(miss))
            if lang == "en":
                print("\n".join(miss))
    else:
        print("\n".join(ks))
