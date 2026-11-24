import json
import re
from pathlib import Path

import pytest

from app.localization import Translator
from app.core.config import THEMES

ROOT = Path(__file__).resolve().parents[2]
L = {l: json.loads((ROOT / "app/localization" / f"{l}.json").read_text(encoding="utf-8")) for l in ("fa", "en", "zh")}


def test_all_languages_have_identical_key_sets():
    assert set(L["fa"]) == set(L["en"]) == set(L["zh"])
    assert len(L["en"]) > 600


def test_no_empty_translations_except_optional_howto():
    for lang, d in L.items():
        empty = [k for k, v in d.items() if not v.strip() and not k.endswith(".h")]
        assert not empty, (lang, empty[:5])


def test_placeholders_consistent_across_languages():
    for k in L["en"]:
        if k.startswith("field."):
            continue
        sets = [set(re.findall(r"\{(\w+)\}", L[l][k])) for l in L]
        assert sets[0] == sets[1] == sets[2], k


def test_scripts_are_what_they_claim():
    fa_chars = re.compile(r"[\u0600-\u06FF]")
    zh_chars = re.compile(r"[\u4e00-\u9fff]")
    for k in ("nav.dashboard", "dash.title", "dl.title", "wiz.s.token", "bot.start"):
        assert fa_chars.search(L["fa"][k]) and zh_chars.search(L["zh"][k]) and not fa_chars.search(L["en"][k])


def test_every_static_key_used_in_code_exists():
    import subprocess, sys
    keys = subprocess.run([sys.executable, str(ROOT / "scripts/i18n_check.py")], capture_output=True, text=True, cwd=ROOT).stdout.split()
    missing = [k for k in keys if k not in L["en"] and not k.endswith((".", "_"))]
    assert not missing, missing


def test_every_error_code_in_source_has_a_message():
    codes = set()
    for f in (ROOT / "app").rglob("*.py"):
        if "localization" in str(f):
            continue
        codes |= set(re.findall(r'code="([a-z_0-9]+)"', f.read_text(encoding="utf-8")))
    codes |= {"download_failed", "disk_space_low", "file_too_large", "rate_limited", "access_denied", "publish_failed",
              "bale_auth_error", "bale_network_error", "not_downloadable", "url_blocked"}
    dynamic_ok = {"error", "config_invalid", "security_blocked", "bale_api_error", "cancelled", "paused", "backup_failed",
                  "not_authorized", "insufficient_role", "backup_integrity", "backup_password_required", "backup_bad_password",
                  "backup_invalid", "url_dns"}
    missing = sorted(c for c in codes if f"error.{c}" not in L["en"] and c not in dynamic_ok and not c.startswith("http_"))
    assert not missing, missing


def test_every_theme_and_status_and_role_is_translated():
    for l in L:
        for t in THEMES:
            assert f"theme.{t}" in L[l]
        for s in ("waiting", "validating", "downloading", "paused", "processing", "uploading", "completed", "failed", "cancelled", "cleanup"):
            assert f"status.{s}" in L[l]
        for r in ("SUPER_ADMIN", "ADMIN", "OPERATOR", "READ_ONLY"):
            assert f"role.{r}" in L[l]


def test_every_input_has_title_description_howto_and_example():
    ids = {k.split(".")[1] for k in L["en"] if k.startswith("field.")}
    assert len(ids) >= 55
    for i in ids:
        for s in "tde":
            assert L["en"][f"field.{i}.{s}"].strip(), (i, s)
        for lang in L:
            assert L[lang][f"field.{i}.t"].strip() and L[lang][f"field.{i}.d"].strip()


def test_translator_fallback_and_rtl():
    t = Translator("fa")
    assert t.is_rtl and t("nav.dashboard") == "داشبورد"
    t.set_language("en")
    assert not t.is_rtl and t("nav.dashboard") == "Dashboard"
    assert t("no.such.key") == "no.such.key" and "no.such.key" in t.missing
    assert t("dl.confirm_cancel", n=3) == "Cancel 3 job(s)? Their temporary files will be deleted."
    assert t.tr_in("zh", "common.ok") == "确定" and t.language == "en"
    t.set_language("xx")
    assert t.language == "en"


def test_help_center_content():
    fa = json.loads((ROOT / "app/resources/help/fa.json").read_text(encoding="utf-8"))
    en = json.loads((ROOT / "app/resources/help/en.json").read_text(encoding="utf-8"))
    need = {"intro", "create_bot", "token", "create_channel", "add_bot_admin", "channel_id", "admin_id", "connection", "test_connection",
            "bot_start_stop", "download", "publish", "queue", "errors", "cleanup", "database", "backup", "token_security", "install"}
    assert need <= {a["id"] for a in fa["articles"]} and need <= {a["id"] for a in en["articles"]}
    assert len(fa["faq"]) >= 8 and len(en["faq"]) == len(fa["faq"])
