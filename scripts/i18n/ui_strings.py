# key: (English, فارسی, 中文)
D = {}
def A(k, en, fa, zh): D[k] = (en, fa, zh)

# ---------------- common
A("common.ok", "OK", "تأیید", "确定")
A("common.cancel", "Cancel", "انصراف", "取消")
A("common.yes", "Yes", "بله", "是")
A("common.no", "No", "خیر", "否")
A("common.save", "Save", "ذخیره", "保存")
A("common.reset", "Reset", "بازنشانی", "重置")
A("common.back", "Back", "بازگشت", "返回")
A("common.next", "Next", "بعدی", "下一步")
A("common.retry", "Retry", "تلاش مجدد", "重试")
A("common.test", "Test", "آزمایش", "测试")
A("common.testing", "Testing…", "در حال آزمایش…", "测试中…")
A("common.browse", "Browse…", "انتخاب…", "浏览…")
A("common.search", "Search…", "جست‌وجو…", "搜索…")
A("common.all", "All", "همه", "全部")
A("common.none", "None", "هیچ‌کدام", "无")
A("common.error", "Error", "خطا", "错误")
A("common.warning", "Warning", "هشدار", "警告")
A("common.confirm", "Please confirm", "تأیید لازم است", "请确认")
A("common.example", "Example", "مثال", "示例")
A("common.show_hide", "Show / hide", "نمایش / مخفی‌سازی", "显示 / 隐藏")
A("common.official_help", "Official help", "راهنمای رسمی", "官方帮助")
A("common.unknown", "unknown", "نامشخص", "未知")
A("common.unlimited", "unlimited", "نامحدود", "无限制")
# ---------------- navigation / app
A("nav.dashboard", "Dashboard", "داشبورد", "仪表盘")
A("nav.downloads", "Downloads", "دانلودها", "下载")
A("nav.channels", "Channels", "کانال‌ها", "频道")
A("nav.users", "Users & roles", "کاربران و نقش‌ها", "用户与角色")
A("nav.logs", "Monitor & Logs", "پایش و گزارش‌ها", "监控与日志")
A("nav.help", "Help Center", "مرکز راهنما", "帮助中心")
A("nav.settings", "Settings", "تنظیمات", "设置")
A("nav.wizard", "Setup wizard", "راهنمای راه‌اندازی", "设置向导")
A("nav.notifications", "Notifications", "اعلان‌ها", "通知")
A("notif.empty", "No notifications yet.", "هنوز اعلانی نیست.", "暂无通知。")
A("app.confirm_exit", "{n} job(s) are running. They will be paused and resumed at the next start. Exit now?", "{n} کار در حال اجرا است. متوقف می‌شوند و در اجرای بعدی ادامه می‌یابند. خارج شوید؟", "有 {n} 个任务正在运行。它们将被暂停并在下次启动时继续。现在退出吗？")
A("sb.queue", "Queue", "صف", "队列")
# ---------------- status / types / roles / themes
for k, en, fa, zh in [
    ("waiting", "Waiting", "در انتظار", "等待中"), ("validating", "Validating", "اعتبارسنجی", "验证中"),
    ("downloading", "Downloading", "در حال دانلود", "下载中"), ("paused", "Paused", "متوقف", "已暂停"),
    ("processing", "Processing", "در حال پردازش", "处理中"), ("uploading", "Uploading", "در حال ارسال", "上传中"),
    ("completed", "Completed", "تکمیل‌شده", "已完成"), ("failed", "Failed", "ناموفق", "失败"),
    ("cancelled", "Cancelled", "لغوشده", "已取消"), ("cleanup", "Cleanup", "پاک‌سازی", "清理中")]:
    A("status." + k, en, fa, zh)
for k, en, fa, zh in [("image", "Images", "تصاویر", "图片"), ("video", "Videos", "ویدئوها", "视频"), ("audio", "Audio", "صوت", "音频"),
                      ("document", "Documents", "اسناد", "文档"), ("archive", "Archives", "آرشیوها", "压缩包"), ("other", "Other files", "سایر فایل‌ها", "其他文件")]:
    A("type." + k, en, fa, zh)
for k, en, fa, zh in [("SUPER_ADMIN", "Super Admin", "مدیر ارشد", "超级管理员"), ("ADMIN", "Admin", "مدیر", "管理员"),
                      ("OPERATOR", "Operator", "اپراتور", "操作员"), ("READ_ONLY", "Read Only", "فقط‌خواندنی", "只读")]:
    A("role." + k, en, fa, zh)
