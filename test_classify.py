"""Quick test: run the classifier against the test log without VOD."""

import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import analyzer


def main():
    result = analyzer.analyze(
        wcl_url="https://www.warcraftlogs.com/reports/Xw2KQ4t9hmPnZv6q",
        vod_url="https://www.twitch.tv/videos/2776241943",
    )

    if "error" in result:
        print(f"Error: {result['error']}")
        return

    print(f"Report: {result['report_title']}")
    print(f"Boss: {result['boss_name']}")
    print(f"Pulls: {result['pull_count']}")
    print()

    for pull in result["pulls"]:
        status = "Kill" if pull["is_kill"] else "Wipe"
        wipe_label = pull["wipe"]["cause_label"] if pull["wipe"] else "—"
        print(f"Pull #{pull['pull_number']}  {pull['duration_display']}  {pull['phase_reached']}  {status}  →  {wipe_label}")

        if pull["early_deaths"]:
            for d in pull["early_deaths"]:
                print(f"  [early] {d['timestamp_display']}  {d['player']:<20}  {d['cause_label']}")
                if d["vod_url"]:
                    print(f"          VOD: {d['vod_url']}")

        if pull["wipe"]:
            w = pull["wipe"]
            print(f"  [wipe]  {w['timestamp_display']}  {w['cause_label']}: {w['cause_description']}")
            if w["vod_url"]:
                print(f"          VOD: {w['vod_url']}")

        print()

    with open("test_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    print("Full results saved to test_results.json")


if __name__ == "__main__":
    main()
