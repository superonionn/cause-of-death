"""Session-based incremental analysis for live raid night usage.

Sessions cache WCL metadata and classified pulls. On refresh, only new
fights are fetched and classified, reducing a ~30s full analysis to ~1-2s.
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import wcl
import bosses
import bosses.midnight_falls  # registers the boss
import analyzer


MAX_SESSIONS = 50
TOKEN_MAX_AGE_S = 72_000  # re-fetch token after 20 hours

_sessions: dict[str, "Session"] = {}
_sessions_lock = threading.Lock()


@dataclass
class Session:
    session_id: str
    report_code: str
    token: str
    token_obtained_at: float
    report_meta: dict
    actors: dict[int, dict]
    abilities: dict[int, dict]
    tank_ids: set[int]
    healer_ids: set[int]
    boss_name: str
    boss_config: object
    vod_segments: list[dict]
    stream_delay_s: int
    channel: str | None
    vod_url: str | None
    report_start_utc: datetime
    processed_fight_ids: set[int] = field(default_factory=set)
    pulls: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.monotonic)
    last_refresh_at: float = field(default_factory=time.monotonic)
    refresh_lock: threading.Lock = field(default_factory=threading.Lock)


def _evict_if_needed():
    if len(_sessions) >= MAX_SESSIONS:
        oldest_key = min(_sessions, key=lambda k: _sessions[k].created_at)
        del _sessions[oldest_key]


def _ensure_token(session: Session) -> str:
    if time.monotonic() - session.token_obtained_at > TOKEN_MAX_AGE_S:
        session.token = wcl.get_token()
        session.token_obtained_at = time.monotonic()
    return session.token


def create_session(
    wcl_url: str,
    vod_url: str | None = None,
    channel: str | None = None,
    stream_delay_s: int = 0,
) -> dict:
    code = wcl.parse_report_code(wcl_url)

    with _sessions_lock:
        if code in _sessions:
            existing = _sessions[code]
            return _build_response(existing)

    token = wcl.get_token()
    token_time = time.monotonic()
    report = wcl.fetch_report(token, code)
    actors_map = wcl.get_actors(report)
    abilities_map = wcl.get_abilities(report)

    report_start = wcl.report_start_utc(report)
    report_end = datetime.fromtimestamp(report["endTime"] / 1000, tz=timezone.utc)

    vod_segments = analyzer.get_vod_segments(vod_url, channel, report_start, report_end)

    boss_name = "Midnight Falls"
    boss_config = bosses.get_boss(boss_name)
    if not boss_config:
        raise ValueError(f"No boss config registered for '{boss_name}'")

    boss_fights = analyzer.filter_boss_fights(report, boss_name)
    if not boss_fights:
        raise ValueError(f"No {boss_name} fights found in this log")

    fight_ids = [f["id"] for f in boss_fights]
    death_events = wcl.fetch_fight_events(token, code, fight_ids, "Deaths")
    tank_ids, healer_ids = wcl.get_role_ids(token, code, fight_ids)

    wipe_fights = [f for f in boss_fights if not f.get("kill")]
    damage_by_fight = analyzer.fetch_damage_parallel(token, code, wipe_fights)

    pulls = analyzer.classify_fights(
        boss_config, boss_fights, death_events, damage_by_fight,
        actors_map, abilities_map, tank_ids, healer_ids,
        vod_segments, report_start, stream_delay_s,
    )

    session = Session(
        session_id=code,
        report_code=code,
        token=token,
        token_obtained_at=token_time,
        report_meta=report,
        actors=actors_map,
        abilities=abilities_map,
        tank_ids=tank_ids,
        healer_ids=healer_ids,
        boss_name=boss_name,
        boss_config=boss_config,
        vod_segments=vod_segments,
        stream_delay_s=stream_delay_s,
        channel=channel,
        vod_url=vod_url,
        report_start_utc=report_start,
        processed_fight_ids=set(fight_ids),
        pulls=pulls,
    )

    with _sessions_lock:
        _evict_if_needed()
        _sessions[code] = session

    return _build_response(session)


def refresh_session(session_id: str) -> dict:
    with _sessions_lock:
        session = _sessions.get(session_id)
    if session is None:
        raise KeyError(f"Session '{session_id}' not found. Create a new session.")

    with session.refresh_lock:
        return _refresh_locked(session)


def _refresh_locked(session: Session) -> dict:
    token = _ensure_token(session)

    report = wcl.fetch_report(token, session.report_code)
    session.report_meta = report

    all_boss_fights = analyzer.filter_boss_fights(report, session.boss_name)
    new_fights = [f for f in all_boss_fights if f["id"] not in session.processed_fight_ids]

    if not new_fights:
        session.last_refresh_at = time.monotonic()
        return {
            "session_id": session.session_id,
            "new_pulls": 0,
            "total_pulls": len(session.pulls),
            "new_pull_data": [],
        }

    new_fight_ids = [f["id"] for f in new_fights]
    death_events = wcl.fetch_fight_events(token, session.report_code, new_fight_ids, "Deaths")

    new_wipe_fights = [f for f in new_fights if not f.get("kill")]
    damage_by_fight = analyzer.fetch_damage_parallel(token, session.report_code, new_wipe_fights)

    new_pulls = analyzer.classify_fights(
        session.boss_config, new_fights, death_events, damage_by_fight,
        session.actors, session.abilities, session.tank_ids, session.healer_ids,
        session.vod_segments, session.report_start_utc, session.stream_delay_s,
        pull_number_offset=len(session.pulls),
    )

    session.pulls.extend(new_pulls)
    session.processed_fight_ids.update(new_fight_ids)
    session.last_refresh_at = time.monotonic()

    return {
        "session_id": session.session_id,
        "new_pulls": len(new_pulls),
        "total_pulls": len(session.pulls),
        "new_pull_data": new_pulls,
    }


def get_session(session_id: str) -> dict:
    with _sessions_lock:
        session = _sessions.get(session_id)
    if session is None:
        raise KeyError(f"Session '{session_id}' not found. Create a new session.")
    return _build_response(session)


def _build_response(session: Session) -> dict:
    return {
        "session_id": session.session_id,
        "report_title": session.report_meta.get("title", session.report_code),
        "boss_name": session.boss_name,
        "pull_count": len(session.pulls),
        "pulls": session.pulls,
    }