for k, en, fa, zh in [("dark", "Dark", "تیره", "深色"), ("light", "Light", "روشن", "浅色"), ("windows11", "Windows 11", "ویندوز ۱۱", "Windows 11"),
                      ("midnight_blue", "Midnight Blue", "آبی نیمه‌شب", "午夜蓝"), ("graphite", "Graphite", "گرافیتی", "石墨"),
                      ("emerald", "Emerald", "زمردی", "祖母绿"), ("crimson", "Crimson", "سرخابی", "深红")]:
    A("theme." + k, en, fa, zh)
A("source.desktop", "Desktop", "دسکتاپ", "桌面")
A("source.bot", "Bot", "ربات", "机器人")
A("source.import", "Import", "وارد‌کردن", "导入")
for k, en, fa, zh in [("connected", "Connected", "متصل", "已连接"), ("connecting", "Connecting…", "در حال اتصال…", "连接中…"),
                      ("error", "Error", "خطا", "错误"), ("stopped", "Stopped", "متوقف", "已停止")]:
    A("bot.state." + k, en, fa, zh)
A("chan.status.ok", "OK", "سالم", "正常"); A("chan.status.error", "Error", "خطا", "错误"); A("chan.status.unverified", "Not verified", "تأییدنشده", "未验证")
A("pubstatus.sent", "Sent", "ارسال‌شده", "已发送"); A("pubstatus.failed", "Failed", "ناموفق", "失败"); A("pubstatus.skipped_duplicate", "Skipped (duplicate)", "رد شد (تکراری)", "已跳过（重复）")
# ---------------- columns
for k, en, fa, zh in [("file", "File", "فایل", "文件"), ("status", "Status", "وضعیت", "状态"), ("size", "Size", "حجم", "大小"),
                      ("progress", "Progress", "پیشرفت", "进度"), ("speed", "Speed", "سرعت", "速度"), ("eta", "ETA", "زمان باقی‌مانده", "剩余时间"),
                      ("priority", "Priority", "اولویت", "优先级"), ("source", "Source", "منبع", "来源"), ("info", "Info", "توضیح", "信息"),
                      ("type", "Type", "نوع", "类型"), ("default", "Default", "پیش‌فرض", "默认"), ("time", "Time", "زمان", "时间")]:
    A("col." + k, en, fa, zh)
for k, en, fa, zh in [("created_at", "Created", "ایجاد", "创建"), ("status", "Status", "وضعیت", "状态"), ("filename", "File name", "نام فایل", "文件名"),
        ("size_total", "Size", "حجم", "大小"), ("category", "Type", "نوع", "类型"), ("source", "Source", "منبع", "来源"), ("requester_id", "Requester", "درخواست‌کننده", "请求者"),
        ("result", "Result", "نتیجه", "结果"), ("error_code", "Error code", "کد خطا", "错误代码"), ("cleanup_status", "Cleanup", "پاک‌سازی", "清理"),
        ("sent_at", "Sent at", "زمان ارسال", "发送时间"), ("channel_label", "Channel", "کانال", "频道"), ("method", "Method", "روش", "方式"), ("size", "Size", "حجم", "大小"),
        ("error", "Error", "خطا", "错误"), ("ts", "Time", "زمان", "时间"), ("component", "Component", "بخش", "组件"), ("level", "Level", "سطح", "级别"),
        ("message", "Message", "پیام", "消息"), ("actor_id", "Actor ID", "شناسه عامل", "操作者ID"), ("action", "Action", "عملیات", "操作"), ("detail", "Detail", "جزئیات", "详情"),
        ("job_id", "Job ID", "شناسه کار", "任务ID"), ("reason", "Reason", "دلیل", "原因"), ("files_removed", "Files removed", "فایل حذف‌شده", "已删除文件"),
        ("bytes_freed", "Freed", "فضای آزادشده", "释放空间"), ("note", "Note", "یادداشت", "备注")]:
    A("lc." + k, en, fa, zh)
