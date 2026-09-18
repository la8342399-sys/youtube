import asyncio
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

asyncio.set_event_loop(asyncio.new_event_loop())

from dotenv import load_dotenv
from pyrogram import Client
from pytgcalls import GroupCallFactory
from pytgcalls.implementation.group_call_file import GroupCallFile
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.error import BadRequest
from telegram.helpers import escape_markdown
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
SESSION_STRINGS = os.getenv("SESSION_STRINGS", "")
SESSION_STRING_2 = os.getenv("SESSION_STRING_2", "") or os.getenv("SESSION_STRINGS_2", "")

configured_session_strings = [
    value.strip()
    for value in re.split(r"[,\n]+", f"{SESSION_STRING},{SESSION_STRINGS}")
    if value.strip()
]
if SESSION_STRING_2:
    configured_session_strings.extend(
        value.strip()
        for value in re.split(r"[,\n]+", SESSION_STRING_2)
        if value.strip()
    )
configured_session_strings = list(dict.fromkeys(configured_session_strings))
CACHE_DIR = Path(os.getenv("CACHE_DIR", "cache"))
if not CACHE_DIR.is_absolute():
    CACHE_DIR = BASE_DIR / CACHE_DIR
CACHE_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_FILE_IDS_PATH = CACHE_DIR / "audio_file_ids.json"
WARNINGS_PATH = CACHE_DIR / "warnings.json"
WARN_VOTES_PATH = CACHE_DIR / "warn_votes.json"
SETTINGS_PATH = CACHE_DIR / "settings.json"
USER_DATA_PATH = CACHE_DIR / "user_data.json"
BAD_WORDS_PATH = BASE_DIR / "bad_words.txt"
BOT_OWNER_IDS = {
    int(value.strip())
    for value in re.split(r"[,\s]+", os.getenv("BOT_OWNER_IDS", ""))
    if value.strip().lstrip("-").isdigit()
}
BOT_OWNER_USERNAMES = {
    value.strip().lstrip("@").casefold()
    for value in re.split(r"[,\s]+", os.getenv("BOT_OWNER_USERNAMES", ""))
    if value.strip()
}
if not BOT_OWNER_IDS:
    logger.warning("BOT_OWNER_IDS is empty: owner-only commands are disabled")
CLEANUP_INTERVAL_MINUTES = max(1, int(os.getenv("CLEANUP_INTERVAL_MINUTES", "15")))
PRIVATE_FORCED_CHANNEL = os.getenv("PRIVATE_FORCED_CHANNEL", "@vozvzo").strip()
DEVELOPER_USERNAME = os.getenv("DEVELOPER_USERNAME", "znvsv").strip().lstrip("@")
DEVELOPER_NAME = os.getenv("DEVELOPER_NAME", "شمري").strip()

DEFAULT_FEATURES = {
    "download": True,
    "protection": True,
    "voice": False,
    "games": False,
    "force_sub": False,
}
FEATURE_LABELS = {
    "download": "يوت / تنزيل الأغاني",
    "voice": "شغل / المكالمة الصوتية",
    "games": "الألعاب",
    "protection": "الحماية والتحذيرات",
    "force_sub": "الاشتراك الإجباري",
}
FEATURE_ALIASES = {
    "يوت": "download",
    "تحميل": "download",
    "تنزيل": "download",
    "اغاني": "download",
    "أغاني": "download",
    "شغل": "voice",
    "مكالمة": "voice",
    "مكالمه": "voice",
    "صوت": "voice",
    "العاب": "games",
    "ألعاب": "games",
    "حماية": "protection",
    "الحماية": "protection",
    "تحذيرات": "protection",
    "اشتراك": "force_sub",
    "الاشتراك": "force_sub",
    "اجباري": "force_sub",
    "إجباري": "force_sub",
}
BOT_COMMAND_PATTERNS = [
    r"^يوت\s+.+$",
    r"^شغل\s+.+$",
    r"^(العاب|ألعاب|الاوامر|كتم|رفع كتم|تحذير|رفع تحذير|مسح|مسح الكل|مسح تحذيرات)(?:\s+.*)?$",
    r"^(تخطي|غني|توقف|إيقاف|ايقاف|اوكف)$",
    r"^/(pause|resume|skip|stop|volume|clean|mute|unmute|warn|unwarn|clearwarnings|games)(?:@\w+)?(?:\s+.*)?$",
]
OWNER_COMMAND_RE = re.compile(
    r"^(تفعيل|الغاء تفعيل|إلغاء تفعيل|ت م|الميزات|حالة الاشتراك|تاريخ|تاريخ الاشتراك|اشتراك اجباري|اشتراك إجباري|حذف اشتراك اجباري|الغاء اشتراك اجباري|إلغاء اشتراك إجباري|ايدي|آيدي|مسح رسائلي)(?:\s+.*)?$",
    flags=re.IGNORECASE,
)
ACTIVATION_REQUIRED_TEXT = (
    "⛔️ تعذّر تفعيل البوت\n\n"
    "لا يمكن تفعيل البوت إلا بأمر مباشر من أحد مطوّري البوت 🛠️\n\n"
    "🔐 حفاظًا على أمان النظام وتنظيم الصلاحيات، يرجى التواصل مع أحد المطوّرين لإتمام التفعيل.\n\n"
    "✦ إدارة وتطوير البوت:\n"
    "👤 @znvsv — الشمري"
)

try:
    AUDIO_FILE_IDS: dict[str, str] = json.loads(AUDIO_FILE_IDS_PATH.read_text(encoding="utf-8"))
except (FileNotFoundError, json.JSONDecodeError):
    AUDIO_FILE_IDS = {}

try:
    raw_warnings = json.loads(WARNINGS_PATH.read_text(encoding="utf-8"))
    if isinstance(raw_warnings, dict):
        WARNINGS: dict[str, int] = {
            str(key): max(0, int(value))
            for key, value in raw_warnings.items()
            if int(value) > 0
        }
    else:
        WARNINGS = {}
except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
    WARNINGS = {}

try:
    raw_warn_votes = json.loads(WARN_VOTES_PATH.read_text(encoding="utf-8"))
    WARN_VOTES: dict[str, dict[str, Any]] = raw_warn_votes if isinstance(raw_warn_votes, dict) else {}
except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
    WARN_VOTES = {}

try:
    raw_settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    SETTINGS: dict[str, Any] = raw_settings if isinstance(raw_settings, dict) else {}
except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
    SETTINGS = {}

try:
    raw_user_data = json.loads(USER_DATA_PATH.read_text(encoding="utf-8"))
    USER_DATA: dict[str, dict[str, Any]] = raw_user_data if isinstance(raw_user_data, dict) else {}
except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
    USER_DATA = {}

voice_client: Client | None = None
voice_clients: list[Client] = []
voice_client_users: dict[Client, Any] = {}
voice_initialization_error: str | None = None
voice_calls: Any | None = None
voice_calls_by_group: dict[int, Any] = {}
voice_clients_by_group: dict[int, Client] = {}
game_states: dict[tuple[int, int], dict[str, Any]] = {}
tracked_messages: dict[int, deque[tuple[int, int]]] = {}
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(max(1, int(os.getenv("DOWNLOAD_CONCURRENCY", "8"))))


async def search_song_async(query: str, download: bool = False) -> dict[str, Any]:
    async with DOWNLOAD_SEMAPHORE:
        return await asyncio.to_thread(search_song, query, download)
PRIVILEGE_CACHE: dict[tuple[int, int], tuple[float, bool]] = {}
SUBSCRIPTION_CACHE: dict[tuple[int, int, str], tuple[float, bool]] = {}
MEMBERSHIP_CACHE_TTL = 60
MUSIC_API_URL = os.getenv("MUSIC_API_URL", "http://127.0.0.1:8000").rstrip("/")
MUSIC_API_TIMEOUT = max(5, int(os.getenv("MUSIC_API_TIMEOUT", "120")))
MUSIC_API_AUTOSTART = os.getenv("MUSIC_API_AUTOSTART", "1").strip().lower() not in {"0", "false", "no"}
music_api_process: subprocess.Popen[bytes] | None = None


class MusicServiceError(RuntimeError):
    pass


def start_local_music_api() -> subprocess.Popen[bytes] | None:
    """تشغيل خدمة الموسيقى محليًا عند عدم وجود خدمة جاهزة."""
    global music_api_process
    if not MUSIC_API_AUTOSTART:
        return None

    parsed_url = urllib.parse.urlparse(MUSIC_API_URL)
    if parsed_url.hostname not in {"127.0.0.1", "localhost"}:
        return None

    health_url = f"{MUSIC_API_URL}/health"
    try:
        with urllib.request.urlopen(health_url, timeout=1):
            return None
    except (urllib.error.URLError, TimeoutError):
        pass

    port = str(parsed_url.port or 8000)
    try:
        music_api_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "music_api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                port,
            ],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
    except OSError as error:
        logger.warning("Could not start local music service: %s", error)
        return None

    for _ in range(20):
        try:
            with urllib.request.urlopen(health_url, timeout=1):
                logger.info("Music service started on %s", MUSIC_API_URL)
                return music_api_process
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.25)

    logger.warning("Local music service did not become ready")
    music_api_process.terminate()
    music_api_process = None
    return None


