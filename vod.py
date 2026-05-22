"""VOD integration — Twitch VOD discovery and timestamp syncing via yt-dlp."""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import yt_dlp


def parse_vod_url(url: str) -> tuple[str, str]:
    m = re.search(r"twitch\.tv/videos/(\d+)", url)
    if m:
        return "twitch", m.group(1)
    raise ValueError(f"Unsupported VOD URL format: {url}")


def twitch_vod_info(url: str) -> tuple[datetime, int]:
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
    ts = info.get("timestamp") or info.get("release_timestamp")
    if not ts:
        raise RuntimeError("Could not determine VOD start time from Twitch URL.")
    return datetime.fromtimestamp(ts, tz=timezone.utc), int(info.get("duration") or 0)


def get_vod_segments(vod_urls: list[str]) -> list[dict]:
    segments = []
    for url in vod_urls:
        platform, video_id = parse_vod_url(url)
        start, duration = twitch_vod_info(url)
        segments.append({
            "platform": platform,
            "video_id": video_id,
            "start": start,
            "end": start + timedelta(seconds=duration),
        })
    segments.sort(key=lambda s: s["start"])
    return segments


def discover_channel_vods(channel: str, report_start: datetime, report_end: datetime) -> list[dict]:
    ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "playlistend": 30}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        playlist = ydl.extract_info(f"https://www.twitch.tv/{channel}/videos", download=False)

    if not playlist or not playlist.get("entries"):
        raise RuntimeError(f"No VODs found for '{channel}'.")

    video_ids = []
    for entry in playlist["entries"]:
        if not entry:
            continue
        vid_id = entry.get("id", "").lstrip("v") or re.search(r"/videos/(\d+)", entry.get("url", "") or "")
        if vid_id:
            video_ids.append(vid_id if isinstance(vid_id, str) else vid_id.group(1))

    segments = []
    for vid_id in video_ids:
        url = f"https://www.twitch.tv/videos/{vid_id}"
        start, duration = twitch_vod_info(url)
        end = start + timedelta(seconds=duration)
        if end < report_start:
            break
        if start <= report_end and end >= report_start:
            segments.append({"platform": "twitch", "video_id": vid_id, "start": start, "end": end})

    if not segments:
        raise RuntimeError(f"No VODs on '{channel}' overlap the WCL report window.")

    segments.sort(key=lambda s: s["start"])
    return segments


def find_segment(segments: list[dict], event_time: datetime) -> Optional[dict]:
    for seg in segments:
        if seg["start"] <= event_time <= seg["end"]:
            return seg
    return None


def make_timestamp_url(platform: str, video_id: str, seconds: int) -> str:
    seconds = max(0, seconds)
    if platform == "twitch":
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"https://www.twitch.tv/videos/{video_id}?t={h}h{m}m{s}s"
    return ""


def fmt_hms(seconds: int) -> str:
    sign = "-" if seconds < 0 else ""
    h, rem = divmod(abs(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{sign}{h:02d}:{m:02d}:{s:02d}"


def fmt_mmss(ms: int) -> str:
    total_secs = ms // 1000
    m, s = divmod(total_secs, 60)
    return f"{m}:{s:02d}"
