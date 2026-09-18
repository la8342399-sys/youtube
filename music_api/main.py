import os
import logging
from pathlib import Path
from typing import Any

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

app = FastAPI(title="Music API", version="1.0.0")
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True, parents=True)
YTDLP_PROXY = os.getenv("YTDLP_PROXY", "").strip()


def yt_dlp_options(options: dict[str, Any]) -> dict[str, Any]:
    if YTDLP_PROXY:
        options["proxy"] = YTDLP_PROXY

    # التمويه كعميل تطبيق هاتف لتجاوز حظر يوتيوب وبدون كوكيز
    options["extractor_args"] = {
        "youtube": {
            "player_client": ["android", "ios", "mweb"],
        }
    }
    
    return options


def search_youtube(query: str) -> dict[str, Any] | None:
    ydl_opts = yt_dlp_options({
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "default_search": "ytsearch1",
        "extract_flat": False,
    })
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
    except Exception:
        logger.exception("YouTube search failed for query: %s", query)
        return None

    if not info:
        return None

    entries = info.get("entries") if isinstance(info, dict) else None
    if isinstance(entries, list) and entries:
        item = entries[0]
    elif isinstance(info, dict):
        item = info
    else:
        return None

    title = item.get("title") or "unknown"
    video_url = item.get("webpage_url") or item.get("url")
    if not video_url:
        return None

    return {
        "title": title,
        "url": video_url,
        "id": item.get("id"),
        "thumbnail": item.get("thumbnail"),
        "artist": item.get("artist") or item.get("uploader") or item.get("channel"),
        "uploader": item.get("uploader"),
        "duration": item.get("duration"),
        "abr": item.get("abr"),
    }


def download_audio_file(query: str) -> Path:
    result = search_youtube(query)
    if result is None:
        raise FileNotFoundError("لم يتم العثور على الأغنية")

    outtmpl = str(CACHE_DIR / "%(title)s.%(ext)s")
    ydl_opts = yt_dlp_options({
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}],
    })

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([result["url"]])
    except Exception as error:
        logger.exception("YouTube download failed for query: %s", query)
        raise RuntimeError("فشل تنزيل الملف من YouTube") from error

    matches = sorted(CACHE_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for file_path in matches:
        if file_path.is_file() and file_path.suffix.lower() in {".mp3", ".m4a", ".webm", ".ogg", ".wav"}:
            return file_path

    raise FileNotFoundError("تعذر تنزيل الملف الصوتي")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/search")
def search(q: str = Query(..., description="اسم الأغنية أو رابط YouTube")) -> dict[str, Any]:
    result = search_youtube(q)
    if result is None:
        raise HTTPException(status_code=404, detail="لم يتم العثور على الأغنية")
    return {
        "title": result["title"],
        "id": result["id"],
        "thumbnail": result["thumbnail"],
        "artist": result.get("artist"),
        "duration": result.get("duration"),
        "abr": result.get("abr"),
        "download_url": f"/download?q={result['title']}",
    }


@app.get("/download")
def download(q: str = Query(..., description="اسم الأغنية")) -> FileResponse:
    try:
        file_path = download_audio_file(q)
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="audio/mpeg",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
