"""Debug script: fetch raw WCL data from the test log and dump event structure."""

import json
import wcl


def main():
    token = wcl.get_token()
    code = wcl.parse_report_code("https://www.warcraftlogs.com/reports/Xw2KQ4t9hmPnZv6q")
    report = wcl.fetch_report(token, code)

    print(f"Report: {report.get('title')}")
    print(f"Start: {report['startTime']}, End: {report['endTime']}")

    actors = wcl.get_actors(report)
    abilities = wcl.get_abilities(report)

    lura_fights = wcl.get_fights_by_boss(report, "Midnight Falls")
    print(f"\nMidnight Falls fights: {len(lura_fights)}")
    for f in lura_fights:
        duration = (f["endTime"] - f["startTime"]) / 1000
        kill = "Kill" if f.get("kill") else "Wipe"
        print(f"  Fight {f['id']}: {duration:.0f}s ({kill}) phases={f.get('phases')}")

    if not lura_fights:
        print("No Lura fights found!")
        return

    # Fetch events for the FIRST Lura fight to inspect structure
    first = lura_fights[0]
    fight_ids = [first["id"]]
    print(f"\n--- Fetching events for fight {first['id']} ---")

    death_events = wcl.fetch_fight_events(token, code, fight_ids, "Deaths")
    damage_events = wcl.fetch_fight_events(token, code, fight_ids, "DamageTaken")
    buff_events = wcl.fetch_fight_events(token, code, fight_ids, "Buffs")
    debuff_events = wcl.fetch_fight_events(token, code, fight_ids, "Debuffs")

    print(f"  Deaths endpoint: {len(death_events)} events")
    print(f"  DamageTaken: {len(damage_events)} events")
    print(f"  Buffs: {len(buff_events)} events")
    print(f"  Debuffs: {len(debuff_events)} events")

    # Show death events and their structure
    print("\n--- Death events (type=death) ---")
    actual_deaths = [e for e in death_events if e.get("type") == "death"]
    print(f"  {len(actual_deaths)} actual deaths")
    for e in actual_deaths[:5]:
        target = actors.get(e.get("targetID", -1), {}).get("name", "?")
        ts = e["timestamp"] - first["startTime"]
        # Show ALL fields
        print(f"\n  {target} died at {ts/1000:.1f}s")
        print(f"  Full event: {json.dumps(e, indent=4)}")

    # Show death window events (non-death events from Deaths endpoint)
    print("\n--- Death window events (non-death, from Deaths endpoint) ---")
    window_events = [e for e in death_events if e.get("type") != "death"]
    event_types = set(e.get("type") for e in window_events)
    print(f"  Event types in death windows: {event_types}")
    for e in window_events[:5]:
        print(f"  {json.dumps(e, indent=4)}")

    # Unique damage ability names
    print("\n--- Unique DamageTaken abilities ---")
    ability_counts = {}
    for e in damage_events:
        aid = e.get("abilityGameID")
        if aid:
            name = abilities.get(aid, {}).get("name", f"unknown-{aid}")
            ability_counts[name] = ability_counts.get(name, 0) + 1
    for name, count in sorted(ability_counts.items(), key=lambda x: -x[1]):
        print(f"  {name}: {count}")

    # Unique buff ability names (looking for seed/dawn crystal)
    print("\n--- Unique Buff abilities ---")
    buff_counts = {}
    for e in buff_events:
        aid = e.get("abilityGameID")
        if aid:
            name = abilities.get(aid, {}).get("name", f"unknown-{aid}")
            buff_counts[name] = buff_counts.get(name, 0) + 1
    for name, count in sorted(buff_counts.items(), key=lambda x: -x[1]):
        print(f"  {name}: {count}")

    # Unique debuff ability names
    print("\n--- Unique Debuff abilities ---")
    debuff_counts = {}
    for e in debuff_events:
        aid = e.get("abilityGameID")
        if aid:
            name = abilities.get(aid, {}).get("name", f"unknown-{aid}")
            debuff_counts[name] = debuff_counts.get(name, 0) + 1
    for name, count in sorted(debuff_counts.items(), key=lambda x: -x[1]):
        print(f"  {name}: {count}")

    # Now fetch ALL Lura fights to get a broader picture
    all_fight_ids = [f["id"] for f in lura_fights]
    print(f"\n--- Fetching deaths for ALL {len(lura_fights)} Lura fights ---")
    all_deaths = wcl.fetch_fight_events(token, code, all_fight_ids, "Deaths")
    all_actual_deaths = [e for e in all_deaths if e.get("type") == "death"]
    print(f"  Total death events: {len(all_actual_deaths)}")

    # Group deaths by fight and show killing abilities
    print("\n--- Deaths per fight with killing abilities ---")
    for fight in lura_fights:
        fight_deaths = [e for e in all_actual_deaths
                        if fight["startTime"] <= e["timestamp"] <= fight["endTime"]]
        duration = (fight["endTime"] - fight["startTime"]) / 1000
        kill = "Kill" if fight.get("kill") else "Wipe"
        print(f"\n  Fight {fight['id']} ({duration:.0f}s, {kill}): {len(fight_deaths)} deaths")
        for e in fight_deaths:
            target = actors.get(e.get("targetID", -1), {}).get("name", "?")
            ts = (e["timestamp"] - fight["startTime"]) / 1000
            kill_id = e.get("killingAbilityGameID") or e.get("ability", {}).get("gameID")
            kill_name = "?"
            if kill_id:
                kill_name = abilities.get(kill_id, {}).get("name", f"id:{kill_id}")
            elif "killerID" in e:
                killer = actors.get(e["killerID"], {}).get("name", f"id:{e['killerID']}")
                kill_name = f"killed by {killer}"
            print(f"    {ts:6.1f}s  {target:<20}  {kill_name}")

    # Save raw data for inspection
    with open("debug_events.json", "w", encoding="utf-8") as f:
        json.dump({
            "report_meta": {
                "title": report.get("title"),
                "start": report["startTime"],
                "end": report["endTime"],
            },
            "lura_fights": lura_fights,
            "first_fight_deaths_raw": death_events[:100],
            "first_fight_damage_sample": damage_events[:100],
            "first_fight_buffs_sample": buff_events[:100],
            "first_fight_debuffs_sample": debuff_events[:100],
            "abilities": {str(k): v for k, v in abilities.items()},
            "actors": {str(k): v for k, v in actors.items()},
        }, f, indent=2, default=str)
    print("\n\nRaw data saved to debug_events.json")


if __name__ == "__main__":
    main()
