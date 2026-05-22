"""Main analysis pipeline — ties together WCL, VOD, and boss classification."""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import wcl
import vod
import bosses
import bosses.midnight_falls  # registers the boss


def analyze(wcl_url: str, vod_url: str | None = None, channel: str | None = None, stream_delay_s: int = 0) -> dict:
    token = wcl.get_token()
    code = wcl.parse_report_code(wcl_url)
    report = wcl.fetch_report(token, code)
    actors = wcl.get_actors(report)
    abilities = wcl.get_abilities(report)

    report_start = wcl.report_start_utc(report)
    report_end = datetime.fromtimestamp(report["endTime"] / 1000, tz=timezone.utc)

    # VOD segments
    vod_segments = _get_vod_segments(vod_url, channel, report_start, report_end)

    # Find boss fights — for now, only Midnight Falls
    boss_name = "Midnight Falls"
    boss_config = bosses.get_boss(boss_name)
    if not boss_config:
        return {"error": f"No boss config registered for '{boss_name}'"}

    boss_fights = wcl.get_fights_by_boss(report, boss_name)
    if not boss_fights:
        return {"error": f"No {boss_name} fights found in this log"}

    # Fetch events — deaths are small enough to bulk-fetch, damage must be per-fight
    fight_ids = [f["id"] for f in boss_fights]
    death_events = wcl.fetch_fight_events(token, code, fight_ids, "Deaths")
    tank_ids = wcl.get_tank_ids(token, code, fight_ids)

    # Pre-fetch damage for wipe pulls in parallel (kills don't need damage classification)
    wipe_fights = [f for f in boss_fights if not f.get("kill")]
    damage_by_fight: dict[int, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(wcl.fetch_fight_events, token, code, [f["id"]], "DamageTaken"): f["id"]
            for f in wipe_fights
        }
        for future in as_completed(futures):
            fid = futures[future]
            damage_by_fight[fid] = future.result()

    # Classify each pull
    pulls = []
    for i, fight in enumerate(boss_fights):
        fight_start_ms = fight["startTime"]
        fight_end_ms = fight["endTime"]
        duration_ms = fight_end_ms - fight_start_ms
        is_kill = bool(fight.get("kill"))

        fight_deaths = [e for e in death_events if fight_start_ms <= e["timestamp"] <= fight_end_ms]
        fight_damage = damage_by_fight.get(fight["id"], [])

        deaths, wipe = boss_config.classify_pull(
            fight, fight_deaths, fight_damage, actors, abilities, tank_ids,
        )

        # Calculate VOD timestamps for each death
        death_list = []
        for d in deaths:
            death_time_utc = report_start + timedelta(milliseconds=d.timestamp_ms)
            seg = vod.find_segment(vod_segments, death_time_utc)
            vod_url_str = ""
            vod_time_str = ""
            if seg:
                vod_secs = int((death_time_utc - seg["start"]).total_seconds()) + stream_delay_s
                vod_url_str = vod.make_timestamp_url(seg["platform"], seg["video_id"], max(0, vod_secs - 5))
                vod_time_str = vod.fmt_hms(vod_secs)

            death_list.append({
                "player": d.player_name,
                "timestamp_display": vod.fmt_mmss(d.fight_relative_ms),
                "fight_relative_ms": d.fight_relative_ms,
                "cause_id": d.cause_id,
                "cause_label": d.cause_label,
                "cause_description": d.cause_description,
                "killing_ability": d.killing_ability,
                "death_order": d.death_order,
                "is_wipe_death": d.is_wipe_death,
                "vod_url": vod_url_str,
                "vod_time": vod_time_str,
            })

        # VOD timestamp for wipe
        wipe_data = None
        if wipe:
            wipe_time_utc = report_start + timedelta(milliseconds=fight_start_ms + wipe.timestamp_ms)
            seg = vod.find_segment(vod_segments, wipe_time_utc)
            wipe_vod_url = ""
            wipe_vod_time = ""
            if seg:
                wipe_secs = int((wipe_time_utc - seg["start"]).total_seconds()) + stream_delay_s
                wipe_vod_url = vod.make_timestamp_url(seg["platform"], seg["video_id"], max(0, wipe_secs - 5))
                wipe_vod_time = vod.fmt_hms(wipe_secs)

            wipe_data = {
                "cause_id": wipe.cause_id,
                "cause_label": wipe.cause_label,
                "cause_description": wipe.cause_description,
                "timestamp_display": vod.fmt_mmss(wipe.timestamp_ms),
                "vod_url": wipe_vod_url,
                "vod_time": wipe_vod_time,
            }

        # Split deaths into early (non-wipe) and wipe deaths
        early_deaths = [d for d in death_list if not d["is_wipe_death"]]
        wipe_deaths = [d for d in death_list if d["is_wipe_death"]]

        pulls.append({
            "pull_number": i + 1,
            "fight_id": fight["id"],
            "duration_ms": duration_ms,
            "duration_display": vod.fmt_mmss(duration_ms),
            "phase_reached": boss_config.get_phase(duration_ms),
            "is_kill": is_kill,
            "wipe": wipe_data,
            "early_deaths": early_deaths,
            "wipe_deaths": wipe_deaths,
            "total_deaths": len(death_list),
        })

    return {
        "report_title": report.get("title", code),
        "boss_name": boss_name,
        "pull_count": len(pulls),
        "pulls": pulls,
    }


def _get_vod_segments(vod_url: str | None, channel: str | None,
                      report_start: datetime, report_end: datetime) -> list[dict]:
    if vod_url:
        return vod.get_vod_segments([vod_url])
    if channel:
        return vod.discover_channel_vods(channel, report_start, report_end)
    default_channel = os.environ.get("TWITCH_CHANNEL")
    if default_channel:
        return vod.discover_channel_vods(default_channel, report_start, report_end)
    return []
