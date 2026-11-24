# BALE DOWNLOAD HUB

برنامهٔ دسکتاپ ویندوز: **لینک ← دانلود ← بررسی ← انتشار در کانال بله ← حذف کامل فایل‌های موقت**.
*A Windows desktop app: link → download → verify → publish to a Bale channel → delete every temporary file.*

نسخه / Version: **1.0.0** · پایتون ≥ 3.11 · PySide6 · SQLite

> **صادقانه بگوییم / Honest status** – همهٔ بخش‌ها پیاده‌سازی و با **۱۸۳ تست خودکار** (همه موفق) آزموده شده‌اند، اما: ارسال واقعی به بله با توکن شما، اجرا روی ویندوز و ساخت `EXE` در محیط توسعه ممکن نبود. جزئیات در [`TEST_REPORT.md`](TEST_REPORT.md) و بخش «محدودیت‌ها» پایین.

## شروع سریع (۵ دقیقه)

1. Python 3.11+ را نصب کنید (`python.org`، گزینهٔ *Add to PATH*).
2. روی **`run.bat`** دوبار کلیک کنید (بار اول وابستگی‌ها را نصب می‌کند). یا `run.ps1`.
3. راهنمای راه‌اندازی باز می‌شود: توکن ربات ← کانال ← بررسی دسترسی ← مدیران ← پوشهٔ موقت ← محدودیت‌ها ← پاک‌سازی ← فعال‌سازی.
4. در بخش **دانلودها** لینک اضافه کنید، یا لینک را به ربات بله بفرستید.

راهنمای کامل فارسی: [`BALE_DOWNLOAD_HUB_GUIDE_FA.pdf`](BALE_DOWNLOAD_HUB_GUIDE_FA.pdf) و [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md). راهنمای داخل برنامه: «مرکز راهنما» (فارسی/انگلیسی) + دکمهٔ ؟ کنار هر ورودی.

## ویژگی‌ها

| حوزه | چه چیزی واقعاً پیاده‌سازی شده |
|---|---|
| رابط | PySide6؛ داشبورد با داده‌های واقعی و ۶ نمودار؛ ۷ تم + رنگ Accent؛ فارسی (RTL، فونت Vazirmatn همراه برنامه)، انگلیسی، چینی؛ تغییر زبان در هر لحظه؛ Toast؛ ۱۰ مرحله Setup Wizard؛ مرکز راهنما با جست‌وجو و FAQ |
| ورود لینک | دستی، گروهی، Paste از کلیپ‌بورد، فایل TXT/CSV، ربات بله (چند لینک در پیام)، **API داخلی اختیاری** (فقط 127.0.0.1 + کلید) |
| تحلیل | نام، حجم، MIME، نوع، قابلیت ادامه، محدودیت حجم/نوع؛ تأیید کاربر پیش از دانلود |
| دانلود | HTTP/HTTPS، Streaming، قطعه‌ای چنداتصالی و Resume (فقط اگر سرور Range بدهد)، محدودیت پهنای باند، Retry نمایی، yt-dlp برای صفحات رسانهٔ عمومی |
| صف | اولویت، توقف/ادامه/لغو، هم‌زمانی، زمان‌بندی (توسط برنامه)، ذخیره و بازیابی پس از Crash، جلوگیری از تکرار |
| رسانه | تشخیص نوع با امضای واقعی، متادیتا (Pillow/ffprobe)، Thumbnail (پیش‌نمایش)، تغییر نام، تبدیل تصویر (اختیاری) |
| انتشار | عکس/ویدئو/صوت/سند با روش مناسب و Fallback، قالب کپشن برای هر نوع، چندکانالی با نتیجهٔ جدا، مسیریابی نوع→کانال، ضد تکرار SHA-256، پیش‌نمایش و تأیید |
| ربات | `/start /help /status /queue /cancel /pause /resume /confirm /reject` + دستورهای مدیریت کاربر؛ RBAC چهارنقشی؛ محدودیت درخواست و سهمیه |
| امنیت | SSRF (DNS + همهٔ Redirectها)، امضای فایل، Zip Slip/بمب فشرده، بدون `shell=True`، توکن در Credential Manager، ماسک در لاگ/گزارش/خروجی |
| **پاک‌سازی** | پوشهٔ جداگانه برای هر کار؛ حذف کامل پس از موفقیت/شکست/لغو؛ جارو کردن فایل‌های رهاشده؛ گزارش حجم آزادشده؛ حالت حریم خصوصی |
| دیتابیس | SQLite + SQLAlchemy + Alembic؛ بدون BLOB؛ بررسی سلامت، Vacuum، نگهداری+آرشیو، Backup/Restore رمزگذاری‌شده |
| گزارش | ۶ تب، فیلتر متن/تاریخ/وضعیت/کانال، خروجی CSV/JSON، چاپ |