A("pub.method", "Method", "روش ارسال", "发送方式")
# ---------------- errors (codes -> readable)
E = {
 "url_empty": ("Empty link", "لینک خالی است", "链接为空"), "url_too_long": ("Link is too long", "لینک بیش از حد طولانی است", "链接过长"),
 "url_invalid": ("Invalid link", "لینک نامعتبر است", "链接无效"), "url_scheme": ("Only http/https links are allowed", "فقط لینک http/https مجاز است", "仅允许 http/https 链接"),
 "url_credentials": ("Links with embedded credentials are not allowed", "لینک حاوی نام‌کاربری/رمز مجاز نیست", "不允许包含凭据的链接"),
 "url_private": ("Private/internal address blocked (SSRF protection)", "آدرس خصوصی/داخلی مسدود شد (محافظت SSRF)", "已阻止内网/私有地址（SSRF 防护）"),
 "url_dns": ("The host name could not be resolved", "نام میزبان پیدا نشد", "无法解析主机名"), "url_blocked": ("Link blocked", "لینک مسدود شد", "链接已被阻止"),
 "duplicate_active": ("Already in the queue", "این لینک هم‌اکنون در صف است", "已在队列中"), "duplicate_done": ("Already downloaded and published", "قبلاً دانلود و منتشر شده است", "已下载并发布过"),
 "duplicate_in_batch": ("Duplicate in this batch", "تکراری در همین دسته", "本批次中重复"), "quota_exceeded": ("Daily quota exceeded", "سهمیهٔ روزانه تمام شده است", "已超出每日配额"),
 "no_channel": ("No destination channel is configured", "هیچ کانال مقصدی تنظیم نشده است", "未配置目标频道"), "file_too_large": ("File is larger than the allowed size", "حجم فایل بیش از سقف مجاز است", "文件超过允许大小"),
 "type_not_allowed": ("This file type is not allowed", "این نوع فایل مجاز نیست", "不允许此文件类型"), "html_page_not_media": ("The page is not a downloadable file", "این صفحه فایل قابل دانلود نیست", "该页面不是可下载的文件"),
 "media_unsupported": ("Not a supported file or media page", "فایل یا صفحهٔ رسانهٔ پشتیبانی‌شده نیست", "不是受支持的文件或媒体页面"), "drm_protected": ("DRM-protected content is not supported", "محتوای دارای DRM پشتیبانی نمی‌شود", "不支持受 DRM 保护的内容"),
 "live_stream": ("Live streams are not supported", "پخش زنده پشتیبانی نمی‌شود", "不支持直播流"), "access_denied_by_server": ("The server denied access (login/permission required)", "سرور دسترسی نداد (نیاز به ورود/مجوز)", "服务器拒绝访问（需要登录/权限）"),
 "http_400": ("Server error 400", "خطای ۴۰۰ سرور", "服务器错误 400"), "http_401": ("Authentication required (401)", "نیاز به احراز هویت (۴۰۱)", "需要身份验证 (401)"), "http_403": ("Access forbidden (403)", "دسترسی ممنوع (۴۰۳)", "禁止访问 (403)"),
 "http_404": ("File not found (404)", "فایل پیدا نشد (۴۰۴)", "未找到文件 (404)"), "http_429": ("Too many requests (429)", "درخواست بیش از حد (۴۲۹)", "请求过多 (429)"), "http_500": ("Server error (500)", "خطای سرور (۵۰۰)", "服务器错误 (500)"),
 "http_502": ("Bad gateway (502)", "دروازه نامعتبر (۵۰۲)", "网关错误 (502)"), "http_503": ("Service unavailable (503)", "سرویس در دسترس نیست (۵۰۳)", "服务不可用 (503)"),
 "probe_failed": ("Could not analyse the link", "تحلیل لینک ممکن نشد", "无法分析链接"), "executable_blocked": ("Executable programs are blocked", "فایل‌های اجرایی مسدودند", "已阻止可执行程序"),
 "executable_disguised": ("File is an executable disguised as another type", "فایل اجرایی با ظاهر نوع دیگری است", "文件是伪装成其他类型的可执行文件"), "html_instead_of_file": ("Received a web page instead of the file", "به‌جای فایل یک صفحهٔ وب دریافت شد", "收到的是网页而不是文件"),
 "type_mismatch": ("File content does not match its type", "محتوای فایل با نوع آن مطابقت ندارد", "文件内容与类型不符"), "unsafe_archive": ("Unsafe archive (path traversal / bomb)", "آرشیو ناامن (Zip Slip / بمب فشرده)", "不安全的压缩包（路径穿越/压缩炸弹）"),
 "malware_detected": ("Antivirus flagged the file", "آنتی‌ویروس فایل را مشکوک اعلام کرد", "杀毒软件报告该文件有风险"), "size_mismatch": ("Downloaded size does not match", "حجم دریافتی با انتظار نمی‌خواند", "下载大小不匹配"),
 "range_unsupported": ("Server does not support partial downloads", "سرور دانلود قطعه‌ای را پشتیبانی نمی‌کند", "服务器不支持分段下载"), "too_many_redirects": ("Too many redirects", "تعداد تغییر مسیر بیش از حد است", "重定向过多"),
 "download_failed": ("Download failed", "دانلود ناموفق بود", "下载失败"), "disk_space_low": ("Not enough free disk space", "فضای آزاد دیسک کافی نیست", "磁盘可用空间不足"),
 "internal_error": ("Internal error (see error log)", "خطای داخلی (گزارش خطا را ببینید)", "内部错误（请查看错误日志）"), "bale_auth_error": ("Bale rejected the bot token", "بله توکن ربات را رد کرد", "Bale 拒绝了机器人令牌"),
 "bale_network_error": ("Cannot reach Bale (network)", "ارتباط با بله برقرار نشد (شبکه)", "无法连接 Bale（网络）"), "bale_api_error": ("Bale API error", "خطای API بله", "Bale API 错误"),
 "too_large_for_bale": ("Bale bots can upload at most 50 MB", "ربات‌های بله حداکثر ۵۰ مگابایت آپلود می‌کنند", "Bale 机器人最多可上传 50 MB"), "publish_failed": ("Publishing failed", "انتشار ناموفق بود", "发布失败"),
 "interrupted": ("Interrupted by a crash or exit", "با بسته‌شدن/Crash قطع شد", "因崩溃或退出而中断"), "cancelled": ("Cancelled", "لغو شد", "已取消"),
 "media_download_failed": ("Media download failed", "دانلود رسانه ناموفق بود", "媒体下载失败"), "path_traversal": ("Unsafe path blocked", "مسیر ناامن مسدود شد", "已阻止不安全路径"),
 "rate_limited": ("Too many requests", "درخواست بیش از حد", "请求过多"), "access_denied": ("Access denied", "دسترسی رد شد", "访问被拒绝"), "not_downloadable": ("Not downloadable", "قابل دانلود نیست", "无法下载"),
}
for k, (en, fa, zh) in E.items():
    A("error." + k, en, fa, zh)