def stop_local_music_api() -> None:
    if music_api_process is not None and music_api_process.poll() is None:
        music_api_process.terminate()
        try:
            music_api_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            music_api_process.kill()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def save_settings() -> None:
    SETTINGS_PATH.write_text(
        json.dumps(SETTINGS, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_user_data() -> None:
    USER_DATA_PATH.write_text(
        json.dumps(USER_DATA, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_user_data(user: Any) -> dict[str, Any]:
    key = str(user.id)
    data = USER_DATA.setdefault(
        key,
        {"points": 0, "messages": 0, "downloads": 0, "joined_at": now_utc().isoformat()},
    )
    data.setdefault("points", 0)
    data.setdefault("messages", 0)
    data.setdefault("downloads", 0)
    return data


def add_user_points(user: Any, points: int = 1) -> dict[str, Any]:
    data = get_user_data(user)
    data["points"] = max(0, int(data.get("points", 0)) + points)
    data["messages"] = int(data.get("messages", 0)) + 1
    save_user_data()
    return data


def user_level(points: int) -> tuple[int, str]:
    level = max(1, points // 100 + 1)
    return level, f"المستوى {level}"


def private_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 بحث عن أغنية", callback_data="private:search")],
        [InlineKeyboardButton("💿 البحث عن ألبوم", callback_data="private:album")],
        [InlineKeyboardButton("🎚️ اختيار الجودة", callback_data="private:quality"), InlineKeyboardButton("🔗 إرسال رابط الأغنية", callback_data="private:link")],
        [InlineKeyboardButton("📊 إحصائيات البوت", callback_data="private:stats")],
        [InlineKeyboardButton(f"🛠 المطور: {DEVELOPER_NAME}", url=f"https://t.me/{DEVELOPER_USERNAME}")],
    ])


def save_warn_votes() -> None:
    WARN_VOTES_PATH.write_text(
        json.dumps(WARN_VOTES, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def cleanup_cache_and_logs() -> tuple[int, int, int]:
    """تنظيف الملفات المؤقتة والملفات القديمة قبل أن تملأ السيرفر."""
    now = time.time()
    removed_files = 0
    removed_dirs = 0
    bytes_removed = 0
    protected_names = {"audio_file_ids.json", "warnings.json", "warn_votes.json", "settings.json"}

    for path in sorted(CACHE_DIR.rglob("*"), key=lambda item: str(item).lower()):
        try:
            if path.is_dir():
                if path.name in {"__pycache__"}:
                    for child in sorted(path.rglob("*"), reverse=True):
                        if child.is_file():
                            try:
                                child.unlink()
                                removed_files += 1
                                bytes_removed += child.stat().st_size if child.exists() else 0
                            except Exception:
                                pass
                    try:
                        path.rmdir()
                        removed_dirs += 1
                    except Exception:
                        pass
                continue

            if path.name in protected_names:
                continue

            if path.suffix.lower() in {".log", ".tmp", ".bak"}:
                path.unlink()
                removed_files += 1
                continue

            if path.suffix.lower() in {".mp3", ".m4a", ".webm", ".opus", ".wav", ".ogg"}:
                if (now - path.stat().st_mtime) > 2 * 86400:
                    bytes_removed += path.stat().st_size
                    path.unlink()
                    removed_files += 1
                    continue

            if path.name.startswith("yt_dlp") or path.name.endswith(".part"):
                bytes_removed += path.stat().st_size
                path.unlink()
                removed_files += 1
        except Exception:
            continue

    for directory in [CACHE_DIR / "yt_dlp_cache", CACHE_DIR / "temp"]:
        if directory.exists() and directory.is_dir():
            try:
                for child in list(directory.rglob("*")):
                    if child.is_file() and (now - child.stat().st_mtime) > 2 * 86400:
                        bytes_removed += child.stat().st_size
                        child.unlink()
                        removed_files += 1
                for child in sorted(directory.rglob("*"), reverse=True):
                    if child.is_dir():
                        try:
                            child.rmdir()
                            removed_dirs += 1
                        except Exception:
                            pass
                if not any(directory.iterdir()):
                    try:
                        directory.rmdir()
                        removed_dirs += 1
                    except Exception:
                        pass
            except Exception:
                continue

    return removed_files, removed_dirs, bytes_removed


async def periodic_cache_cleanup() -> None:
    while True:
        try:
            removed_files, removed_dirs, bytes_removed = cleanup_cache_and_logs()
            if removed_files or removed_dirs or bytes_removed:
                logger.info(
                    "Cleaned cache: files=%s directories=%s bytes=%s",
                    removed_files,
                    removed_dirs,
                    bytes_removed,
                )
        except Exception:
            logger.exception("Cache cleanup failed")
        await asyncio.sleep(CLEANUP_INTERVAL_MINUTES * 60)


async def _legacy_post_init(_: Application) -> None:
    """تهيئة البوت عند التشغيل"""
    global voice_client, voice_clients, voice_client_users
    if not (API_ID and API_HASH and configured_session_strings):
        logger.warning("⚠️ Voice calls disabled: missing API_ID, API_HASH, or session strings")
        return

    for index, session_string in enumerate(configured_session_strings, start=1):
        client = Client(
            f"voice_session_{index}",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=session_string,
        )
        try:
            await client.start()
            voice_clients.append(client)
            me = await client.get_me()
            voice_client_users[client] = me
            if voice_client is None:
                voice_client = client
            logger.info(f"✅ Voice client {index} started as: {me.first_name} (@{me.username})")
        except Exception:
            logger.exception(f"❌ Failed to start voice client {index}")
            try:
                await client.stop()
            except Exception:
                pass

    asyncio.create_task(periodic_cache_cleanup())


async def _legacy_post_shutdown(_: Application) -> None:
    """إيقاف البوت بشكل نظيف"""
    global voice_calls_by_group, voice_clients

    for group_call in voice_calls_by_group.values():
        try:
            await group_call.stop()
        except Exception:
            pass
    voice_calls_by_group.clear()

    for client in voice_clients:
        try:
            await client.stop()
        except Exception:
            pass

    logger.info("✅ Bot shut down cleanly")


def chat_settings(chat_id: int) -> dict[str, Any]:
    key = str(chat_id)
    if key not in SETTINGS or not isinstance(SETTINGS[key], dict):
        SETTINGS[key] = {}
    settings = SETTINGS[key]
    features = settings.get("features")
    if not isinstance(features, dict):
        features = {}
        settings["features"] = features
    for feature, enabled in DEFAULT_FEATURES.items():
        features.setdefault(feature, enabled)
    return settings


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "غير مفعّل"
    local_time = value.astimezone()
    return local_time.strftime("%Y-%m-%d %H:%M")


def is_chat_active(chat_id: int) -> bool:
    settings = chat_settings(chat_id)
    expires_at = parse_datetime(settings.get("expires_at"))
    return expires_at is not None and expires_at > now_utc()


def subscription_plan_duration(text: str, fallback: str = "month") -> tuple[str, timedelta]:
    normalized = normalize_moderation_text(text)
    number_match = re.search(r"\d+", normalized)
    amount = max(1, int(number_match.group(0))) if number_match else 1
    if "ساعه" in normalized or "ساعة" in normalized or "ساعات" in normalized or "ساعتين" in normalized or "hour" in normalized:
        return "hour", timedelta(hours=amount)
    if "يوم" in normalized or "يومين" in normalized or "ايام" in normalized or "أيام" in normalized or "day" in normalized:
        return "day", timedelta(days=amount)
    if "اسبوع" in normalized or "سبوع" in normalized or "week" in normalized:
        return "week", timedelta(days=7 * amount)
    if "شهر" in normalized or "شهري" in normalized or "month" in normalized:
        return "month", timedelta(days=30 * amount)
    return fallback, timedelta(days=7 if fallback == "week" else 30)


def subscription_plan_label(plan: str) -> str:
    return {
        "hour": "بالساعات",
        "day": "يومي",
        "week": "أسبوعي",
        "month": "شهري",
    }.get(plan, "شهري")


def has_subscription_plan(text: str) -> bool:
    normalized = normalize_moderation_text(text)
    return any(word in normalized for word in {"ساعه", "ساعة", "ساعات", "ساعتين", "hour", "يوم", "يومين", "ايام", "أيام", "day", "اسبوع", "سبوع", "week", "شهر", "شهري", "month"})


def feature_enabled(chat_id: int, feature: str) -> bool:
    return bool(chat_settings(chat_id)["features"].get(feature, False))


def feature_from_text(text: str) -> str | None:
    normalized = normalize_moderation_text(text)
    for alias, feature in FEATURE_ALIASES.items():
        if normalize_moderation_text(alias) in normalized:
            return feature
    return None


def is_bot_command_text(text: str) -> bool:
    stripped = text.strip()
    return any(re.match(pattern, stripped, flags=re.IGNORECASE) for pattern in BOT_COMMAND_PATTERNS)


def is_bot_owner_user(user: Any) -> bool:
    if not user:
        return False
    return user.id in BOT_OWNER_IDS


def read_bool_cache(cache: dict[Any, tuple[float, bool]], key: Any) -> bool | None:
    cached = cache.get(key)
    if cached is None:
        return None
    expires_at, value = cached
    if expires_at < time.monotonic():
        cache.pop(key, None)
        return None
    return value


def write_bool_cache(cache: dict[Any, tuple[float, bool]], key: Any, value: bool) -> bool:
    cache[key] = (time.monotonic() + MEMBERSHIP_CACHE_TTL, value)
    return value


def channel_join_url(channel: str) -> str:
    channel = channel.strip()
    if channel.startswith("@"):
        return f"https://t.me/{channel[1:]}"
    if re.fullmatch(r"[A-Za-z0-9_]{5,}", channel):
        return f"https://t.me/{channel}"
    return channel


def normalize_forced_channel(value: str) -> str:
    value = value.strip()
    match = re.search(r"(?:https?://)?t\.me/(?:joinchat/|\+)?([A-Za-z0-9_]{5,})/?", value, flags=re.IGNORECASE)
    if match:
        return f"@{match.group(1)}"
    if re.fullmatch(r"[A-Za-z0-9_]{5,}", value):
        return f"@{value}"
    return value


def forced_channel_label(channel: str) -> str:
    channel = normalize_forced_channel(channel)
    if channel.startswith("@"):
        return channel
    if re.fullmatch(r"[A-Za-z0-9_]{5,}", channel):
        return f"@{channel}"
    return "الكروب/القناة"


def forced_channel(chat_id: int) -> str | None:
    value = chat_settings(chat_id).get("forced_channel")
    return normalize_forced_channel(value) if isinstance(value, str) and value.strip() else None


def forced_channel_id(chat_id: int) -> int | None:
    value = chat_settings(chat_id).get("forced_channel_id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def is_privileged_in_chat(
    user_id: int,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    user: Any = None,
) -> bool:
    if is_bot_owner_user(user):
        return True
    cache_key = (chat_id, user_id)
    cached = read_bool_cache(PRIVILEGE_CACHE, cache_key)
    if cached is not None:
        return cached
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return write_bool_cache(PRIVILEGE_CACHE, cache_key, member.status in {"administrator", "creator"})
    except Exception:
        return write_bool_cache(PRIVILEGE_CACHE, cache_key, False)


async def has_forced_subscription(
    user_id: int,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    refresh: bool = False,
) -> bool:
    channel = forced_channel(chat_id)
    if not channel or not feature_enabled(chat_id, "force_sub"):
        return True
    cache_key = (chat_id, user_id, channel)
    if refresh:
        SUBSCRIPTION_CACHE.pop(cache_key, None)
    else:
        cached = read_bool_cache(SUBSCRIPTION_CACHE, cache_key)
        if cached is not None:
            return cached
    try:
        member = await context.bot.get_chat_member(channel, user_id)
        return write_bool_cache(SUBSCRIPTION_CACHE, cache_key, member.status not in {"left", "kicked"})
    except Exception:
        logger.warning("Could not verify forced subscription for %s in %s", user_id, channel)
        return write_bool_cache(SUBSCRIPTION_CACHE, cache_key, False)


async def validate_forced_subscription_target(
    channel: str,
    context: ContextTypes.DEFAULT_TYPE,
) -> tuple[str, int | None, str | None]:
    target = normalize_forced_channel(channel)
    try:
        chat = await context.bot.get_chat(target)
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
    except Exception as error:
        logger.warning("Forced subscription target is not accessible: %s", error)
        return target, None, "ما أكدر أوصل للقناة/الكروب. أضف البوت هناك أولاً، ويفضّل تخليه مشرف، بعدها فعّل الاشتراك الإجباري."

    if bot_member.status in {"left", "kicked"}:
        return target, chat.id, "البوت مو مضاف بالقناة/الكروب المطلوب."
    title = getattr(chat, "title", None) or getattr(chat, "username", None) or target
    return target, chat.id, None


def clear_forced_subscription_cache(chat_id: int, user_id: int | None = None) -> None:
    channel = forced_channel(chat_id)
    for key in list(SUBSCRIPTION_CACHE):
        key_chat_id, key_user_id, key_channel = key
        if key_chat_id == chat_id and (user_id is None or key_user_id == user_id) and (channel is None or key_channel == channel):
            SUBSCRIPTION_CACHE.pop(key, None)


def normalize_moderation_text(text: str) -> str:
    """توحيد النص قبل فحص الكلمات مع الحفاظ على حدود الكلمات."""
    text = text.casefold().replace("ـ", "")
    text = re.sub(r"[\u064B-\u065F\u0670]", "", text)
    text = text.translate(str.maketrans("إأآٱى", "ااااي"))
    return re.sub(r"\s+", " ", text).strip()


class BadWordsMatcher:
    """بحث متعدد الكلمات في مرور واحد باستخدام Aho-Corasick."""

    def __init__(self, words: list[str]) -> None:
        self.transitions: list[dict[str, int]] = [{}]
        self.failures: list[int] = [0]
        self.outputs: list[bool] = [False]
        for word in words:
            node = 0
            for character in word:
                if character not in self.transitions[node]:
                    self.transitions[node][character] = len(self.transitions)
                    self.transitions.append({})
                    self.failures.append(0)
                    self.outputs.append(False)
                node = self.transitions[node][character]
            self.outputs[node] = True

        queue = deque()
        for node in self.transitions[0].values():
            queue.append(node)
        while queue:
            node = queue.popleft()
            for character, child in self.transitions[node].items():
                fallback = self.failures[node]
                while fallback and character not in self.transitions[fallback]:
                    fallback = self.failures[fallback]
                self.failures[child] = self.transitions[fallback].get(character, 0)
                self.outputs[child] |= self.outputs[self.failures[child]]
                queue.append(child)

    def contains_bad_word(self, text: str) -> bool:
        node = 0
        for character in text:
            while node and character not in self.transitions[node]:
                node = self.failures[node]
            node = self.transitions[node].get(character, 0)
            if self.outputs[node]:
                return True
        return False


def load_bad_words() -> BadWordsMatcher:
    try:
        lines = BAD_WORDS_PATH.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    words = {
        normalize_moderation_text(line)
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    }
    words.discard("")
    logger.info("Loaded %s moderation terms", len(words))
    return BadWordsMatcher(sorted(words, key=len, reverse=True))


BAD_WORDS_MATCHER = load_bad_words()


def build_voice_panel(group_id: int) -> InlineKeyboardMarkup:
    """لوحة تحكم ثابتة تبقى ظاهرة أثناء التشغيل."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⏸ اوكف", callback_data=f"voice_pause:{group_id}"),
                InlineKeyboardButton("▶ غني", callback_data=f"voice_resume:{group_id}"),
            ],
            [InlineKeyboardButton("⏭ تخطي", callback_data=f"voice_skip:{group_id}")],
        ]
    )


def is_probable_url(value: str) -> bool:
    return bool(re.match(r"^https?://", value.strip(), flags=re.IGNORECASE))


def youtube_entry_url(entry: dict[str, Any]) -> str | None:
    webpage_url = entry.get("webpage_url")
    if isinstance(webpage_url, str) and is_probable_url(webpage_url):
        return webpage_url
    entry_id = str(entry.get("id") or "")
    if re.fullmatch(r"[\w-]{11}", entry_id):
        return f"https://www.youtube.com/watch?v={entry_id}"
    url = entry.get("url")
    if isinstance(url, str) and is_probable_url(url):
        return url
    return None


def local_music_fallback(query: str, download: bool) -> dict[str, Any]:
    from music_api.main import download_audio_file, search_youtube

    result = search_youtube(query)
    if result is None:
        raise MusicServiceError("لم يتم العثور على الأغنية")
    song = dict(result)
    if download:
        song["filepath"] = str(download_audio_file(query))
    return song


def search_song(query: str, download: bool = False) -> dict[str, Any]:
    """البحث والتنزيل عبر خدمة الموسيقى الخارجية، بدون كوكيز محلية."""
    query_url = urllib.parse.urlencode({"q": query})
    try:
        with urllib.request.urlopen(
            f"{MUSIC_API_URL}/search?{query_url}",
            timeout=MUSIC_API_TIMEOUT,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        logger.warning("Music service search failed: %s", error)
        try:
            logger.info("Using local music fallback after service search failure")
            return local_music_fallback(query, download)
        except Exception as fallback_error:
            raise MusicServiceError("تعذر البحث عن الأغنية") from fallback_error

    if not isinstance(payload, dict) or not payload.get("title"):
        try:
            return local_music_fallback(query, download)
        except Exception as error:
            raise ValueError("لم يتم العثور على الأغنية") from error

    song: dict[str, Any] = dict(payload)
    if not download:
        return song

    song_id = str(song.get("id") or abs(hash(normalized_query(query))))
    audio_path = CACHE_DIR / f"{song_id}.mp3"
    if not audio_path.is_file():
        try:
            with urllib.request.urlopen(
                f"{MUSIC_API_URL}/download?{query_url}",
                timeout=MUSIC_API_TIMEOUT,
            ) as response, audio_path.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as error:
            audio_path.unlink(missing_ok=True)
            logger.warning("Music service download failed: %s", error)
            try:
                logger.info("Using local music fallback after service download failure")
                return local_music_fallback(query, True)
            except Exception as fallback_error:
                raise MusicServiceError("تعذر تنزيل الملف الصوتي") from fallback_error

    song["filepath"] = str(audio_path)
    return song


def downloaded_audio(song: dict[str, Any]) -> Path:
    """الحصول على مسار الملف الصوتي المحمّل، أو إرجاع ملف موجود من الكاش."""
    reported_paths = [
        song.get("filepath"),
        song.get("_filename"),
        song.get("filename"),
    ]
    for download in song.get("requested_downloads") or []:
        if isinstance(download, dict):
            reported_paths.append(download.get("filepath"))
            reported_paths.append(download.get("_filename"))
            reported_paths.append(download.get("filename"))

    audio_suffixes = {".mp3", ".m4a", ".mp4", ".webm", ".weba", ".opus", ".ogg", ".wav"}
    for reported_path in reported_paths:
        if reported_path:
            path = Path(reported_path)
            if not path.is_absolute():
                path = BASE_DIR / path
            if path.is_file() and path.suffix.lower() in audio_suffixes:
                return path

    song_id = str(song.get("id") or "")
    matches = list(CACHE_DIR.rglob(f"{song_id}.*")) if song_id else []

    audio_files = [path for path in matches if path.suffix.lower() in audio_suffixes]

    if not audio_files:
        all_files = [
            path
            for path in CACHE_DIR.rglob("*")
            if path.is_file() and path.suffix.lower() in audio_suffixes
        ]
        if all_files:
            return max(all_files, key=os.path.getctime)
        logger.warning(
            "Could not locate downloaded audio. song_id=%s reported_paths=%s cache_dir=%s",
            song_id,
            [str(path) for path in reported_paths if path],
            CACHE_DIR,
        )
        raise FileNotFoundError("تعذر تجهيز الملف الصوتي")

    return max(audio_files, key=os.path.getctime)


def normalized_query(query: str) -> str:
    """توحيد اسم الأغنية لاستخدامه في كاش تيليجرام."""
    return re.sub(r"\s+", " ", query.strip().casefold())


def format_song_duration(duration: Any) -> str:
    if duration is None:
        return "غير معروفة"
    try:
        total_seconds = max(0, int(float(duration)))
    except (TypeError, ValueError):
        return "غير معروفة"
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def song_artist(song: dict[str, Any]) -> str:
    artist = song.get("artist") or song.get("uploader") or song.get("channel")
    return str(artist).strip() if artist else "غير معروف"


def song_quality(song: dict[str, Any], audio_path: Path | None = None) -> str:
    bitrate = song.get("abr") or song.get("tbr")
    if bitrate:
        try:
            return f"MP3 / {int(float(bitrate))} kbps"
        except (TypeError, ValueError):
            pass
    if audio_path and audio_path.suffix:
        return audio_path.suffix.lstrip(".").upper()
    return "MP3"


def song_success_text(song: dict[str, Any], requester_name: str, audio_path: Path | None = None) -> str:
    title = str(song.get("title") or "غير معروف").strip()
    duration = format_song_duration(song.get("duration"))
    return (
        "🎶 تم تشغيل الأغنية بنجاح\n\n"
        f"🎵 الأغنية: {title}\n"
        f"👤 الفنان: {song_artist(song)}\n"
        f"⏱️ المدة: {duration}\n"
        f"🎧 الجودة: {song_quality(song, audio_path)}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"🎙️ طلبها: {requester_name}\n"
        "▶️ يتم تشغيلها الآن...\n\n"
        "استمتع بالموسيقى 🎶❤️"
    )


def download_success_text(song: dict[str, Any], requester_name: str) -> str:
    title = str(song.get("title") or "غير معروف").strip()
    return (
        f"🎵 الأغنية: {title}\n"
        f"🎙️ طلبها: {requester_name}\n\n"
        "✅ تم جلب الأغنية بنجاح"
    )



def control_user_label(user: Any) -> str:
    if user and user.username:
        return f"@{user.username}"
    return user.first_name if user and user.first_name else "مشرف"


def save_audio_file_id(query: str, file_id: str) -> None:
    """حفظ معرف الملف حتى يعاد إرساله من تيليجرام بدون رفع جديد."""
    AUDIO_FILE_IDS[normalized_query(query)] = file_id
    AUDIO_FILE_IDS_PATH.write_text(
        json.dumps(AUDIO_FILE_IDS, ensure_ascii=False),
        encoding="utf-8",
    )


async def ensure_voice_clients_in_group(chat: Any, bot: Any) -> list[Client]:
    """العثور على الحسابات المساعدة داخل المجموعة وإدخال غير الموجود منها."""
    if not voice_clients:
        raise RuntimeError("لا توجد حسابات مساعدة متصلة")

    joined_clients: list[Client] = []
    missing_clients: list[Client] = []
    for client in voice_clients:
        user = voice_client_users.get(client)
        if user is None:
            try:
                user = await client.get_me()
                voice_client_users[client] = user
            except Exception as error:
                logger.warning("Cannot read assistant account: %s", error)
                missing_clients.append(client)
                continue

        try:
            await client.get_chat_member(chat.id, user.id)
            joined_clients.append(client)
            logger.info(
                "Assistant %s is already a member of group %s",
                f"@{user.username}" if user.username else user.id,
                chat.id,
            )
        except Exception:
            if chat.username:
                try:
                    await client.join_chat(chat.username)
                    joined_clients.append(client)
                except Exception:
                    missing_clients.append(client)
            else:
                missing_clients.append(client)

    invite_link: str | None = None
    if missing_clients:
        try:
            invite = await bot.create_chat_invite_link(
                chat_id=chat.id,
                name="voice assistants",
                member_limit=len(missing_clients),
            )
            invite_link = invite.invite_link
        except Exception as error:
            logger.warning(
                "Cannot create assistant invite link for %s. "
                "The bot must be an administrator with invite permission: %s",
                chat.id,
                error,
            )

        if invite_link:
            for client in missing_clients:
                try:
                    await client.join_chat(invite_link)
                    joined_clients.append(client)
                    user = voice_client_users.get(client)
                    logger.info(
                        "Assistant %s joined group %s",
                        f"@{user.username}" if user and user.username else user.id if user else "unknown",
                        chat.id,
                    )
                except Exception as error:
                    logger.warning("Assistant could not join group %s: %s", chat.id, error)

            try:
                await bot.revoke_chat_invite_link(
                    chat_id=chat.id,
                    invite_link=invite_link,
                )
            except Exception:
                logger.debug("Could not revoke temporary invite for %s", chat.id, exc_info=True)

    if not joined_clients:
        raise RuntimeError(
            "تعذر إدخال الحساب المساعد تلقائيا. اجعل البوت مشرفا مع صلاحية "
            "دعوة المستخدمين، ثم أعد المحاولة."
        )

    for client in joined_clients:
        for other_client, user in voice_client_users.items():
            if other_client is client:
                continue
            try:
                await client.add_chat_members(chat.id, user.id)
            except Exception:
                pass

    return joined_clients


async def auto_join_voice_clients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إدخال الحسابات المساعدة فور إضافة البوت إلى مجموعة."""
    membership = update.my_chat_member
    if membership is None or membership.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    if membership.new_chat_member.status not in {"member", "administrator", "creator"}:
        return
    if membership.old_chat_member.status in {"member", "administrator", "creator"}:
        return
    try:
        await ensure_voice_clients_in_group(membership.chat, context.bot)
    except Exception as error:
        logger.warning("Automatic assistant join failed for group %s: %s", membership.chat.id, error)


def convert_to_voice_wav(input_path: Path) -> Path:
    """تحويل الملف الصوتي إلى WAV/PCM مناسب للتشغيل داخل المكالمة."""
    output_path = input_path.with_suffix(".wav")

    if input_path.suffix.lower() == ".wav":
        return input_path
    if output_path.is_file() and output_path.stat().st_mtime >= input_path.stat().st_mtime:
        return output_path

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i", str(input_path),
                "-vn",
                "-acodec", "pcm_s16le",
                "-ar", "48000",
                "-ac", "2",
                "-threads", "0",
                "-loglevel", "error",
                "-nostdin",
                str(output_path),
            ],
            check=True,
            capture_output=True,
        )
        logger.info(f"✅ تم تحويل الملف لصيغة مناسبة للمكالمة: {output_path.name}")
        return output_path
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode("utf-8", errors="ignore")
        logger.error(f"❌ فشل تحويل الملف: {stderr[:300]}")
        return input_path


async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """التحقق من صلاحيات المستخدم"""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat or chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return False
    if is_bot_owner_user(user):
        return True
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return member.status in {"administrator", "creator"}
    except Exception:
        return False


async def is_group_admin(user_id: int, group_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """التحقق من أن المستخدم مشرف في المجموعة المرتبطة باللوحة."""
    if user_id in BOT_OWNER_IDS:
        return True
    try:
        member = await context.bot.get_chat_member(group_id, user_id)
        return member.status in {"administrator", "creator"}
    except Exception:
        return False


def warning_key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}:{user_id}"


def protection_target_label(target: Any) -> str:
    if target.username:
        return f"@{escape_markdown(target.username, version=2)}"
    return escape_markdown(target.first_name or "العضو", version=2)


def save_warnings() -> None:
    
    WARNINGS_PATH.write_text(
        json.dumps(WARNINGS, ensure_ascii=False),
        encoding="utf-8",
    )


async def get_protection_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Any | None:
    """الحصول على العضو المستهدف من الرد أو منشن تيليجرام الحقيقي أو اسم المستخدم."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat:
        return None

    target = message.reply_to_message.from_user if message.reply_to_message else None
    if target is None:
        for entity in message.entities or []:
            if entity.type == "text_mention" and entity.user is not None:
                target = entity.user
                break

    if target is None:
        username_match = re.search(r"@([A-Za-z0-9_]{3,32})", message.text or "")
        if username_match:
            username = username_match.group(1)
            try:
                resolved_chat = await context.bot.get_chat(f"@{username}")
                target = resolved_chat.username and resolved_chat
            except Exception:
                target = None

    if target is None:
        await message.reply_text("⚠️ رد على رسالة العضو أو استخدم منشن تيليجرام حقيقي أو @username.")
        return None

    user_obj = target if getattr(target, "id", None) is not None else None

    if user_obj is None or getattr(user_obj, "is_bot", False):
        await message.reply_text("⚠️ لا يمكن تطبيق الإجراء على بوت.")
        return None

    try:
        member = await context.bot.get_chat_member(chat.id, user_obj.id)
    except Exception:
        await message.reply_text("❌ لم أستطع العثور على هذا العضو في المجموعة.")
        return None
    if member.status in {"administrator", "creator"}:
        await message.reply_text("⚠️ لا يمكن تطبيق الإجراء على مشرف.")
        return None
    return user_obj


async def user_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض تفاصيل المستخدم داخل المجموعة: ايدي، اسم، عدد الرسائل، التحذيرات."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat or not message.text:
        return

    text = message.text.strip()
    match = re.match(r"^(ايدي|آيدي|/id|id)(?:\s+.*)?$", text, flags=re.IGNORECASE)
    if not match:
        return

    target = await get_protection_target(update, context)
    if target is None:
        return

    try:
        member = await context.bot.get_chat_member(chat.id, target.id)
    except Exception:
        await message.reply_text("❌ لم أستطع جلب بيانات هذا العضو.")
        return

    message_count = sum(
        sender_id == target.id
        for _, sender_id in tracked_messages.get(chat.id, ())
    )

    warnings_count = WARNINGS.get(warning_key(chat.id, target.id), 0)
    status_text = {
        "creator": "مالك المجموعة",
        "administrator": "مشرف",
        "member": "عضو",
        "restricted": "مقيّد",
        "left": "غادر",
        "kicked": "محظور",
    }.get(member.status, member.status)

    username_text = f"@{target.username}" if getattr(target, "username", None) else "—"
    first_name = getattr(target, "first_name", "") or "—"
    last_name = getattr(target, "last_name", "") or ""
    full_name = f"{first_name} {last_name}".strip() or "—"

    response = (
        "🧾 تفاصيل العضو\n"
        f"👤 الاسم: {full_name}\n"
        f"@ حساب: {username_text}\n"
        f"🆔 الايدي: {target.id}\n"
        f"📌 الحالة: {status_text}\n"
        f"💬 الرسائل المرصودة منذ تشغيل البوت: {message_count}\n"
        f"⚠️ التحذيرات: {warnings_count}\n"
        f"🏠 المجموعة: {chat.title or chat.id}"
    )
    await message.reply_text(response)


async def delete_my_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """مسح رسائل المستخدم الحالي داخل المجموعة."""
    message = update.effective_message
    if not message or not message.text:
        return

    text = message.text.strip()
    if text not in {"مسح رسائلي", "مسح رسائلي ", "مسح رسائلي  ", "مسح رسائلي "}:
        return

    user = message.from_user
    if user is None:
        return

    chat_messages = tracked_messages.get(message.chat.id, deque())
    message_ids = [
        message_id
        for message_id, sender_id in chat_messages
        if sender_id == user.id and message_id != message.message_id
    ]
    deleted = 0
    for start in range(0, len(message_ids), 100):
        batch = message_ids[start:start + 100]
        try:
            if await context.bot.delete_messages(message.chat.id, batch):
                deleted += len(batch)
        except Exception:
            logger.exception("Could not delete tracked messages for user %s", user.id)

    deleted_ids = set(message_ids)
    tracked_messages[message.chat.id] = deque(
        (message_id, sender_id)
        for message_id, sender_id in chat_messages
        if message_id not in deleted_ids
    )

    await message.reply_text(f"🧹 تم حذف {deleted} رسالة لك داخل هذه المجموعة.")


async def delete_group_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """حذف رسالة بالرد أو رسائل العضو المحدد للمشرفين."""
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat or chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    if not await is_admin(update, context):
        await message.reply_text("❌ هذا الأمر متاح لمالك المجموعة والمشرفين فقط.")
        return

    command = normalize_moderation_text(message.text or "")
    if command == "مسح":
        if not message.reply_to_message:
            await message.reply_text("⚠️ استخدم الأمر بالرد على الرسالة التي تريد حذفها.")
            return
        try:
            await context.bot.delete_messages(
                chat.id,
                [message.reply_to_message.message_id, message.message_id],
            )
        except Exception:
            logger.exception("Could not delete replied message in chat %s", chat.id)
        return

    if command != "مسح الكل":
        return

    target = await get_protection_target(update, context)
    if target is None:
        return
    message_ids = [
        message_id
        for message_id, sender_id in tracked_messages.get(chat.id, ())
        if sender_id == target.id
    ]
    message_ids.append(message.message_id)
    unique_message_ids = list(dict.fromkeys(message_ids))
    for start in range(0, len(unique_message_ids), 100):
        batch = unique_message_ids[start:start + 100]
        try:
            await context.bot.delete_messages(chat.id, batch)
        except Exception:
            logger.exception("Could not delete group messages in chat %s", chat.id)
    tracked_messages[chat.id] = deque(
        (message_id, sender_id)
        for message_id, sender_id in tracked_messages.get(chat.id, ())
        if sender_id != target.id
    )


async def owner_management(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat or not message.text:
        return
    text = message.text.strip()
    if not OWNER_COMMAND_RE.match(text):
        return

    if not is_bot_owner_user(user):
        raise ApplicationHandlerStop

    settings = chat_settings(chat.id)
    normalized = normalize_moderation_text(text)

    if normalized.startswith("الميزات"):
        lines = ["⚙️ الميزات:"]
        for feature, label in FEATURE_LABELS.items():
            enabled = feature_enabled(chat.id, feature)
            marker = "✅" if enabled else "❌"
            extra = ""
            if feature == "force_sub" and forced_channel(chat.id):
                extra = f" ({forced_channel(chat.id)})"
            lines.append(f"{marker} {label}{extra}")
        expires_at = parse_datetime(settings.get("expires_at"))
        lines.append("")
        lines.append(f"⏳ الاشتراك: {format_datetime(expires_at)}")
        lines.append("استخدم: ت م اسم الميزة")
        await message.reply_text("\n".join(lines))
        raise ApplicationHandlerStop

    if normalized.startswith("حالة الاشتراك"):
        expires_at = parse_datetime(settings.get("expires_at"))
        status = "مفعّل" if is_chat_active(chat.id) else "متوقف"
        await message.reply_text(f"🔐 حالة الاشتراك: {status}\n⏳ ينتهي: {format_datetime(expires_at)}")
        raise ApplicationHandlerStop

    if normalized.startswith("تاريخ"):
        expires_at = parse_datetime(settings.get("expires_at"))
        if expires_at is None:
            await message.reply_text("⏳ لا يوجد اشتراك مفعّل لهذه المجموعة حالياً.")
            raise ApplicationHandlerStop
        remaining = expires_at - now_utc()
        if remaining.total_seconds() <= 0:
            await message.reply_text("⚠️ انتهى اشتراك هذه المجموعة، ويجب تجديده.")
            raise ApplicationHandlerStop
        total_seconds = max(0, int(remaining.total_seconds()))
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        await message.reply_text(
            f"🗓️ تاريخ انتهاء الاشتراك: {format_datetime(expires_at)}\n"
            f"⏳ باقي: {days} يوم، {hours} ساعة، {minutes} دقيقة"
        )
        raise ApplicationHandlerStop

    if normalized.startswith("تفعيل"):
        current_plan = str(settings.get("plan") or "month")
        renew = "تجديد" in normalized
        if renew and not has_subscription_plan(text):
            await message.reply_text("⚠️ استخدم: تفعيل تجديد اسبوع أو تفعيل تجديد شهر")
            raise ApplicationHandlerStop
        plan, duration = subscription_plan_duration(text, fallback=current_plan)
        current_expiry = parse_datetime(settings.get("expires_at"))
        base_time = max(now_utc(), current_expiry) if renew and current_expiry else now_utc()
        expires_at = base_time + duration
        settings["expires_at"] = expires_at.isoformat()
        settings["plan"] = plan
        settings["activated_by"] = user.id
        settings["activated_at"] = now_utc().isoformat()
        save_settings()
        action = "تجديد" if renew else "تفعيل"
        await message.reply_text(
            f"✅ تم {action} البوت بنجاح.\n"
            f"📦 النوع: {subscription_plan_label(plan)}\n"
            f"⏳ ينتهي: {format_datetime(expires_at)}"
        )
        raise ApplicationHandlerStop

    if normalized.startswith("الغاء تفعيل"):
        settings.pop("expires_at", None)
        settings.pop("activated_by", None)
        settings.pop("activated_at", None)
        save_settings()
        await message.reply_text("⛔️ تم إيقاف اشتراك البوت لهذه المحادثة.")
        raise ApplicationHandlerStop

    if normalized.startswith("ت م"):
        feature = feature_from_text(text[3:].strip())
        if feature is None:
            await message.reply_text("⚠️ اكتب اسم الميزة مثل: يوت، شغل، العاب، حماية، اشتراك.")
            raise ApplicationHandlerStop
        if feature == "force_sub" and not forced_channel(chat.id) and not feature_enabled(chat.id, feature):
            await message.reply_text("⚠️ قبل تفعيل الاشتراك الإجباري استخدم: اشتراك اجباري @channel")
            raise ApplicationHandlerStop
        features = settings["features"]
        features[feature] = not bool(features.get(feature, False))
        save_settings()
        state = "تفعيل" if features[feature] else "تعطيل"
        await message.reply_text(f"✅ تم {state}: {FEATURE_LABELS[feature]}")
        raise ApplicationHandlerStop

    if normalized.startswith("اشتراك اجباري"):
        channel = None
        match = re.search(r"@[\w\d_]{5,}", text)
        if match:
            channel = match.group(0)
        else:
            parts = text.split(maxsplit=2)
            if len(parts) >= 3:
                channel = parts[2].strip()
        if not channel:
            await message.reply_text("⚠️ ارسل الأمر بهذا الشكل: اشتراك اجباري @channel")
            raise ApplicationHandlerStop
        channel, channel_id, validation_error = await validate_forced_subscription_target(channel, context)
        if validation_error:
            await message.reply_text(f"⚠️ {validation_error}")
            raise ApplicationHandlerStop
        settings["forced_channel"] = channel
        if channel_id is not None:
            settings["forced_channel_id"] = channel_id
        settings["features"]["force_sub"] = True
        SUBSCRIPTION_CACHE.clear()
        save_settings()
        await message.reply_text(
            f"✅ تم تفعيل الاشتراك الإجباري على {forced_channel_label(channel)}\n"
            "راح يتم فحص كل مستخدم مباشرة عند استخدام البوت أو عند ضغط زر تحققت."
        )
        raise ApplicationHandlerStop

    if "اشتراك اجباري" in normalized:
        settings.pop("forced_channel", None)
        settings.pop("forced_channel_id", None)
        settings["features"]["force_sub"] = False
        SUBSCRIPTION_CACHE.clear()
        save_settings()
        await message.reply_text("✅ تم إلغاء الاشتراك الإجباري.")
        raise ApplicationHandlerStop


async def activation_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat or chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    if is_chat_active(chat.id):
        return
    text = message.text or ""
    if OWNER_COMMAND_RE.match(text.strip()) and is_bot_owner_user(update.effective_user):
        return
    if text and is_bot_command_text(text):
        await message.reply_text(ACTIVATION_REQUIRED_TEXT)
    raise ApplicationHandlerStop


async def forced_subscription_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    member_update = update.chat_member
    chat = update.effective_chat
    if member_update is None or chat is None:
        return
    user_id = member_update.new_chat_member.user.id
    status = member_update.new_chat_member.status
    username = f"@{chat.username}" if getattr(chat, "username", None) else None

    for group_id_text, settings in SETTINGS.items():
        if not isinstance(settings, dict):
            continue
        try:
            group_id = int(group_id_text)
        except ValueError:
            continue
        target_id = forced_channel_id(group_id)
        target_name = forced_channel(group_id)
        if target_id != chat.id and (not username or target_name != username):
            continue
        cache_key = (group_id, user_id, target_name or "")
        if status in {"left", "kicked"}:
            SUBSCRIPTION_CACHE[cache_key] = (time.monotonic() + MEMBERSHIP_CACHE_TTL, False)
        else:
            SUBSCRIPTION_CACHE[cache_key] = (time.monotonic() + MEMBERSHIP_CACHE_TTL, True)


async def forced_subscription_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if (
        not message
        or not user
        or not chat
        or chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}
        or not is_chat_active(chat.id)
        or not feature_enabled(chat.id, "force_sub")
        or not forced_channel(chat.id)
    ):
        return
    if OWNER_COMMAND_RE.match((message.text or "").strip()) and is_bot_owner_user(user):
        return
    if await is_privileged_in_chat(user.id, chat.id, context, user=user):
        return
    if await has_forced_subscription(user.id, chat.id, context):
        return

    channel = forced_channel(chat.id) or ""
    label = forced_channel_label(channel)
    await message.reply_text(
        f"🔐 يجب الاشتراك في {label} قبل استخدام البوت.\n\n"
        f"📎 اضغط هنا للدخول: {channel_join_url(channel)}"
    )
    raise ApplicationHandlerStop


async def callback_preflight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.message is None:
        return
    chat = query.message.chat
    if chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    if not is_chat_active(chat.id):
        await query.answer("⛔️ البوت غير مفعّل. تواصل مع مطوّري البوت.", show_alert=True)
        raise ApplicationHandlerStop
    if not feature_enabled(chat.id, "force_sub") or not forced_channel(chat.id):
        return
    if await is_privileged_in_chat(query.from_user.id, chat.id, context, user=query.from_user):
        return
    refresh = query.data == "force_sub:check"
    if await has_forced_subscription(query.from_user.id, chat.id, context, refresh=refresh):
        if refresh:
            await query.answer("✅ تم التحقق، تقدر تستخدم البوت الآن.", show_alert=True)
        return
    channel = forced_channel(chat.id) or ""
    label = forced_channel_label(channel)
    if refresh and query.message:
        try:
            await query.edit_message_text(
                f"🔐 يجب الاشتراك في {label} قبل استخدام البوت.\n\n"
                f"📎 الرابط: {channel_join_url(channel)}"
            )
        except Exception:
            pass
    await query.answer(f"🔐 اشترك في {label} أولاً.", show_alert=True)
    raise ApplicationHandlerStop


async def apply_warning_to_target(
    message: Any,
    context: ContextTypes.DEFAULT_TYPE,
    target: Any,
    prefix: str = "⚠️ تم تحذير",
) -> None:
    key = warning_key(message.chat.id, target.id)
    count = WARNINGS.get(key, 0) + 1
    WARNINGS[key] = count
    save_warnings()

    if count < 3:
        await message.reply_text(f"{prefix} {target.first_name}. التحذيرات: {count}/3")
        return

    try:
        await context.bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=target.id,
            permissions=ChatPermissions(can_send_messages=False),
        )
        await message.reply_text(
            f"『⛔️』 تم تقييد {target.first_name} ⚠️ بسبب مخالفة القوانين."
        )
    except Exception:
        logger.exception("Could not auto-mute user %s in chat %s", target.id, message.chat.id)
        await message.reply_text(
            f"⚠️ وصل {target.first_name} إلى 3 تحذيرات، لكن تعذر كتمه. تأكد من صلاحيات البوت."
        )


async def community_warn_vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat or not feature_enabled(chat.id, "protection"):
        return
    target = await get_protection_target(update, context)
    if target is None:
        return
    if target.id == user.id:
        await message.reply_text("⚠️ لا تستطيع تحذير نفسك.")
        return

    key = warning_key(chat.id, target.id)
    vote_state = WARN_VOTES.setdefault(key, {"voters": [], "updated_at": now_utc().isoformat()})
    voters = {int(voter_id) for voter_id in vote_state.get("voters", []) if str(voter_id).lstrip("-").isdigit()}
    voters.add(user.id)
    vote_state["voters"] = sorted(voters)
    vote_state["updated_at"] = now_utc().isoformat()
    save_warn_votes()

    if len(voters) < 5:
        await message.reply_text(f"🗳 تم تسجيل التحذير الجماعي: {len(voters)}/5")
        return

    WARN_VOTES.pop(key, None)
    save_warn_votes()
    await apply_warning_to_target(message, context, target, prefix="⚠️ اكتمل تحذير الأعضاء ضد")


async def mute_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not feature_enabled(message.chat.id, "protection") or not await is_admin(update, context):
        return
    target = await get_protection_target(update, context)
    if target is None:
        return
    try:
        await context.bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=target.id,
            permissions=ChatPermissions(can_send_messages=False),
        )
        await message.reply_text(
            f"『⛔️』 تم تقييد {target.first_name} ⚠️ بسبب مخالفة القوانين."
        )
    except Exception:
        logger.exception("Could not mute user %s in chat %s", target.id, message.chat.id)
        await message.reply_text("❌ لم أستطع كتم العضو. تأكد أن البوت مشرف ولديه صلاحية تقييد الأعضاء.")


async def unmute_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not feature_enabled(message.chat.id, "protection") or not await is_admin(update, context):
        return
    target = await get_protection_target(update, context)
    if target is None:
        return
    try:
        await context.bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=target.id,
            permissions=ChatPermissions.all_permissions(),
        )
        await message.reply_text(f"🔊 تم رفع الكتم عن {target.first_name}.")
    except Exception:
        logger.exception("Could not unmute user %s in chat %s", target.id, message.chat.id)
        await message.reply_text("❌ لم أستطع رفع الكتم. تأكد من صلاحيات البوت.")


async def warn_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not feature_enabled(message.chat.id, "protection"):
        return
    if not await is_admin(update, context):
        await community_warn_vote(update, context)
        return
    target = await get_protection_target(update, context)
    if target is None:
        return
    await apply_warning_to_target(message, context, target)


async def unwarn_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not feature_enabled(message.chat.id, "protection") or not await is_admin(update, context):
        return
    target = await get_protection_target(update, context)
    if target is None:
        return

    key = warning_key(message.chat.id, target.id)
    count = max(0, WARNINGS.get(key, 0) - 1)
    if count:
        WARNINGS[key] = count
    else:
        WARNINGS.pop(key, None)
    save_warnings()
    await message.reply_text(f"✅ تم رفع تحذير عن {target.first_name}. التحذيرات: {count}/3")


async def clear_warnings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not feature_enabled(message.chat.id, "protection") or not await is_admin(update, context):
        return
    target = await get_protection_target(update, context)
    if target is None:
        return
    WARNINGS.pop(warning_key(message.chat.id, target.id), None)
    save_warnings()
    await message.reply_text(f"✅ تم رفع كل التحذيرات عن {target.first_name}.")


async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """حذف الرسائل المسيئة من الأعضاء مع إبقاء رسائل المشرفين."""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat or not message.text:
        return
    if not feature_enabled(chat.id, "protection"):
        return
    if not BAD_WORDS_MATCHER.contains_bad_word(normalize_moderation_text(message.text)):
        return

    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status in {"administrator", "creator"}:
            return
        await message.delete()
        logger.info("Deleted a moderation match from user %s in chat %s", user.id, chat.id)
    except Exception:
        logger.exception("Could not moderate message in chat %s", chat.id)
        return

    raise ApplicationHandlerStop


async def track_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat or chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    tracked_messages.setdefault(chat.id, deque(maxlen=1000)).append((message.message_id, user.id))
    add_user_points(user, 1)


async def private_subscription_ok(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user or not PRIVATE_FORCED_CHANNEL:
        return True
    if bool(get_user_data(user).get("banned")):
        return False
    if is_bot_owner_user(user):
        return True
    try:
        member = await context.bot.get_chat_member(PRIVATE_FORCED_CHANNEL, user.id)
        return member.status not in {"left", "kicked"}
    except Exception:
        logger.warning("Could not verify private subscription for %s", user.id)
        return False


async def private_subscription_guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None or update.effective_chat.type != ChatType.PRIVATE:
        return
    if await private_subscription_ok(update, context):
        return
    message = update.effective_message
    if message:
        await message.reply_text(
            f"🔐 اشترك بالقناة أولاً حتى تستخدم البوت:\n{channel_join_url(PRIVATE_FORCED_CHANNEL)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 الاشتراك بالقناة", url=channel_join_url(PRIVATE_FORCED_CHANNEL))],
                [InlineKeyboardButton("✅ تحققت من الاشتراك", callback_data="private:check")],
            ]),
        )
    raise ApplicationHandlerStop


async def private_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user or message.chat.type != ChatType.PRIVATE:
        return
    add_user_points(user, 1)
    await message.reply_text(
        "🎵 أهلاً بك في بوت الموسيقى\n\nاختر من القائمة:",
        reply_markup=private_menu(),
    )


async def private_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data or not query.data.startswith("private:"):
        return
    try:
        await query.answer()
    except BadRequest:
        pass
    user = query.from_user
    action = query.data.split(":", 1)[1]

    async def reply_result(text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
        await context.bot.send_message(
            chat_id=query.message.chat_id if query.message else user.id,
            text=text,
            reply_markup=reply_markup,
        )

    if action == "check":
        if await private_subscription_ok(update, context):
            await reply_result("✅ تم التحقق من الاشتراك.", private_menu())
        else:
            await query.answer("❌ لم يتم العثور على اشتراكك بالقناة.", show_alert=True)
        return
    if not await private_subscription_ok(update, context):
        await query.answer("🔐 اشترك بالقناة أولاً.", show_alert=True)
        return
    if action in {"search", "artist", "album", "link"}:
        context.user_data["private_action"] = action
        labels = {"search": "🔎 اكتب اسم الأغنية:", "artist": "🎤 اكتب اسم الفنان:", "album": "💿 اكتب اسم الألبوم:", "link": "🔗 اكتب اسم الأغنية لإرسال رابطها:"}
        await reply_result(labels[action], InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ القائمة", callback_data="private:menu")]]))
        return
    if action == "quality":
        await reply_result(
            "🎚️ اختر الجودة:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("96 kbps", callback_data="private:quality_96"), InlineKeyboardButton("128 kbps", callback_data="private:quality_128")],
                [InlineKeyboardButton("192 kbps", callback_data="private:quality_192")],
            ]),
        )
        return
    if action.startswith("quality_"):
        context.user_data["quality"] = action.split("_", 1)[1]
        await reply_result(f"✅ تم اختيار جودة {context.user_data['quality']} kbps.", private_menu())
        return
    data = get_user_data(user)
    points = int(data.get("points", 0))
    level, level_label = user_level(points)
    if action == "menu":
        await reply_result("🎵 القائمة الرئيسية:", private_menu())
    elif action == "account":
        await reply_result(f"👤 حسابك\n🆔 {user.id}\n📛 {user.full_name}\n⭐ النقاط: {points}\n🏅 {level_label}", private_menu())
    elif action == "points":
        await reply_result(f"⭐ نقاطك: {points}\n🏅 {level_label}", private_menu())
    elif action == "levels":
        await reply_result(f"🏅 مستواك: {level}\nتحتاج {level * 100 - points} نقطة للمستوى التالي.", private_menu())
    elif action == "rewards":
        await reply_result("🎁 الجوائز تعتمد على النشاط. كل تفاعل مفيد يزيد نقاطك.", private_menu())
    elif action == "store":
        await reply_result(
            "🛒 متجر النقاط\n\n🎁 عضوية مميزة: 100 نقطة",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("شراء بـ 100 نقطة", callback_data="private:buy_vip")],
                [InlineKeyboardButton("⬅️ القائمة", callback_data="private:menu")],
            ]),
        )
    elif action == "buy_vip":
        if points < 100:
            await query.answer("❌ تحتاج 100 نقطة للشراء.", show_alert=True)
            return
        data["points"] = points - 100
        data["rewards"] = int(data.get("rewards", 0)) + 1
        save_user_data()
        await reply_result("✅ تم شراء العضوية المميزة. شكراً لنشاطك!", private_menu())
    elif action == "stats":
        total_messages = sum(int(item.get("messages", 0)) for item in USER_DATA.values())
        await reply_result(f"📊 إحصائيات البوت\n👥 المستخدمون: {len(USER_DATA)}\n💬 التفاعلات: {total_messages}", private_menu())
    elif action == "users":
        await reply_result(f"👥 عدد المستخدمين: {len(USER_DATA)}", private_menu())
    elif action == "quality":
        context.user_data["quality"] = "128"
        await reply_result("🎚️ الجودة الحالية: 128 kbps\nيمكن تغييرها لاحقاً من إعدادات البوت.", private_menu())


async def private_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user or message.chat.type != ChatType.PRIVATE or not message.text:
        return
    action = context.user_data.pop("private_action", None)
    if not action:
        return
    query = message.text.strip()
    data = add_user_points(user, 2)
    waiting_messages = {
        "search": "⏳ جاري البحث عن الأغنية وتجهيزها، انتظر قليلًا...",
        "album": "⏳ جاري البحث عن الألبوم وتجهيز أغانيه، انتظر قليلًا...",
        "artist": "⏳ جاري البحث عن أغاني الفنان وتجهيزها، انتظر قليلًا...",
        "link": "⏳ جاري تجهيز رابط الأغنية، انتظر قليلًا...",
    }
    status = await message.reply_text(
        waiting_messages.get(action, "⏳ جاري تجهيز طلبك، انتظر قليلًا...")
    )
    if action == "link":
        song = await search_song_async(query, False)
        url = youtube_entry_url(song) or f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
        await status.delete()
        await message.reply_text(f"🔗 رابط الأغنية:\n{url}", reply_markup=private_menu())
        return
    search_query = query if action == "search" else f"{query} {action}"
    song = await search_song_async(search_query, True)
    audio_path = await asyncio.to_thread(downloaded_audio, song)
    await status.edit_text("📤 جاري إرسال الأغنية الآن...")
    await message.reply_audio(audio=str(audio_path), caption=f"🎵 {song.get('title', query)}")
    await status.delete()
    await message.reply_text("✅ تم إرسال الأغنية.", reply_markup=private_menu())


async def group_user_shortcuts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user or not message.text:
        return
    command = normalize_moderation_text(message.text.strip())
    if command not in {"حسابي", "نقاطي", "مستواي", "جوائزي", "المتجر"}:
        return
    data = get_user_data(user)
    points = int(data.get("points", 0))
    level, level_label = user_level(points)
    if command == "حسابي":
        text = f"👤 حسابك\n🆔 {user.id}\n📛 {user.full_name}\n⭐ النقاط: {points}\n🏅 {level_label}"
    elif command == "نقاطي":
        text = f"⭐ نقاطك: {points}\n🏅 {level_label}"
    elif command == "مستواي":
        text = f"🏅 مستواك: {level}\nتحتاج {level * 100 - points} نقطة للمستوى التالي."
    elif command == "جوائزي":
        text = f"🎁 الجوائز المكتسبة: {int(data.get('rewards', 0))}"
    elif command == "المتجر":
        text = "🛒 متجر النقاط\n🎁 العضوية المميزة: 100 نقطة\nاستخدم المتجر من الخاص مع البوت."
    await message.reply_text(text)


async def send_download_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تنزيل الأغنية وإرسالها كملف صوتي."""
    message = update.effective_message
    if not message or not message.text:
        return
    if not feature_enabled(message.chat.id, "download"):
        return

    match = re.match(r"^يوت\s+(.+)$", message.text.strip(), flags=re.IGNORECASE)
    if not match:
        return
    
    query = match.group(1).strip()
    requester = message.from_user
    requester_name = (
        f"@{requester.username}"
        if requester and requester.username
        else (requester.first_name if requester else "غير معروف")
    )
    status = await message.reply_text(
        f"✨ الموسيقى قيد التجهيز، لا تستعجل 🎵\n👤 الطالب: {requester_name}"
    )

    try:
        cached_file_id = AUDIO_FILE_IDS.get(normalized_query(query))
        if cached_file_id:
            try:
                await message.reply_audio(audio=cached_file_id)
                await status.delete()
                await message.reply_text(
                    download_success_text({"title": query}, requester_name)
                )
                return
            except Exception:
                AUDIO_FILE_IDS.pop(normalized_query(query), None)

        song = await search_song_async(query, True)
        audio_path = await asyncio.to_thread(downloaded_audio, song)
        sent_audio = await message.reply_audio(audio=str(audio_path))
        if sent_audio.audio:
            await asyncio.to_thread(save_audio_file_id, query, sent_audio.audio.file_id)
        await status.delete()
        await message.reply_text(download_success_text(song, requester_name))
    except MusicServiceError:
        logger.exception("Music service request failed")
        try:
            await status.delete()
        except Exception:
            pass
        try:
            await message.reply_text("❌ تعذر تجهيز الأغنية حالياً. جرّب اسمًا آخر أو أعد المحاولة لاحقاً.")
        except BadRequest:
            await context.bot.send_message(
                chat_id=message.chat.id,
                text="❌ تعذر تجهيز الأغنية حالياً. جرّب اسمًا آخر أو أعد المحاولة لاحقاً.",
            )
    except Exception as error:
        logger.exception("Song search failed")
        try:
            await status.delete()
        except Exception:
            pass
        try:
            await message.reply_text("❌ تعذر إرسال الملف إلى Telegram. أعد المحاولة بعد قليل.")
        except BadRequest:
            await context.bot.send_message(
                chat_id=message.chat.id,
                text="❌ تعذر إرسال الملف إلى Telegram. أعد المحاولة بعد قليل.",
            )


async def show_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض أوامر البوت حسب صلاحية المستخدم."""
    message = update.effective_message
    if not message:
        return

    if await is_admin(update, context):
        command_lines = ["📋 أوامر المشرفين:", ""]
        if feature_enabled(message.chat.id, "download"):
            command_lines.append("يوت اسم الأغنية - تنزيل الأغنية كملف صوتي")
        if feature_enabled(message.chat.id, "voice"):
            command_lines.extend([
                "شغل اسم الأغنية - تشغيل الأغنية في المكالمة",
                "اوكف - إيقاف الأغنية مؤقتًا",
                "غني - استئناف تشغيل الأغنية",
                "تخطي - تخطي الأغنية",
                "توقف - إنهاء التشغيل",
                "/pause - إيقاف مؤقت",
                "/resume - استئناف التشغيل",
                "/skip - تخطي الأغنية",
                "/stop - إنهاء التشغيل",
                "/volume 50 - ضبط مستوى الصوت",
            ])
        command_lines.append("/clean - تنظيف ملفات الكاش")
        command_lines.extend([
            "مسح - حذف الرسالة بالرد عليها",
            "مسح الكل - حذف رسائل العضو المحدد بالرد أو المنشن",
        ])
        if feature_enabled(message.chat.id, "games"):
            command_lines.extend(["", "العاب أو /games - ألعاب جماعية وترفيهية"])
        if feature_enabled(message.chat.id, "protection"):
            command_lines.extend([
                "",
                "كتم - كتم العضو بالرد على رسالته",
                "رفع كتم - رفع الكتم",
                "تحذير - إضافة تحذير",
                "رفع تحذير - حذف تحذير واحد",
                "مسح تحذيرات - حذف كل التحذيرات",
                "الأعضاء: 5 ردود بكلمة تحذير تعطي العضو تحذيرًا رسميًا",
            ])
        commands = "\n".join(command_lines)
    else:
        command_lines = ["📋 الأوامر المتاحة للأعضاء:", ""]
        if feature_enabled(message.chat.id, "download"):
            command_lines.append("يوت اسم الأغنية - تنزيل الأغنية كملف صوتي")
        if feature_enabled(message.chat.id, "games"):
            command_lines.append("العاب - قائمة 10 ألعاب")
        if feature_enabled(message.chat.id, "protection"):
            command_lines.append("تحذير - بالرد على رسالة العضو، 5 أعضاء = تحذير رسمي")
        command_lines.extend([
            "حسابي - عرض حسابك ونقاطك",
            "نقاطي - عرض النقاط والمستوى",
            "مستواي - عرض المستوى والترقية",
            "جوائزي - عرض الجوائز المكتسبة",
            "المتجر - عرض متجر النقاط",
        ])
        command_lines.append("الاوامر - عرض قائمة الأوامر")
        commands = "\n".join(command_lines)
 
    await message.reply_text(commands)


async def play_song(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global voice_calls, voice_client
    message = update.effective_message
    
    if not message or not message.text:
        return
    if not feature_enabled(message.chat.id, "voice"):
        await message.reply_text(
            "⚠️ ميزة المكالمة الصوتية غير مفعّلة في هذه المجموعة.\n"
            "فعّلها أولًا بالأمر: ت م شغل"
        )
        return
    
    if not await is_admin(update, context):
        await message.reply_text("❌ أمر شغل متاح للمشرفين فقط.")
        return
    
    match = re.match(r"^شغل\s+(.+)$", message.text.strip(), flags=re.IGNORECASE)
    if not match:
        return
    
    if voice_client is None:
        error_message = voice_initialization_error or (
            "لم يتصل أي حساب مساعد. تأكد من API_ID وAPI_HASH وSESSION_STRINGS."
        )
        await message.reply_text(f"❌ لا يمكن تشغيل المكالمة حالياً.\n{error_message}")
        return

    query = match.group(1).strip()
    requester = message.from_user
    requester_name = (
        f"@{requester.username}"
        if requester and requester.username
        else (requester.first_name if requester else "غير معروف")
    )
    status = await message.reply_text(
        f"✨ الموسيقى قيد التجهيز، لا تستعجل 🎵\n👤 الطالب: {requester_name}"
    )

    try:
        info = await search_song_async(query, False)
        song_id = info.get("id") or ""
        cached_path = None
        if song_id:
            matches = list(CACHE_DIR.glob(f"{song_id}.*"))
            for path in matches:
                if path.suffix.lower() in {".mp3", ".m4a", ".webm", ".opus", ".wav"}:
                    cached_path = path
                    break

        if cached_path is None:
            download_query = (
                song_url
                if (song_url := youtube_entry_url(info))
                else query
            )
            song = await search_song_async(download_query, True)
            audio_path = await asyncio.to_thread(downloaded_audio, song)
        else:
            song = info
            audio_path = cached_path

        title = song.get("title", query)
        duration = format_song_duration(song.get("duration"))

        audio_path = await asyncio.to_thread(convert_to_voice_wav, Path(audio_path))

        group_id = message.chat.id
        existing_call = voice_calls_by_group.get(group_id)
        if existing_call is not None:
            try:
                await existing_call.stop()
            except Exception:
                pass
            voice_calls_by_group.pop(group_id, None)

        group_clients = await ensure_voice_clients_in_group(message.chat, context.bot)
        assigned_client = voice_clients_by_group.get(group_id)
        if assigned_client in group_clients and assigned_client.is_connected:
            clients = [assigned_client]
        else:
            clients = [
                client for client in group_clients
                if client.is_connected
            ]
        if not clients:
            raise RuntimeError(
                "تم العثور على الحساب المساعد ضمن الأعضاء، لكنه غير متصل بجلسة Pyrogram. "
                "تحقق من SESSION_STRINGS ثم أعد تشغيل البوت."
            )

        last_error: Exception | None = None
        started = False
        for client in clients:
            candidate_call = GroupCallFactory(client).get_file_group_call(
                input_filename=str(audio_path),
                play_on_repeat=False,
            )
            try:
                # تحميل المجموعة قبل محاولة الانضمام للمكالمة.
                await client.get_chat(message.chat.id)
                await candidate_call.start(message.chat.id)
                voice_client = client
                voice_calls = candidate_call
                voice_calls_by_group[group_id] = candidate_call
                voice_clients_by_group[group_id] = client
                started = True
                break
            except Exception as error:
                last_error = error
                try:
                    await candidate_call.stop()
                except Exception:
                    pass

        if not started:
            raise last_error or RuntimeError("تعذر تشغيل الحسابات المساعدة")

        try:
            await status.delete()
        except Exception:
            logger.warning("Could not delete voice preparation message")
        try:
            await message.reply_text(
                song_success_text(song, requester_name, audio_path)
            )
        except Exception:
            logger.warning("Voice started, but confirmation message could not be sent")
        return

    except MusicServiceError:
        logger.exception("Voice music service request failed")
        try:
            await status.edit_text("❌ خدمة الموسيقى غير متاحة حالياً. جرّب لاحقاً.")
        except Exception:
            logger.warning("Could not send YouTube auth error message")
    except ValueError:
        logger.exception("Voice song search failed")
        try:
            await status.edit_text("❌ لم يتم العثور على الأغنية.")
        except Exception:
            logger.warning("Could not send song search error message")
    except Exception as e:
        logger.exception("Voice playback failed")
        error_text = str(e)
        if "PEER_ID_INVALID" in error_text or "Peer id invalid" in error_text:
            error_text = "الحساب المساعد غير موجود في هذه المجموعة أو لم يتعرف عليها بعد."
        elif "GROUPCALL_INVALID" in error_text:
            error_text = "افتح مكالمة صوتية في المجموعة أولاً ثم أعد أمر شغل."
        try:
            await status.edit_text(f"❌ تعذر تشغيل الأغنية: {error_text[:150]}")
        except Exception:
            logger.warning("Could not send voice playback error message")
async def control_call(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """التحكم في المكالمة الصوتية (للمشرفين فقط)"""
    global voice_calls, voice_client
    message = update.effective_message

    if not message:
        return
    if not feature_enabled(message.chat.id, "voice"):
        return

    if not await is_admin(update, context):
        return

    group_id = message.chat.id
    group_client = voice_clients_by_group.get(group_id)
    group_call = voice_calls_by_group.get(group_id)
    if group_client is None or not group_client.is_connected:
        await message.reply_text("❌ الحساب المساعد غير متصل بالمكالمات الصوتية.")
        return

    if group_call is None:
        await message.reply_text("❌ لا توجد أغنية قيد التشغيل.")
        return

    try:
        controller = control_user_label(message.from_user)
        text = message.text.strip().casefold()

        command_aliases = {
            "تخطي": "skip",
            "غني": "resume",
            "توقف": "stop",
            "إيقاف": "pause",
            "ايقاف": "pause",
            "اوكف": "pause",
        }
        text = command_aliases.get(text, text)

        if text in {"/pause", "pause"}:
            group_call.pause_playout()
            await message.reply_text(f"⏸️ تم إيقاف التشغيل مؤقتاً بواسطة {controller}.")

        elif text in {"/resume", "resume"}:
            group_call.resume_playout()
            await message.reply_text(f"▶️ تم تشغيل الأغنية بواسطة {controller}.")

        elif text in {"/skip", "skip"}:
            await group_call.stop()
            voice_calls_by_group.pop(group_id, None)
            await message.reply_text(f"⏭️ تم تخطي الأغنية بواسطة {controller}.")

        elif text in {"/stop", "stop"}:
            await group_call.stop()
            voice_calls_by_group.pop(group_id, None)
            await message.reply_text(f"⏹️ تم إنهاء التشغيل بواسطة {controller}.")

        elif text.startswith("/volume"):
            if not context.args:
                await message.reply_text("ℹ️ استخدم: `/volume 50` لتغيير مستوى الصوت (0-100).")
                return
            try:
                volume = int(context.args[0])
                if 0 <= volume <= 100:
                    group_call.set_my_volume(volume)
                    await message.reply_text(f"🔊 تم ضبط الصوت على {volume}%.")
                else:
                    await message.reply_text("⚠️ القيمة يجب أن تكون بين 0 و 100.")
            except ValueError:
                await message.reply_text("⚠️ يرجى إدخال رقم صحيح (0-100).")

    except Exception as e:
        logger.exception("Voice control failed")
        await message.reply_text(f"❌ تعذر تنفيذ الأمر: {str(e)[:100]}")


async def voice_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لوحة التحكم بالمكالمة الصوتية في المجموعة."""
    message = update.effective_message
    if not message or not feature_enabled(message.chat.id, "voice") or not await is_admin(update, context):
        return

    try:
        await context.bot.send_message(
            chat_id=message.from_user.id,
            text="🎛 لوحة التحكم بالمكالمة الصوتية",
            reply_markup=build_voice_panel(message.chat.id),
        )
    except Exception:
        logger.info("Admin must start a private chat with the bot before using /panel")


async def handle_voice_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة أزرار لوحة التحكم في المكالمة."""
    query = update.callback_query
    if query is None or not query.data:
        return

    await query.answer()
    data = query.data
    parts = data.split(":")
    if len(parts) != 2 or parts[0] not in {"voice_pause", "voice_resume", "voice_skip"}:
        return
    try:
        group_id = int(parts[1])
    except ValueError:
        return

    if not feature_enabled(group_id, "voice"):
        await query.answer("❌ ميزة المكالمة متوقفة حالياً.", show_alert=True)
        return
    if not await is_privileged_in_chat(query.from_user.id, group_id, context, user=query.from_user):
        await query.answer("❌ هذا الأمر متاح لمشرفي المجموعة فقط.", show_alert=True)
        return
    
    group_call = voice_calls_by_group.get(group_id)
    if group_call is None:
        await query.edit_message_text("❌ لا توجد مكالمة صوتية نشطة.")
        return

    try:
        controller = control_user_label(query.from_user)
        if parts[0] == "voice_pause":
            group_call.pause_playout()
            await query.answer(f"⏸️ أوقف التشغيل مؤقتاً: {controller}")
            await query.edit_message_reply_markup(reply_markup=build_voice_panel(group_id))
        elif parts[0] == "voice_resume":
            group_call.resume_playout()
            await query.answer(f"▶️ شغّل الأغنية: {controller}")
            await query.edit_message_reply_markup(reply_markup=build_voice_panel(group_id))
        elif parts[0] == "voice_skip":
            await group_call.stop()
            voice_calls_by_group.pop(group_id, None)
            await query.answer(f"⏭️ تخطى الأغنية: {controller}")
            await query.edit_message_reply_markup(reply_markup=build_voice_panel(group_id))
    except Exception as e:
        logger.exception("Callback voice control failed")
        await query.answer(f"❌ تعذر تنفيذ الأمر: {str(e)[:100]}")
        await query.edit_message_reply_markup(reply_markup=build_voice_panel(group_id))


def games_menu() -> InlineKeyboardMarkup:
    games = [
        ("❌⭕ XO", "xo"),
        ("🔴🟡 4 بصف", "connect4"),
        ("✊ حجر ورق مقص", "rps"),
        ("🎲 نرد", "dice"),
        ("🪙 عملة", "coin"),
        ("🔢 خمن الرقم", "guess"),
        ("⬆️⬇️ أعلى أو أدنى", "higher"),
        ("🎰 سلوت", "slots"),
        ("❓ سؤال سريع", "quiz"),
        ("🔤 فك الكلمة", "word"),
    ]
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, callback_data=f"game:open:{name}") for label, name in games[index:index + 2]]
         for index in range(0, len(games), 2)]
    )


async def games_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message and feature_enabled(message.chat.id, "games"):
        await message.reply_text("🎮 اختار لعبة:", reply_markup=games_menu())


def game_back_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎮 الألعاب", callback_data="game:menu")]])


def xo_keyboard(board: list[str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(board[index] or "·", callback_data=f"game:xo:{index}") for index in range(row, row + 3)]
            for row in range(0, 9, 3)
        ]
    )


def board_winner(board: list[str], size: int = 3, connect: int = 3) -> str | None:
    lines = []
    for row in range(size):
        lines.append([row * size + column for column in range(size)])
    for column in range(size):
        lines.append([row * size + column for row in range(size)])
    lines.append([index * (size + 1) for index in range(size)])
    lines.append([(index + 1) * (size - 1) for index in range(size)])
    for line in lines:
        if len(line) >= connect and board[line[0]] and all(board[index] == board[line[0]] for index in line):
            return board[line[0]]
    return None


def new_xo_state() -> dict[str, Any]:
    return {"type": "xo", "board": [""] * 9, "turn": "X", "players": {}}


def game_text(name: str) -> str:
    return {
        "rps": "✊ حجر ورق مقص: اختار حركتك",
        "dice": "🎲 اضغط لرمي النرد",
        "coin": "🪙 اضغط لقلب العملة",
        "higher": "⬆️⬇️ الرقم الحالي: اضغط هل الرقم القادم أعلى أم أدنى؟",
        "slots": "🎰 اضغط لتشغيل السلوت",
        "quiz": "❓ سؤال سريع: ما عاصمة العراق؟",
    }.get(name, "🎮 اختار لعبة")


def game_buttons(name: str) -> InlineKeyboardMarkup:
    buttons: dict[str, list[list[InlineKeyboardButton]]] = {
        "rps": [[InlineKeyboardButton("✊", callback_data="game:rps:rock"), InlineKeyboardButton("✋", callback_data="game:rps:paper"), InlineKeyboardButton("✌️", callback_data="game:rps:scissors")]],
        "dice": [[InlineKeyboardButton("🎲 ارْمِ", callback_data="game:dice:roll")]],
        "coin": [[InlineKeyboardButton("🪙 اقلب", callback_data="game:coin:flip")]],
        "higher": [[InlineKeyboardButton("⬆️ أعلى", callback_data="game:higher:up"), InlineKeyboardButton("⬇️ أدنى", callback_data="game:higher:down")]],
        "slots": [[InlineKeyboardButton("🎰 تشغيل", callback_data="game:slots:spin")]],
        "quiz": [[InlineKeyboardButton("بغداد", callback_data="game:quiz:baghdad"), InlineKeyboardButton("دمشق", callback_data="game:quiz:damascus"), InlineKeyboardButton("القاهرة", callback_data="game:quiz:cairo")]],
    }
    buttons[name].append([InlineKeyboardButton("🎮 الألعاب", callback_data="game:menu")])
    return InlineKeyboardMarkup(buttons[name])


async def handle_game_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data:
        return
    if query.message is not None and not feature_enabled(query.message.chat_id, "games"):
        await query.answer("❌ ميزة الألعاب متوقفة حالياً.", show_alert=True)
        return
    parts = query.data.split(":")
    if parts[0] != "game":
        return
    await query.answer()
    if parts[1] == "menu":
        await query.edit_message_text("🎮 اختار لعبة:", reply_markup=games_menu())
        return
    if parts[1] != "open":
        return
    name = parts[2]
    key = (query.message.chat_id, query.message.message_id)
    if name == "xo":
        game_states[key] = new_xo_state()
        await query.edit_message_text("❌⭕ XO\nالدور: X", reply_markup=xo_keyboard(game_states[key]["board"]))
        return
    if name == "connect4":
        game_states[key] = {"type": "connect4", "board": [""] * 16, "turn": "🔴"}
        keyboard = [[InlineKeyboardButton("·", callback_data=f"game:c4:{index}") for index in range(4)] for _ in range(4)]
        await query.edit_message_text("🔴🟡 4 بصف\nالدور: 🔴", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    if name == "guess":
        game_states[key] = {"type": "guess", "number": random.randint(1, 10)}
        await query.edit_message_text("🔢 خمن الرقم من 1 إلى 10", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(str(number), callback_data=f"game:guess:{number}") for number in range(1, 6)], [InlineKeyboardButton(str(number), callback_data=f"game:guess:{number}") for number in range(6, 11)], [InlineKeyboardButton("🎮 الألعاب", callback_data="game:menu")]]))
        return
    if name == "word":
        word = random.choice(["موسيقى", "برمجة", "تليجرام", "اغنية", "كمبيوتر"])
        game_states[key] = {"type": "word", "word": word}
        shuffled = "".join(random.sample(word, len(word)))
        await query.edit_message_text(f"🔤 رتب حروف الكلمة:\n`{shuffled}`", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("إجابة", callback_data=f"game:word:{word}")], [InlineKeyboardButton("🎮 الألعاب", callback_data="game:menu")]]))
        return
    if name == "quiz":
        await query.edit_message_text(game_text(name), reply_markup=game_buttons(name))
        return
    await query.edit_message_text(game_text(name), reply_markup=game_buttons(name))


async def finish_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or not query.data or not query.data.startswith("game:"):
        return
    if query.message is not None and not feature_enabled(query.message.chat_id, "games"):
        await query.answer("❌ ميزة الألعاب متوقفة حالياً.", show_alert=True)
        return
    parts = query.data.split(":")
    if parts[1] in {"menu", "open"}:
        await handle_game_button(update, context)
        return
    key = (query.message.chat_id, query.message.message_id)
    state = game_states.get(key)
    if parts[1] == "xo" and state:
        index = int(parts[2])
        if state["board"][index]:
            return
        player_id = query.from_user.id
        players = state["players"]
        if player_id not in players:
            if len(players) >= 2:
                await query.answer("اللعبة ممتلئة", show_alert=True)
                return
            players[player_id] = "X" if "X" not in players.values() else "O"
        if players[player_id] != state["turn"]:
            await query.answer("انتظر دورك", show_alert=True)
            return
        state["board"][index] = state["turn"]
        winner = board_winner(state["board"])
        if winner or all(state["board"]):
            await query.edit_message_text(f"❌⭕ النتيجة: {winner or 'تعادل'}", reply_markup=game_back_button())
            game_states.pop(key, None)
        else:
            state["turn"] = "O" if state["turn"] == "X" else "X"
            await query.edit_message_reply_markup(reply_markup=xo_keyboard(state["board"]))
        return
    if parts[1] == "c4" and state:
        index = int(parts[2])
        column = index % 4
        open_slots = [row * 4 + column for row in range(3, -1, -1) if not state["board"][row * 4 + column]]
        if not open_slots:
            await query.answer("هذا العمود ممتلئ", show_alert=True)
            return
        state["board"][open_slots[0]] = state["turn"]
        winner = board_winner(state["board"], size=4, connect=4)
        keyboard = [[InlineKeyboardButton(state["board"][row * 4 + col] or "·", callback_data=f"game:c4:{col}") for col in range(4)] for row in range(4)]
        if winner or all(state["board"]):
            await query.edit_message_text(f"🔴🟡 النتيجة: {winner or 'تعادل'}", reply_markup=game_back_button())
            game_states.pop(key, None)
        else:
            state["turn"] = "🟡" if state["turn"] == "🔴" else "🔴"
            await query.edit_message_text(f"🔴🟡 4 بصف\nالدور: {state['turn']}", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    if parts[1] == "guess" and state:
        guess = int(parts[2])
        answer = state["number"]
        text = "🎉 صحيح!" if guess == answer else f"❌ خطأ، الرقم كان {answer}"
        await query.edit_message_text(text, reply_markup=game_back_button())
        game_states.pop(key, None)
        return
    if parts[1] == "word" and state:
        await query.edit_message_text("🎉 الكلمة هي: " + state["word"], reply_markup=game_back_button())
        game_states.pop(key, None)
        return
    if parts[1] == "rps":
        bot_move = random.choice(["rock", "paper", "scissors"])
        labels = {"rock": "✊", "paper": "✋", "scissors": "✌️"}
        await query.edit_message_text(f"أنت: {labels[parts[2]]}\nالبوت: {labels[bot_move]}", reply_markup=game_buttons("rps"))
        return
    if parts[1] == "dice":
        await query.edit_message_text(f"🎲 النتيجة: {random.randint(1, 6)}", reply_markup=game_buttons("dice"))
        return
    if parts[1] == "coin":
        await query.edit_message_text(f"🪙 {random.choice(['وجه', 'كتابة'])}", reply_markup=game_buttons("coin"))
        return
    if parts[1] == "higher":
        await query.edit_message_text(f"🎯 الرقم الجديد: {random.randint(1, 100)}", reply_markup=game_buttons("higher"))
        return
    if parts[1] == "slots":
        result = [random.choice(["🍒", "🍋", "⭐", "💎"]) for _ in range(3)]
        await query.edit_message_text(" | ".join(result) + ("\n🎉 فزت!" if len(set(result)) == 1 else ""), reply_markup=game_buttons("slots"))
        return
    if parts[1] == "quiz":
        await query.edit_message_text("✅ صحيح، عاصمة العراق بغداد!", reply_markup=game_buttons("quiz"))


async def clean_cache_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تنظيف ملفات الكاش (للمشرفين فقط)"""
    if not await is_admin(update, context):
        await update.message.reply_text("❌ هذا الأمر متاح فقط للمشرفين.")
        return
    
    deleted = 0
    for file in CACHE_DIR.glob("*"):
        if file.is_file() and file.suffix.lower() in {".mp3", ".m4a", ".webm", ".opus", ".wav"}:
            try:
                file.unlink()
                deleted += 1
            except Exception:
                pass
    
    await update.message.reply_text(f"🧹 تم حذف {deleted} ملف من الكاش.")


async def post_init(_: Application) -> None:
    """تهيئة البوت عند التشغيل"""
    global voice_client, voice_clients, voice_client_users, voice_initialization_error
    asyncio.create_task(periodic_cache_cleanup())
    if not (API_ID and API_HASH and configured_session_strings):
        logger.warning("⚠️ Voice calls disabled: missing API_ID, API_HASH, or session strings")
        return

    for index, session_string in enumerate(configured_session_strings, start=1):
        client = Client(
            f"voice_session_{index}",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=session_string,
        )
        try:
            await client.start()
            voice_clients.append(client)
            me = await client.get_me()
            voice_client_users[client] = me
            if voice_client is None:
                voice_client = client
            logger.info(f"✅ Voice client {index} started as: {me.first_name} (@{me.username})")
        except Exception as error:
            if "AUTH_KEY_DUPLICATED" in str(error):
                voice_initialization_error = (
                    "جلسة الحساب المساعد مستخدمة في تشغيل آخر. "
                    "أوقف البوت/الحساب المساعد من الجهاز أو السيرفر الآخر، "
                    "أو أنشئ SESSION_STRING جديدة ثم أعد التشغيل."
                )
            logger.exception(f"❌ Failed to start voice client {index}")
            try:
                await client.stop()
            except Exception:
                pass


async def post_shutdown(_: Application) -> None:
    """إيقاف البوت بشكل نظيف"""
    global voice_calls_by_group, voice_clients

    for group_call in voice_calls_by_group.values():
        try:
            await group_call.stop()
        except Exception:
            pass
    voice_calls_by_group.clear()
    
    for client in voice_clients:
        try:
            await client.stop()
        except Exception:
            pass
    
    logger.info("✅ Bot shut down cleanly")


def build_application() -> Application:
    """بناء التطبيق الرئيسي"""
    if not BOT_TOKEN:
        raise RuntimeError("❌ BOT_TOKEN غير موجود في ملف .env")
    
    telegram_request = HTTPXRequest(
        connection_pool_size=32,
        read_timeout=120,
        write_timeout=120,
        connect_timeout=30,
        pool_timeout=30,
        media_write_timeout=600,
    )
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(telegram_request)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(
        ChatMemberHandler(auto_join_voice_clients, ChatMemberHandler.MY_CHAT_MEMBER)
    )
    application.add_handler(
        ChatMemberHandler(forced_subscription_member_update, ChatMemberHandler.CHAT_MEMBER),
        group=-5,
    )
    application.add_handler(CommandHandler("start", private_start, filters=filters.ChatType.PRIVATE), group=-6)
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE, private_subscription_guard), group=-5)
    application.add_handler(CallbackQueryHandler(private_button, pattern=r"^private:"), group=-4)
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, private_text, block=False), group=-3)
    application.add_handler(MessageHandler(filters.TEXT, owner_management), group=-4)
    application.add_handler(MessageHandler(filters.ChatType.GROUPS, activation_guard), group=-3)
    application.add_handler(CallbackQueryHandler(callback_preflight), group=-3)
    application.add_handler(MessageHandler(filters.ChatType.GROUPS, forced_subscription_guard), group=-2)
    application.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, track_group_message), group=-10)
    application.add_handler(
        MessageHandler(
            filters.Regex(r"^(حسابي|نقاطي|مستواي|جوائزي|المتجر)$")
            & filters.ChatType.GROUPS
            & filters.TEXT,
            group_user_shortcuts,
            block=False,
        )
    )
    application.add_handler(CallbackQueryHandler(handle_voice_button, pattern=r"^voice_(pause|resume|skip):"))
    application.add_handler(CallbackQueryHandler(finish_game_callback, pattern=r"^game:"))
    
    # أوامر التحكم بالمكالمة (للمشرفين فقط)
    application.add_handler(CommandHandler(
        ["pause", "resume", "skip", "stop", "volume"],
        control_call
    ))
    application.add_handler(CommandHandler("panel", voice_panel))
    application.add_handler(CommandHandler("clean", clean_cache_command))
    application.add_handler(CommandHandler("mute", mute_member))
    application.add_handler(CommandHandler("unmute", unmute_member))
    application.add_handler(CommandHandler("warn", warn_member))
    application.add_handler(CommandHandler("unwarn", unwarn_member))
    application.add_handler(CommandHandler("clearwarnings", clear_warnings))
    application.add_handler(CommandHandler("id", user_info_command))
    application.add_handler(CommandHandler("games", games_command))
    application.add_handler(MessageHandler(
        filters.Regex(r"^(العاب|ألعاب)$") & filters.TEXT,
        games_command,
    ))

    application.add_handler(MessageHandler(
        filters.Regex(r"^كتم(?:\s+.+)?$") & filters.TEXT & filters.ChatType.GROUPS,
        mute_member,
    ))
    application.add_handler(MessageHandler(
        filters.Regex(r"^رفع كتم(?:\s+.+)?$") & filters.TEXT & filters.ChatType.GROUPS,
        unmute_member,
    ))
    application.add_handler(MessageHandler(
        filters.Regex(r"^تحذير(?:\s+.+)?$") & filters.TEXT & filters.ChatType.GROUPS,
        warn_member,
    ))
    application.add_handler(MessageHandler(
        filters.Regex(r"^رفع تحذير(?:\s+.+)?$") & filters.TEXT & filters.ChatType.GROUPS,
        unwarn_member,
    ))
    application.add_handler(MessageHandler(
        filters.Regex(r"^مسح تحذيرات(?:\s+.+)?$") & filters.TEXT & filters.ChatType.GROUPS,
        clear_warnings,
    ))
    application.add_handler(MessageHandler(
        filters.Regex(r"^(ايدي|آيدي|/id|id)(?:\s+.*)?$") & filters.TEXT & filters.ChatType.GROUPS,
        user_info_command,
    ))
    application.add_handler(MessageHandler(
        filters.Regex(r"^مسح رسائلي$") & filters.TEXT & filters.ChatType.GROUPS,
        delete_my_messages,
    ))
    application.add_handler(MessageHandler(
        filters.Regex(r"^(مسح|مسح الكل)$") & filters.TEXT & filters.ChatType.GROUPS,
        delete_group_messages,
    ))

    # عرض الأوامر حسب صلاحية المستخدم
    application.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS,
        moderate_message,
    ), group=-1)

    application.add_handler(MessageHandler(
        filters.Regex(r"^الاوامر$") & filters.TEXT,
        show_commands
    ))

    # أمر تشغيل الأغنية (للمشرفين فقط)
    application.add_handler(MessageHandler(
        filters.Regex(r"^شغل\s+.+$") & filters.TEXT,
        play_song
    ))

    # أوامر التحكم العربية المباشرة للمشرفين
    application.add_handler(MessageHandler(
        filters.Regex(r"^(تخطي|غني|توقف|إيقاف|ايقاف|اوكف)$") & filters.TEXT,
        control_call
    ))
    
    # أمر البحث عن الأغنية (لجميع المستخدمين)
    application.add_handler(MessageHandler(
        filters.Regex(r"^يوت\s+.+$") & filters.TEXT,
        send_download_audio,
        block=False,
    ))
    
    return application


if __name__ == "__main__":
    try:
        start_local_music_api()
        application = build_application()
        logger.info("🤖 Bot started successfully!")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("⏹️ Bot stopped by user")
    except Exception as e:
        logger.exception(f"❌ Bot crashed: {e}")
    finally:
        stop_local_music_api()