## ساختار پروژه

```
app/            application.py (ترکیب سرویس‌ها) · main.py
  core/         config · logger(ماسک) · events · exceptions · paths · constants
  security/     url_safety(SSRF) · secret_store · access_control · scanner
  integrations/bale/   client · adapter(BaleAPIAdapter) · polling · publisher
  downloader/   engine · direct · media_extractor(yt-dlp) · validators · queue · retries
  media/        analyzer · processor · thumbnails
  database/     models · repository · manager · migrations(Alembic)
  cleanup/      manager · scheduler
  services/     download · publishing · bot · bot_runtime · notification · backup · report · update · local_api · caption
  ui/           main_window · wizard · theme · pages/ · components/
  localization/ fa.json en.json zh.json      resources/ fonts · help
tests/          unit · integration · security · ui        scripts/ build · generate_pdf · …
docs/           ARCHITECTURE · API · USER_GUIDE · SECURITY · DEVELOPER_GUIDE
```

## اجرا، تست، ساخت

```bat
run.bat                    :: اجرا   (run.bat console برای دیدن خطاها)
.venv\Scripts\python -m pytest         :: تست‌ها (pip install -r requirements-dev.txt)
build.bat                  :: ساخت EXE → dist\BALE_DOWNLOAD_HUB\BALE_DOWNLOAD_HUB.exe
BALE_DOWNLOAD_HUB.exe --selftest       :: تست سریع بستهٔ ساخته‌شده
```

## محدودیت‌ها (صادقانه)

* **API رسمی بله** (docs.bale.ai): آپلود ربات ≤ **۵۰ MB** (عکس ۱۰ MB). *ارسال زمان‌بندی‌شده، خواندن مجوزهای ربات در کانال، پاسخ به دکمه‌های شیشه‌ای و Thumbnail سفارشی* در مستندات نیست و ادعا نشده: زمان‌بندی را برنامه انجام می‌دهد؛ دسترسی کانال با پیام آزمایشیِ حذف‌شونده سنجیده می‌شود؛ تأیید در ربات با دستور متنی است؛ فایل بزرگ را می‌توان به قطعات ۴۹ MB تقسیم کرد.
* دریافت پیام ربات با `getUpdates` و فاصلهٔ زمانی است (پارامتر long-poll مستند نیست).
* حذف فایل = حذف از سیستم‌فایل، **نه** پاک‌سازی امن/غیرقابل‌بازیابی.
* SSRF: DNS Rebinding بین بررسی و اتصال کاملاً بسته نیست؛ yt-dlp درخواست‌های شبکهٔ خودش را انجام می‌دهد (فقط آدرس ورودی بررسی می‌شود). جزئیات: `docs/SECURITY.md`.
* DRM، پخش زنده و محتوای نیازمند ورود/پرداخت پشتیبانی **نمی‌شود** و دور زده **نمی‌شود**.
* مقالات راهنمای داخلی برای چینی انگلیسی نمایش داده می‌شوند (متن رابط چینی کامل است).
* `BALE_DOWNLOAD_HUB.exe` در این بسته ساخته نشده (ساخت فقط روی ویندوز؛ `build.bat` را اجرا کنید).

## مجوزها
فونت Vazirmatn (OFL) در `app/resources/fonts/OFL.txt`. وابستگی‌ها مجوز خودشان را دارند.