A("bk.err.backup_password_required", "This backup is encrypted – enter its password.", "این پشتیبان رمزگذاری شده است؛ رمز را وارد کنید.", "此备份已加密，请输入密码。")
A("bk.err.backup_bad_password", "Wrong password or corrupted backup.", "رمز اشتباه است یا پشتیبان خراب است.", "密码错误或备份已损坏。")
A("bk.err.backup_invalid", "The backup file is not a valid database.", "فایل پشتیبان دیتابیس معتبر نیست.", "备份文件不是有效的数据库。")
A("bk.err.backup_integrity", "Database failed its integrity check.", "دیتابیس بررسی سلامت را رد کرد.", "数据库完整性检查失败。")
# ---------------- validation messages
A("err.required", "This field is required.", "این فیلد الزامی است.", "此项为必填。")
A("err.token_format", "Token format looks wrong. Expected digits, a colon and letters/digits (e.g. 123456789:ABC-DEF…).", "قالب توکن درست نیست. باید عدد، دونقطه و حروف/اعداد باشد (مثل 123456789:ABC-DEF…).", "令牌格式不正确。应为数字、冒号和字母/数字（例如 123456789:ABC-DEF…）。")
A("err.token_rejected", "Bale did not accept this token: {detail}", "بله این توکن را نپذیرفت: {detail}", "Bale 不接受此令牌：{detail}")
A("err.username_format", "Use 3–64 letters, digits or underscore (with or without @).", "۳ تا ۶۴ حرف، عدد یا زیرخط (با یا بدون @).", "3–64 个字母、数字或下划线（可带 @）。")
A("err.channel_format", "Use @channel_username or a numeric chat id.", "از @شناسه_کانال یا شناسه عددی استفاده کنید.", "请使用 @频道用户名 或数字聊天ID。")
A("err.numeric_id", "Numeric user IDs only (digits).", "فقط شناسهٔ عددی (ارقام).", "仅限数字用户ID。")
A("err.not_dir", "This path exists but is not a folder.", "این مسیر وجود دارد اما پوشه نیست.", "该路径存在但不是文件夹。")
A("err.proxy_format", "Use http://, https:// or socks5:// followed by host:port.", "از http://‎، https://‎ یا socks5://‎ و سپس host:port استفاده کنید.", "请使用 http://、https:// 或 socks5://，后接 主机:端口。")
