"""Generic boss/dungeon classifier — works for any encounter without boss-specific config.

Uses killing ability names directly from WCL death events. Detects universal
wipe patterns: mass one-shots, tank death cascades, called wipes, and attrition.
"""

from bosses import DeathInfo, WipeInfo

PRE_PULL_WINDOW_MS = 10_000
WIPE_CLUSTER_WINDOW_MS = 15_000
AMBIENT_PATTERNS = ["melee", "falling", "environment"]


def _is_ambient(ability_name: str) -> bool:
    lower = ability_name.lower()
    if not lower or lower == "unknown":
        return True
    return any(p in lower for p in AMBIENT_PATTERNS)


class GenericBoss:
    name = "__generic__"

    def get_phase(self, fight_duration_ms: int) -> str:
        return ""

    def classify_pull(
        self,
        fight: dict,
        death_events: list[dict],
        damage_events: list[dict],
        actors: dict[int, dict],
        abilities: dict[int, dict],
        tank_ids: set[int] | None = None,
        healer_ids: set[int] | None = None,
    ) -> tuple[list[DeathInfo], WipeInfo | None]:
        fight_start = fight["startTime"]
        fight_end = fight["endTime"]
        is_kill = bool(fight.get("kill"))
        tank_ids = tank_ids or set()

        fight_deaths = []
        for e in death_events:
            if e.get("type") != "death":
                continue
            if not (fight_start <= e["timestamp"] <= fight_end):
                continue
            tid = e.get("targetID", -1)
            if tid not in actors:
                continue

            rel_ms = e["timestamp"] - fight_start
            if rel_ms < PRE_PULL_WINDOW_MS:
                continue

            ability_game_id = e.get("killingAbilityGameID", 0)
            ability_name = abilities.get(ability_game_id, {}).get("name", "Unknown")

            fight_deaths.append({
                "player_name": actors[tid]["name"],
                "player_id": tid,
                "timestamp_ms": e["timestamp"],
                "fight_relative_ms": rel_ms,
                "ability_name": ability_name,
                "ability_id": ability_game_id,
            })

        fight_deaths.sort(key=lambda d: d["timestamp_ms"])
        for i, d in enumerate(fight_deaths):
            d["death_order"] = i + 1

        wipe = None
        wipe_death_ids: set[int] = set()
        if not is_kill and fight_deaths:
            wipe, wipe_death_ids = self._classify_wipe(fight_deaths, tank_ids)

        deaths = []
        for d in fight_deaths:
            label = f"Killed by {d['ability_name']}" if d["ability_name"] != "Unknown" else "Unknown Ability"
            deaths.append(DeathInfo(
                player_name=d["player_name"],
                player_id=d["player_id"],
                timestamp_ms=d["timestamp_ms"],
                fight_relative_ms=d["fight_relative_ms"],
                cause_id=d["ability_name"].lower().replace(" ", "_"),
                cause_label=label,
                cause_description=f"Killed by {d['ability_name']}",
                killing_ability=d["ability_name"],
                killing_ability_id=d["ability_id"],
                death_order=d["death_order"],
                is_wipe_death=d["death_order"] in wipe_death_ids,
            ))

        return deaths, wipe

    def _classify_wipe(
        self,
        fight_deaths: list[dict],
        tank_ids: set[int],
    ) -> tuple[WipeInfo, set[int]]:
        wipe_cluster = self._get_wipe_cluster(fight_deaths)
        wipe_death_ids = {d["death_order"] for d in wipe_cluster}
        wipe_time = wipe_cluster[0]["fight_relative_ms"] if wipe_cluster else fight_deaths[-1]["fight_relative_ms"]

        # Short pull with only ambient/unknown deaths = accidental pull
        if wipe_time < 60_000:
            non_ambient = [d for d in fight_deaths if not _is_ambient(d["ability_name"])]
            if not non_ambient:
                return WipeInfo("called_wipe", "Called Wipe", "Accidental pull or early reset", wipe_time), wipe_death_ids

        # Mass one-shot: 3+ die to same ability within 5s
        result = self._detect_mass_oneshot(wipe_cluster, wipe_time, wipe_death_ids)
        if result:
            return result

        # Tank death cascade: tank dies, 3+ follow within 10s
        result = self._detect_tank_cascade(wipe_cluster, wipe_death_ids, wipe_time, tank_ids)
        if result:
            return result

        # Called wipe: 3+ die to environmental/melee at fight end
        ambient_in_cluster = [d for d in wipe_cluster if _is_ambient(d["ability_name"])]
        if len(ambient_in_cluster) >= 3 and len(ambient_in_cluster) >= len(wipe_cluster) * 0.6:
            return WipeInfo("called_wipe", "Called Wipe", "Raid wiped — players died to environment", wipe_time), wipe_death_ids

        # Attrition: spread-out deaths, no dominant mechanic
        early_deaths = [d for d in fight_deaths if d["death_order"] not in wipe_death_ids]
        if len(early_deaths) >= 3:
            ability_counts = self._count_abilities(wipe_cluster)
            non_ambient = {k: v for k, v in ability_counts.items() if not _is_ambient(k)}
            cluster_size = max(len(wipe_cluster), 1)
            top_count = max(non_ambient.values(), default=0)
            if top_count / cluster_size < 0.3:
                return WipeInfo("attrition", "Too Many Deaths",
                                f"Too many individual deaths — raid could not recover ({len(fight_deaths)} total)",
                                wipe_time), wipe_death_ids

        # Fallback: most common ability in wipe cluster
        ability_counts = self._count_abilities(wipe_cluster)
        non_ambient = {k: v for k, v in ability_counts.items() if not _is_ambient(k)}
        if non_ambient:
            top_ability = max(non_ambient, key=non_ambient.get)
            count = non_ambient[top_ability]
            return WipeInfo(top_ability.lower().replace(" ", "_"),
                            f"Wiped to {top_ability}",
                            f"{top_ability} killed {count} player{'s' if count != 1 else ''} during the wipe",
                            wipe_time), wipe_death_ids

        return WipeInfo("unknown", "Unknown Wipe", "Could not determine wipe cause", wipe_time), wipe_death_ids

    def _detect_mass_oneshot(self, wipe_cluster, wipe_time, wipe_death_ids):
        ability_groups: dict[str, list[dict]] = {}
        for d in wipe_cluster:
            if _is_ambient(d["ability_name"]):
                continue
            ability_groups.setdefault(d["ability_name"], []).append(d)

        for ability, deaths in ability_groups.items():
            if len(deaths) < 3:
                continue
            times = sorted(d["fight_relative_ms"] for d in deaths)
            best = 0
            for i in range(len(times)):
                j = i
                while j < len(times) and times[j] - times[i] <= 5_000:
                    j += 1
                best = max(best, j - i)
            if best >= 3:
                return WipeInfo(ability.lower().replace(" ", "_"),
                                f"{ability}",
                                f"{ability} killed {len(deaths)} players simultaneously",
                                wipe_time), wipe_death_ids
        return None

    def _detect_tank_cascade(self, wipe_cluster, wipe_death_ids, wipe_time, tank_ids):
        if not tank_ids:
            return None
        for d in wipe_cluster:
            if d["player_id"] not in tank_ids:
                continue
            cascade = [x for x in wipe_cluster
                       if x["fight_relative_ms"] > d["fight_relative_ms"]
                       and x["fight_relative_ms"] <= d["fight_relative_ms"] + 15_000]
            if len(cascade) >= 3:
                return WipeInfo("tank_death", "Tank Death",
                                f"Tank ({d['player_name']}) died to {d['ability_name']}, causing a cascade wipe",
                                wipe_time), wipe_death_ids
        return None

    def _get_wipe_cluster(self, fight_deaths: list[dict]) -> list[dict]:
        if not fight_deaths:
            return []
        last_time = fight_deaths[-1]["fight_relative_ms"]
        return [d for d in fight_deaths if last_time - d["fight_relative_ms"] < WIPE_CLUSTER_WINDOW_MS]

    def _count_abilities(self, deaths: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in deaths:
            name = d["ability_name"]
            counts[name] = counts.get(name, 0) + 1
        return counts
