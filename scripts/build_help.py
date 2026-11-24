"""Generates app/resources/help/{fa,en}.json (Help Center articles + FAQ). Run: python scripts/build_help.py"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "app" / "resources" / "help"
OUT.mkdir(parents=True, exist_ok=True)

EN = {
 "articles": [
  ("intro", "Getting to know the app", "<p><b>BALE DOWNLOAD HUB</b> downloads files from allowed public links, checks them, publishes them to your Bale channel and then <b>deletes every temporary file</b>.</p><ol><li>Create a Bale bot and copy its token.</li><li>Create a channel and make the bot an admin.</li><li>Paste the token and channel in the Setup Wizard.</li><li>Add links (in the app or by messaging the bot).</li></ol><p>Only administrators you define can use the bot.</p>"),
  ("create_bot", "Creating a Bale bot", "<p>Bots are created with Bale's official bot-management bot (<b>@botfather</b> inside Bale). Follow the steps in the official documentation: <a href='https://docs.bale.ai/'>docs.bale.ai</a>.</p><p>You choose a name and a username; BotFather then replies with the bot <b>token</b>.</p>"),
  ("token", "Getting and protecting the token", "<p>The token looks like <code>123456789:ABC-DEF...</code>. Anyone who has it controls your bot.</p><ul><li>Paste it only into the app's token field (it is kept in the Windows Credential Manager, not in the database or in settings files).</li><li>Never post it in chats or screenshots.</li><li>If it leaks, ask BotFather to revoke/regenerate it and enter the new one here.</li></ul><p>The app masks tokens in logs, error messages, reports and exports.</p>"),
  ("create_channel", "Creating a channel", "<p>In Bale: New → Channel. A <b>public</b> channel has a username (e.g. <code>@my_files</code>) which is the easiest ID to use.</p>"),
  ("add_bot_admin", "Making the bot a channel admin", "<p>Open the channel → Administrators → Add admin → choose your bot and allow <b>posting messages</b>. Without this the bot cannot publish and the channel test will fail.</p>"),
  ("channel_id", "Finding the channel ID", "<p>Use <code>@username</code> for public channels. The Bale Bot API also accepts the numeric chat id; after a successful test the app shows the numeric ID it received from Bale.</p><p><i>Limit:</i> the documented API has no call to list a bot's channels, so a private channel without a username needs its numeric ID from another source.</p>"),
  ("admin_id", "Finding a user's numeric ID", "<p>Ask the person to send any message to your bot. If they are not authorised yet, the bot answers with their numeric ID – paste it into <b>Users</b> or into the wizard's admin step.</p>"),
  ("connection", "Connection settings", "<p>Defaults work for most networks. Increase the timeouts on slow connections; set a proxy (<code>http://…</code> or <code>socks5://…</code>) only if Bale is not reachable directly.</p>"),
  ("test_connection", "Testing the connection", "<p>Use <b>Test</b> next to the token (calls <code>getMe</code>) and next to the channel. The channel test sends a short message and deletes it again – this is the only reliable way to verify posting rights because the Bale API has no 'my permissions' call.</p>"),
  ("bot_start_stop", "Starting and stopping the bot", "<p>The bot starts automatically when a token is saved and <b>Bot enabled</b> is on (Settings → Bot). Turn it off to stop receiving messages; downloads started from the desktop keep working.</p>"),
  ("download", "Downloading from a link", "<p>Add links in <b>Downloads → Add links</b>, paste several, or import TXT/CSV. The app analyses each link first (name, size, type) and you confirm. Supported: direct files and pages supported by yt-dlp. <b>Not</b> supported: DRM content, content behind logins/paywalls, private network addresses.</p>"),
  ("publish", "Publishing to the channel", "<p>Images (≤10 MB JPG/PNG) go as photos, MP4 as video, MP3/M4A as audio, everything else as documents. Bale bots can upload at most <b>50 MB</b> per file. Optionally enable <i>split large files</i> to send 49 MB parts. Scheduling is done by the app (the Bale API has no scheduled posts).</p>"),
  ("local_api", "Local link API (optional)", "<p>Settings → Bot → <b>Enable local link API</b>. Other programs on this computer can then POST links:</p><pre>curl -X POST http://127.0.0.1:8765/api/v1/links -H \"Authorization: Bearer YOUR_KEY\" -H \"Content-Type: application/json\" -d \"{\\\"urls\\\":[\\\"https://example.com/a.pdf\\\"]}\"</pre><p>It listens on 127.0.0.1 only, needs the key shown in settings, accepts at most 20 links per request, and is off by default.</p>"),
  ("queue", "Managing the queue", "<p>Pause, resume, cancel, retry, change priority, and set concurrent downloads. The queue is saved and restored after a restart or crash; partial downloads resume when the server supports Range requests.</p>"),
  ("errors", "Common errors", "<ul><li><b>Unauthorized / token rejected</b> – wrong or revoked token.</li><li><b>Forbidden / not a member</b> – bot is not an admin of the channel.</li><li><b>File too large</b> – above your limit or Bale's 50 MB.</li><li><b>URL blocked</b> – private/internal address (SSRF protection).</li><li><b>Disk space low</b> – the queue pauses automatically.</li></ul>"),
  ("cleanup", "Automatic clean-up", "<p>After a successful publish every temporary file of that job (download, processed copy, thumbnail, side files) is deleted; failed or cancelled jobs are cleaned too. Orphans are swept at start-up and on a schedule. <b>Privacy mode</b> also removes the URL and file name from the history.</p><p><i>Honest note:</i> deleting a file is not secure erasure – the operating system may allow recovery with special tools.</p>"),
  ("database", "Managing the database", "<p>The SQLite database holds only job metadata – never file contents. Use Settings → Backup for integrity check, vacuum and retention.</p>"),
  ("backup", "Backups and restore", "<p>Backups can be password-encrypted. Settings export never contains the token. Restoring first saves a safety copy of the current database.</p>"),
  ("token_security", "Token security", "<p>The token is stored in the OS credential vault; if none exists an encrypted file protected by machine/user-derived key is used (stops casual reading, not malware running as you).</p>"),
  ("install", "Installing and updating", "<p>Run <code>run.bat</code> (creates a virtual environment and installs dependencies) or use the EXE built by <code>build.bat</code>. Updates are never installed automatically; the update check is off until you enable it and give a feed URL.</p>"),
 ],
 "faq": [
  ("Does the app keep my downloads?", "No. After publishing (or failing/cancelling) the job's temporary folder is deleted. The database stores metadata only."),
  ("Why is a file over 50 MB rejected?", "Bale bots can upload at most 50 MB per file through the Bot API. Enable 'split large files' for 49 MB parts."),
  ("Can I schedule posts?", "Yes, in the Add-links dialog. The app starts the job at the chosen time because the Bale API has no scheduling."),
  ("Is my token safe?", "It is stored in the Windows Credential Manager and masked everywhere. Never share it."),
  ("Who can use the bot?", "Only users in the Users list. Everyone else gets a short 'not authorised' reply with their numeric ID."),
  ("Why can't I download from a private IP?", "Blocking localhost/private addresses (SSRF) protects your network."),
  ("Why did the channel test post a message?", "It is the only way to verify posting rights; the message is deleted immediately."),
  ("Does it support YouTube etc.?", "Through yt-dlp for public content that is allowed. DRM, logins and paywalls are not supported."),
  ("What happens if the PC crashes?", "On restart unfinished jobs return to the queue and resume if possible; orphan files are cleaned."),
  ("Can I use another language?", "Settings → Appearance: Persian (RTL), English, Chinese – switch any time."),
 ],
}

FA = {
 "articles": [
  ("intro", "آشنایی با برنامه", "<p><b>BALE DOWNLOAD HUB</b> فایل‌ها را از لینک‌های عمومی و مجاز دریافت می‌کند، بررسی می‌کند، در کانال بله منتشر می‌کند و سپس <b>تمام فایل‌های موقت را حذف می‌کند</b>.</p><ol><li>یک ربات بله بسازید و توکن آن را بردارید.</li><li>یک کانال بسازید و ربات را ادمین کنید.</li><li>توکن و کانال را در راهنمای راه‌اندازی وارد کنید.</li><li>لینک‌ها را در برنامه یا از طریق ربات بدهید.</li></ol><p>فقط مدیرانی که شما تعریف کرده‌اید می‌توانند از ربات استفاده کنند.</p>"),
  ("create_bot", "ساخت ربات بله", "<p>ربات‌ها با ربات رسمی مدیریت ربات بله (<b>@botfather</b> داخل بله) ساخته می‌شوند. مراحل را در مستندات رسمی دنبال کنید: <a href='https://docs.bale.ai/'>docs.bale.ai</a>.</p><p>یک نام و یک شناسه کاربری انتخاب می‌کنید و BotFather <b>توکن</b> ربات را برای شما می‌فرستد.</p>"),
  ("token", "دریافت و محافظت از توکن", "<p>توکن شبیه <code>123456789:ABC-DEF...</code> است و هر کس آن را داشته باشد ربات شما را کنترل می‌کند.</p><ul><li>آن را فقط در فیلد توکن برنامه وارد کنید (در Credential Manager ویندوز نگهداری می‌شود، نه در دیتابیس یا فایل تنظیمات).</li><li>هرگز آن را در گفت‌وگو یا تصویر منتشر نکنید.</li><li>در صورت افشا، از BotFather توکن جدید بگیرید و اینجا جایگزین کنید.</li></ul><p>برنامه توکن را در لاگ‌ها، پیام‌های خطا، گزارش‌ها و خروجی‌ها مخفی می‌کند.</p>"),
  ("create_channel", "ساخت کانال", "<p>در بله: جدید ← کانال. کانال <b>عمومی</b> یک شناسه (مثل <code>@my_files</code>) دارد که ساده‌ترین روش برای معرفی کانال است.</p>"),
  ("add_bot_admin", "ادمین‌کردن ربات در کانال", "<p>کانال ← مدیران ← افزودن مدیر ← ربات خود را انتخاب کنید و اجازهٔ <b>ارسال پیام</b> بدهید. بدون این کار انتشار ممکن نیست و آزمایش کانال شکست می‌خورد.</p>"),
  ("channel_id", "دریافت شناسه کانال", "<p>برای کانال عمومی از <code>@username</code> استفاده کنید. API بله شناسه عددی را هم می‌پذیرد؛ پس از آزمایش موفق، برنامه شناسه عددیِ دریافتی از بله را نشان می‌دهد.</p><p><i>محدودیت:</i> API مستند بله فهرست کانال‌های ربات را برنمی‌گرداند؛ برای کانال خصوصیِ بدون شناسه، شناسه عددی را باید از منبع دیگری داشته باشید.</p>"),
  ("admin_id", "دریافت شناسه عددی کاربر", "<p>از فرد بخواهید یک پیام به ربات شما بدهد. اگر هنوز مجاز نباشد، ربات شناسه عددی او را در پاسخ می‌نویسد؛ آن را در بخش <b>کاربران</b> یا مرحلهٔ مدیران راهنما وارد کنید.</p>"),
  ("connection", "تنظیم اتصال", "<p>مقادیر پیش‌فرض برای بیشتر شبکه‌ها مناسب‌اند. در اتصال کند زمان‌ها را افزایش دهید؛ پروکسی (<code>http://…</code> یا <code>socks5://…</code>) فقط وقتی لازم است که بله مستقیم در دسترس نباشد.</p>"),
  ("test_connection", "آزمایش اتصال", "<p>دکمهٔ <b>آزمایش</b> کنار توکن (متد <code>getMe</code>) و کنار کانال را بزنید. آزمایش کانال یک پیام کوتاه می‌فرستد و بلافاصله حذفش می‌کند؛ چون API بله متدی برای «مجوزهای من» ندارد، این تنها راه قابل‌اعتماد بررسی دسترسی ارسال است.</p>"),
  ("bot_start_stop", "شروع و توقف ربات", "<p>با ذخیرهٔ توکن و روشن‌بودن <b>ربات فعال</b> (تنظیمات ← ربات)، ربات خودکار شروع می‌شود. با خاموش‌کردن آن دریافت پیام متوقف می‌شود؛ دانلودهای دسکتاپ ادامه می‌یابند.</p>"),
  ("download", "دانلود از لینک", "<p>از <b>دانلودها ← افزودن لینک</b>، چند لینک را Paste کنید یا TXT/CSV وارد کنید. برنامه هر لینک را ابتدا تحلیل می‌کند (نام، حجم، نوع) و شما تأیید می‌کنید. پشتیبانی: فایل مستقیم و صفحات پشتیبانی‌شده توسط yt-dlp. <b>پشتیبانی نمی‌شود:</b> محتوای DRM، محتوای پشت ورود/پرداخت، آدرس‌های شبکه داخلی.</p>"),
  ("publish", "ارسال به کانال", "<p>تصاویر JPG/PNG تا ۱۰ مگابایت به‌صورت عکس، MP4 به‌صورت ویدئو، MP3/M4A به‌صورت صوت و بقیه به‌صورت سند ارسال می‌شوند. ربات‌های بله حداکثر <b>۵۰ مگابایت</b> برای هر فایل می‌توانند آپلود کنند. اختیاری: «تقسیم فایل بزرگ» قطعات ۴۹ مگابایتی می‌فرستد. زمان‌بندی را خود برنامه انجام می‌دهد (API بله ارسال زمان‌بندی‌شده ندارد).</p>"),
  ("local_api", "API داخلی دریافت لینک (اختیاری)", "<p>تنظیمات ← ربات ← <b>فعال‌سازی API داخلی دریافت لینک</b>. سپس برنامه‌های دیگرِ همین رایانه می‌توانند لینک POST کنند:</p><pre>curl -X POST http://127.0.0.1:8765/api/v1/links -H \"Authorization: Bearer YOUR_KEY\" -H \"Content-Type: application/json\" -d \"{\\\"urls\\\":[\\\"https://example.com/a.pdf\\\"]}\"</pre><p>فقط روی 127.0.0.1 گوش می‌دهد، به کلید نمایش‌داده‌شده در تنظیمات نیاز دارد، در هر درخواست حداکثر ۲۰ لینک می‌پذیرد و به‌صورت پیش‌فرض خاموش است.</p>"),
  ("queue", "مدیریت صف", "<p>توقف، ادامه، لغو، تلاش مجدد، تغییر اولویت و تعداد دانلود هم‌زمان. صف ذخیره می‌شود و پس از بستن یا Crash بازیابی می‌شود؛ دانلود نیمه‌تمام در صورت پشتیبانی سرور از Range ادامه می‌یابد.</p>"),
  ("errors", "خطاهای متداول", "<ul><li><b>Unauthorized / توکن رد شد</b> – توکن اشتباه یا باطل‌شده.</li><li><b>Forbidden / عضو نیست</b> – ربات ادمین کانال نیست.</li><li><b>فایل بزرگ است</b> – بیش از سقف شما یا ۵۰ مگابایت بله.</li><li><b>آدرس مسدود</b> – آدرس خصوصی/داخلی (محافظت SSRF).</li><li><b>فضای دیسک کم است</b> – صف خودکار متوقف می‌شود.</li></ul>"),
  ("cleanup", "پاک‌سازی خودکار", "<p>پس از انتشار موفق، همهٔ فایل‌های موقت همان کار (دانلود، نسخهٔ پردازش‌شده، Thumbnail، فایل‌های جانبی) حذف می‌شود؛ کارهای ناموفق یا لغوشده هم پاک می‌شوند. فایل‌های رهاشده هنگام شروع و به‌صورت زمان‌بندی‌شده جارو می‌شوند. <b>حالت حریم خصوصی</b> آدرس و نام فایل را هم از تاریخچه حذف می‌کند.</p><p><i>نکتهٔ صادقانه:</i> حذف فایل با پاک‌سازی امن یکی نیست؛ ممکن است با ابزار ویژه قابل بازیابی باشد.</p>"),
  ("database", "مدیریت دیتابیس", "<p>دیتابیس SQLite فقط اطلاعات مدیریتی کارها را نگه می‌دارد، نه محتوای فایل. از تنظیمات ← پشتیبان برای بررسی سلامت، فشرده‌سازی و نگهداری استفاده کنید.</p>"),
  ("backup", "تهیه Backup و بازیابی", "<p>پشتیبان می‌تواند با رمز رمزگذاری شود. خروجی تنظیمات هرگز توکن ندارد. پیش از بازیابی، یک نسخهٔ ایمنی از دیتابیس فعلی ذخیره می‌شود.</p>"),
  ("token_security", "امنیت توکن", "<p>توکن در گاوصندوق اعتبارنامهٔ سیستم‌عامل ذخیره می‌شود؛ اگر وجود نداشت، فایل رمزگذاری‌شده با کلید مشتق از ماشین/کاربر استفاده می‌شود (جلوی خواندن عادی را می‌گیرد، نه بدافزاری که با حساب شما اجرا می‌شود).</p>"),
  ("install", "نصب و به‌روزرسانی", "<p><code>run.bat</code> را اجرا کنید (محیط مجازی می‌سازد و وابستگی‌ها را نصب می‌کند) یا از EXE ساخته‌شده با <code>build.bat</code> استفاده کنید. به‌روزرسانی هرگز خودکار نصب نمی‌شود؛ بررسی به‌روزرسانی تا زمانی که فعالش نکنید و آدرس خوراک ندهید خاموش است.</p>"),
 ],
 "faq": [
  ("آیا برنامه دانلودها را نگه می‌دارد؟", "خیر. پس از انتشار (یا شکست/لغو) پوشهٔ موقت کار حذف می‌شود. دیتابیس فقط اطلاعات مدیریتی دارد."),
  ("چرا فایل بیش از ۵۰ مگابایت رد می‌شود؟", "ربات‌های بله از طریق Bot API حداکثر ۵۰ مگابایت آپلود می‌کنند. «تقسیم فایل بزرگ» را برای قطعات ۴۹ مگابایتی فعال کنید."),
  ("آیا ارسال زمان‌بندی‌شده دارید؟", "بله، در پنجرهٔ افزودن لینک. چون API بله زمان‌بندی ندارد، برنامه کار را در زمان انتخابی شروع می‌کند."),
  ("آیا توکن من امن است؟", "در Credential Manager ویندوز ذخیره می‌شود و همه‌جا مخفی است. هرگز آن را به اشتراک نگذارید."),
  ("چه کسی می‌تواند از ربات استفاده کند؟", "فقط کاربران فهرست کاربران. بقیه یک پاسخ کوتاه «مجاز نیستید» همراه با شناسه عددی خود می‌گیرند."),
  ("چرا از IP خصوصی دانلود نمی‌شود؟", "مسدودکردن localhost و آدرس‌های خصوصی (SSRF) از شبکهٔ شما محافظت می‌کند."),
  ("چرا آزمایش کانال پیام می‌فرستد؟", "تنها راه بررسی دسترسی ارسال است؛ پیام بلافاصله حذف می‌شود."),
  ("آیا از یوتیوب و مانند آن پشتیبانی می‌شود؟", "از طریق yt-dlp برای محتوای عمومی مجاز. DRM، ورود و پرداخت پشتیبانی نمی‌شود."),
  ("اگر سیستم Crash کند چه می‌شود؟", "پس از اجرای مجدد، کارهای ناتمام به صف برمی‌گردند و در صورت امکان ادامه می‌یابند؛ فایل‌های رهاشده پاک می‌شوند."),
  ("آیا زبان دیگری هست؟", "تنظیمات ← ظاهر: فارسی (RTL)، انگلیسی و چینی؛ هر لحظه قابل تغییر."),
 ],
}

for lang, data in (("en", EN), ("fa", FA)):
    obj = {"articles": [{"id": a, "title": t, "body": b} for a, t, b in data["articles"]],
           "faq": [{"q": q, "a": a} for q, a in data["faq"]]}
    (OUT / f"{lang}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
print("help written")
