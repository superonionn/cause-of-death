"""Midnight Falls (Lura) — full phase death/wipe classification.

Classification uses the killingAbilityGameID from WCL death events, matched
against known mechanic ability names.  For wipe classification, the death
cluster mechanic breakdown determines the cause, with sub-classification
for Light's End (dawn crystal) based on what triggered it.
"""

from bosses import DeathInfo, WipeInfo, register_boss

# ── Phase timing (milliseconds from fight start) ──────────────────────────────

P1_END_MS = 190_000
INTERMISSION_END_MS = 230_000
P2_END_MS = 340_000
P3_END_MS = 500_000
ENRAGE_THRESHOLD_MS = 540_000

MEMORY_GAME_WINDOWS_MS = [
    (40_000, 60_000),
    (100_000, 120_000),
    (160_000, 180_000),
]

PRE_PULL_WINDOW_MS = 10_000

# ── Ability name → mechanic category mapping ────────────────────────────────

MECHANIC_PATTERNS: dict[str, list[str]] = {
    "glaive":             ["heaven's glaives"],
    "tank_buster":        ["heaven's lance"],
    "beam":               ["dark quasar"],
    "terminate":          ["terminate"],
    "dissonance":         ["dissonance"],
    "cosmic_fracture":    ["cosmic fracture"],
    "lights_end":         ["light's end"],
    "radiance":           ["radiance"],
    "naarus_lament":      ["naaru's lament"],
    "resonance":          ["resonance"],
    "darkwell":           ["the darkwell"],
    "starsplinter":       ["starsplinter"],
    "charged_core":       ["charged core", "core harvest"],
    "iris_of_oblivion":   ["iris of oblivion"],
    "overkill_current":   ["overkill current"],
    "criticality":        ["criticality"],
    "midnight":           ["midnight"],
    "dark_constellation": ["dark constellation"],
    "stellar_implosion":  ["stellar implosion"],
    "dark_archangel":     ["dark archangel"],
    "black_tide":         ["black tide"],
    "enrage":             ["heaven and hell", "heaven & hell", "midnight perpetual"],
}

AMBIENT_PATTERNS = [
    "shattered sky", "glimmering", "melee", "fel armor",
    "dark rune", "dimming", "impaled", "thunderous well",
    "tears of l'ura", "void swarm", "light siphon", "severed surge",
]

# ── Human-readable labels ───────────────────────────────────────────────────

DEATH_LABELS: dict[str, tuple[str, str]] = {
    "glaive":             ("Hit by Glaive", "Killed by Heaven's Glaives"),
    "tank_buster":        ("Tank Buster", "Killed by Heaven's Lance (tank buster)"),
    "beam":               ("Hit by Beam", "Killed by Dark Quasar"),
    "terminate":          ("Failed Interrupt", "Killed by an uninterrupted Terminate cast"),
    "dissonance":         ("Memory Game", "Killed by Dissonance from memory game failure"),
    "cosmic_fracture":    ("Crystal Failure", "Killed by Cosmic Fracture — crystal not killed/healed in time"),
    "lights_end":         ("Dawn Crystal Failure", "Killed by Light's End"),
    "radiance":           ("Crystal on Ground", "Killed by Radiance — crystal left on ground too long"),
    "naarus_lament":      ("Missed Soak", "Killed by Naaru's Lament — soak not covered"),
    "resonance":          ("Resonance", "Killed by Resonance"),
    "darkwell":           ("Center Circle", "Walked into The Darkwell"),
    "starsplinter":       ("Hit by Starsplinter", "Killed by Starsplinter"),
    "charged_core":       ("Hit by Basketball", "Killed by Charged Core"),
    "iris_of_oblivion":   ("Walked Outside", "Killed by Iris of Oblivion — walked outside the arena"),
    "overkill_current":   ("Galvanize Failure", "Killed by Overkill Current — not enough people in Galvanize"),
    "criticality":        ("Hit by Circle", "Killed by Criticality"),
    "midnight":           ("Out of Seed", "Killed by Midnight — outside seed too long"),
    "dark_constellation": ("Hit by Constellation", "Killed by Dark Constellation"),
    "stellar_implosion":  ("Missed Group Soak", "Killed by Stellar Implosion — group soak not covered"),
    "dark_archangel":     ("Dark Archangel", "Killed by Dark Archangel"),
    "black_tide":         ("Black Tide", "Killed by Black Tide"),
    "enrage":             ("Enrage", "Killed by boss enrage mechanic"),
    "ambient":            ("Ambient Damage", "Killed by passive/environmental damage during a wipe"),
    "unknown":            ("Unknown", "Could not determine cause of death"),
}

WIPE_LABELS: dict[str, tuple[str, str]] = {
    "terminate":                ("Missed Interrupt",
                                 "Failed to interrupt a Terminate cast — multiple players one-shot"),
    "lights_end":               ("Dawn Crystal Failure",
                                 "Dawn crystal mechanic was not handled correctly — Light's End killed the raid"),
    "lights_end_glaive":        ("Dawn Crystal: Glaive",
                                 "A glaive likely hit a crystal carrier or landed near a crystal on the ground"),
    "lights_end_memory":        ("Dawn Crystal: Memory Game",
                                 "Memory game hit occurred during crystal phase, triggering Light's End"),
    "lights_end_beam":          ("Dawn Crystal: Beam/Starsplinter",
                                 "A beam or Starsplinter hit the dawn crystal, triggering Light's End"),
    "lights_end_constellation": ("Dawn Crystal: Constellation",
                                 "A constellation hit the crystal carrier, triggering Light's End"),
    "lights_end_circle":        ("Crystal Hit by Circle",
                                 "A circle (Criticality) hit the dawn crystal — raid wiped"),
    "radiance":                 ("Crystal on Ground Too Long",
                                 "A crystal was left on the ground too long — Radiance killed the raid"),
    "cosmic_fracture":          ("Crystal Not Killed/Healed",
                                 "Midnight or Dusk crystal mechanic failed — Cosmic Fracture dot wiped the raid"),
    "naarus_lament":            ("Missed Soak",
                                 "Soak mechanic was not covered by enough players"),
    "dissonance":               ("Memory Game Failure",
                                 "Memory game input or positioning was wrong — Dissonance killed multiple players"),
    "overkill_current":         ("Galvanize Failure",
                                 "Not enough people stood in Galvanize — Overkill Current wiped the raid"),
    "stellar_implosion":        ("Missed Group Soak",
                                 "Group soak was not covered — Stellar Implosion wiped the raid"),
    "dark_archangel":           ("Crystal Not Pressed",
                                 "Dawn crystal was not pressed for Dark Archangel"),
    "tank_death":               ("Tank Death",
                                 "Tank died, causing a cascade wipe"),
    "starsplinter_stack":       ("Starsplinter Hit Stack",
                                 "Starsplinter hit the group — multiple players killed"),
    "enrage":                   ("Enrage",
                                 "Boss enraged — too many deaths over Phase 4, fight lasted past 9 minutes"),
    "called_wipe":              ("Called Wipe",
                                 "Raid leader called a wipe — players ran to center"),
    "attrition":                ("Too Many Deaths",
                                 "Too many individual deaths drained battle rezzes — raid could not recover"),
    "unknown":                  ("Unknown Wipe",
                                 "Could not determine wipe cause"),
}


def _categorize(ability_name: str) -> str:
    lower = ability_name.lower()
    for category, patterns in MECHANIC_PATTERNS.items():
        for p in patterns:
            if p in lower:
                return category
    for p in AMBIENT_PATTERNS:
        if p in lower:
            return "ambient"
    return "unknown"


def _is_ignorable_death(fight_relative_ms: int) -> bool:
    return fight_relative_ms < PRE_PULL_WINDOW_MS


def _in_memory_game_window(fight_relative_ms: int) -> bool:
    for start, end in MEMORY_GAME_WINDOWS_MS:
        if start <= fight_relative_ms <= end:
            return True
    return False


def _get_death_label(category: str) -> tuple[str, str]:
    return DEATH_LABELS.get(category, DEATH_LABELS["unknown"])


def _get_wipe_label(cause_id: str) -> tuple[str, str]:
    return WIPE_LABELS.get(cause_id, WIPE_LABELS["unknown"])


def _get_phase_at_time(fight_relative_ms: int) -> str:
    if fight_relative_ms < P1_END_MS:
        return "p1"
    if fight_relative_ms < INTERMISSION_END_MS:
        return "intermission"
    if fight_relative_ms < P2_END_MS:
        return "p2"
    if fight_relative_ms < P3_END_MS:
        return "p3"
    return "p4"


PHASE_DISPLAY = {
    "p1": "Phase 1",
    "intermission": "Intermission",
    "p2": "Phase 2",
    "p3": "Phase 3",
    "p4": "Phase 4",
}


# ── Main classification entry point ─────────────────────────────────────────

@register_boss("Midnight Falls")
class MidnightFalls:
    name = "Midnight Falls"

    def get_phase(self, fight_duration_ms: int) -> str:
        return PHASE_DISPLAY.get(_get_phase_at_time(fight_duration_ms), "Phase 4")

    def classify_pull(
        self,
        fight: dict,
        death_events: list[dict],
        damage_events: list[dict],
        actors: dict[int, dict],
        abilities: dict[int, dict],
        tank_ids: set[int] | None = None,
    ) -> tuple[list[DeathInfo], WipeInfo | None]:
        fight_start = fight["startTime"]
        fight_end = fight["endTime"]
        is_kill = bool(fight.get("kill"))

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
            ability_game_id = e.get("killingAbilityGameID", 0)
            ability_name = abilities.get(ability_game_id, {}).get("name", "Unknown")

            if _is_ignorable_death(rel_ms):
                continue

            category = _categorize(ability_name)
            label, desc = _get_death_label(category)

            if category == "ambient":
                label = f"Ambient ({ability_name})"
                desc = f"Killed by {ability_name} (passive/environmental damage)"

            fight_deaths.append({
                "player_name": actors[tid]["name"],
                "player_id": tid,
                "timestamp_ms": e["timestamp"],
                "fight_relative_ms": rel_ms,
                "category": category,
                "cause_label": label,
                "cause_description": desc,
                "killing_ability": ability_name,
                "killing_ability_id": ability_game_id,
            })

        fight_deaths.sort(key=lambda d: d["timestamp_ms"])
        for i, d in enumerate(fight_deaths):
            d["death_order"] = i + 1

        wipe = None
        wipe_death_ids = set()
        if not is_kill and fight_deaths:
            wipe, wipe_death_ids = self._classify_wipe(
                fight_deaths, damage_events, fight_start, abilities, tank_ids or set(),
            )

        deaths = []
        for d in fight_deaths:
            deaths.append(DeathInfo(
                player_name=d["player_name"],
                player_id=d["player_id"],
                timestamp_ms=d["timestamp_ms"],
                fight_relative_ms=d["fight_relative_ms"],
                cause_id=d["category"],
                cause_label=d["cause_label"],
                cause_description=d["cause_description"],
                killing_ability=d["killing_ability"],
                killing_ability_id=d["killing_ability_id"],
                death_order=d["death_order"],
                is_wipe_death=d["death_order"] in wipe_death_ids,
            ))

        return deaths, wipe

    # ── Wipe classification dispatcher ───────────────────────────────────────

    def _classify_wipe(
        self,
        fight_deaths: list[dict],
        damage_events: list[dict],
        fight_start: int,
        abilities: dict[int, dict],
        tank_ids: set[int],
    ) -> tuple[WipeInfo, set[int]]:
        wipe_cluster = self._get_wipe_cluster(fight_deaths)
        wipe_death_ids = {d["death_order"] for d in wipe_cluster}
        mechanic_counts = self._count_mechanics(wipe_cluster)
        wipe_time = wipe_cluster[0]["fight_relative_ms"] if wipe_cluster else fight_deaths[-1]["fight_relative_ms"]

        # Universal: galvanize failure always takes priority
        all_counts = self._count_mechanics(fight_deaths)
        if all_counts.get("overkill_current", 0) >= 1:
            label, desc = _get_wipe_label("overkill_current")
            return WipeInfo("overkill_current", label, desc, wipe_time), wipe_death_ids

        called = self._detect_called_wipe(
            fight_deaths, wipe_cluster, wipe_death_ids, mechanic_counts,
            wipe_time, damage_events, fight_start, abilities,
        )
        if called:
            return called

        phase = _get_phase_at_time(wipe_time)

        if phase == "p1":
            return self._classify_p1_wipe(wipe_cluster, wipe_death_ids, mechanic_counts, wipe_time, damage_events, fight_start, abilities, fight_deaths, tank_ids)
        if phase == "intermission":
            return self._classify_intermission_wipe(wipe_cluster, wipe_death_ids, mechanic_counts, wipe_time, damage_events, fight_start, abilities, fight_deaths, tank_ids)
        if phase == "p2":
            return self._classify_p2_wipe(wipe_cluster, wipe_death_ids, mechanic_counts, wipe_time, damage_events, fight_start, abilities, fight_deaths, tank_ids)
        if phase == "p3":
            return self._classify_p3_wipe(wipe_cluster, wipe_death_ids, mechanic_counts, wipe_time, damage_events, fight_start, abilities, fight_deaths, tank_ids)
        return self._classify_p4_wipe(wipe_cluster, wipe_death_ids, mechanic_counts, wipe_time, fight_deaths)

    # ── Phase 1 ──────────────────────────────────────────────────────────────

    def _classify_p1_wipe(self, wipe_cluster, wipe_death_ids, mechanic_counts, wipe_time, damage_events, fight_start, abilities, fight_deaths, tank_ids):
        has_lights_end = mechanic_counts.get("lights_end", 0) >= 3
        any_lights_end = mechanic_counts.get("lights_end", 0) >= 1
        has_terminate = mechanic_counts.get("terminate", 0) >= 3

        # Terminate first — a missed kick one-shotting half the raid is always the cause
        if has_terminate:
            terminate_deaths = [d for d in wipe_cluster if d["category"] == "terminate"]
            times = [d["fight_relative_ms"] for d in terminate_deaths]
            if max(times) - min(times) < 5000:
                label, desc = _get_wipe_label("terminate")
                return WipeInfo("terminate", label, f"{desc} ({len(terminate_deaths)} players killed)", wipe_time), wipe_death_ids

        # Glaive kills crystal holder → mass ambient deaths (LE doesn't always show as killing blow)
        glaive_deaths = [d for d in fight_deaths if d["category"] == "glaive" and d["player_id"] not in tank_ids]
        for gd in glaive_deaths:
            ambient_after = [
                d for d in fight_deaths
                if d["fight_relative_ms"] > gd["fight_relative_ms"]
                and d["fight_relative_ms"] <= gd["fight_relative_ms"] + 8_000
                and d["category"] in ("ambient", "unknown", "lights_end", "midnight", "naarus_lament", "radiance", "resonance")
            ]
            if len(ambient_after) >= 5:
                label, desc = _get_wipe_label("lights_end_glaive")
                return WipeInfo("lights_end_glaive", label,
                                f"Glaive killed crystal carrier ({gd['player_name']}), triggering a cascade wipe",
                                wipe_time), wipe_death_ids

        result = self._resolve_dissonance_vs_soak(wipe_cluster, mechanic_counts, wipe_time, wipe_death_ids)
        if result:
            return result

        if has_lights_end and has_terminate:
            first_le = min(d["fight_relative_ms"] for d in wipe_cluster if d["category"] == "lights_end")
            first_term = min(d["fight_relative_ms"] for d in wipe_cluster if d["category"] == "terminate")
            if first_term <= first_le + 1000:
                n = len([d for d in wipe_cluster if d["category"] == "terminate"])
                label, desc = _get_wipe_label("terminate")
                return WipeInfo("terminate", label,
                                f"{desc} — crystal holder killed by Terminate, triggering Light's End ({n} killed by Terminate)",
                                wipe_time), wipe_death_ids
            return self._classify_lights_end_p1(wipe_cluster, damage_events, fight_start, wipe_time, abilities), wipe_death_ids

        if has_lights_end:
            return self._classify_lights_end_p1(wipe_cluster, damage_events, fight_start, wipe_time, abilities), wipe_death_ids

        # Even 1 Light's End death with a clear sub-cause = crystal issue
        if any_lights_end:
            sub = self._classify_lights_end_p1(wipe_cluster, damage_events, fight_start, wipe_time, abilities)
            if sub.cause_id != "lights_end":
                return sub, wipe_death_ids

        if mechanic_counts.get("terminate", 0) >= 2:
            terminate_deaths = [d for d in wipe_cluster if d["category"] == "terminate"]
            times = [d["fight_relative_ms"] for d in terminate_deaths]
            if max(times) - min(times) < 5000:
                label, desc = _get_wipe_label("terminate")
                return WipeInfo("terminate", label, f"{desc} ({len(terminate_deaths)} players killed)", wipe_time), wipe_death_ids

        if mechanic_counts.get("cosmic_fracture", 0) >= 3:
            label, desc = _get_wipe_label("cosmic_fracture")
            return WipeInfo("cosmic_fracture", label, desc, wipe_time), wipe_death_ids

        if mechanic_counts.get("radiance", 0) >= 3:
            label, desc = _get_wipe_label("radiance")
            return WipeInfo("radiance", label, desc, wipe_time), wipe_death_ids

        tank = self._check_tank_death(wipe_cluster, wipe_death_ids, wipe_time, tank_ids, "Phase 1")
        if tank:
            return tank
        return self._fallback_wipe(mechanic_counts, wipe_time, wipe_death_ids, "Phase 1", fight_deaths)

    def _classify_lights_end_p1(self, wipe_cluster, damage_events, fight_start, wipe_time, abilities):
        lights_end_time = min(d["timestamp_ms"] for d in wipe_cluster if d["category"] == "lights_end")
        window_start = lights_end_time - 15_000

        glaive_hit = False
        for e in damage_events:
            if not (window_start <= e["timestamp"] <= lights_end_time):
                continue
            ability_name = abilities.get(e.get("abilityGameID"), {}).get("name", "")
            if _categorize(ability_name) == "glaive":
                glaive_hit = True
                break

        if glaive_hit:
            label, desc = _get_wipe_label("lights_end_glaive")
            return WipeInfo("lights_end_glaive", label, desc, wipe_time)

        if _in_memory_game_window(wipe_time):
            label, desc = _get_wipe_label("lights_end_memory")
            return WipeInfo("lights_end_memory", label, desc, wipe_time)

        label, desc = _get_wipe_label("lights_end")
        return WipeInfo("lights_end", label, desc, wipe_time)

    # ── Intermission ─────────────────────────────────────────────────────────

    def _classify_intermission_wipe(self, wipe_cluster, wipe_death_ids, mechanic_counts, wipe_time, damage_events, fight_start, abilities, fight_deaths, tank_ids):
        if mechanic_counts.get("starsplinter", 0) >= 3 and mechanic_counts.get("lights_end", 0) >= 1:
            label, desc = _get_wipe_label("lights_end_beam")
            return WipeInfo("lights_end_beam", label, desc, wipe_time), wipe_death_ids

        if mechanic_counts.get("lights_end", 0) >= 3:
            lights_end_time = min(d["timestamp_ms"] for d in wipe_cluster if d["category"] == "lights_end")
            window_start = lights_end_time - 10_000
            beam_or_star = False
            for e in damage_events:
                if not (window_start <= e["timestamp"] <= lights_end_time):
                    continue
                ability_name = abilities.get(e.get("abilityGameID"), {}).get("name", "")
                cat = _categorize(ability_name)
                if cat in ("beam", "starsplinter"):
                    beam_or_star = True
                    break
            if beam_or_star:
                label, desc = _get_wipe_label("lights_end_beam")
                return WipeInfo("lights_end_beam", label, desc, wipe_time), wipe_death_ids
            label, desc = _get_wipe_label("lights_end")
            return WipeInfo("lights_end", label, desc, wipe_time), wipe_death_ids

        if mechanic_counts.get("naarus_lament", 0) >= 2:
            label, desc = _get_wipe_label("naarus_lament")
            return WipeInfo("naarus_lament", label, desc, wipe_time), wipe_death_ids

        tank = self._check_tank_death(wipe_cluster, wipe_death_ids, wipe_time, tank_ids, "Intermission")
        if tank:
            return tank
        return self._fallback_wipe(mechanic_counts, wipe_time, wipe_death_ids, "Intermission", fight_deaths)

    # ── Phase 2 ──────────────────────────────────────────────────────────────

    def _classify_p2_wipe(self, wipe_cluster, wipe_death_ids, mechanic_counts, wipe_time, damage_events, fight_start, abilities, fight_deaths, tank_ids):
        # Criticality = circle hit crystal (kills everyone directly)
        if mechanic_counts.get("criticality", 0) >= 3:
            label, desc = _get_wipe_label("lights_end_circle")
            return WipeInfo("lights_end_circle", label, desc, wipe_time), wipe_death_ids

        if mechanic_counts.get("lights_end", 0) >= 3:
            lights_end_time = min(d["timestamp_ms"] for d in wipe_cluster if d["category"] == "lights_end")
            window_start = lights_end_time - 10_000
            has_criticality = False
            for e in damage_events:
                if not (window_start <= e["timestamp"] <= lights_end_time):
                    continue
                ability_name = abilities.get(e.get("abilityGameID"), {}).get("name", "")
                if "criticality" in ability_name.lower():
                    has_criticality = True
                    break
            if has_criticality:
                label, desc = _get_wipe_label("lights_end_circle")
                return WipeInfo("lights_end_circle", label, desc, wipe_time), wipe_death_ids
            label, desc = _get_wipe_label("lights_end_beam")
            return WipeInfo("lights_end_beam", label,
                            "A beam hit the dawn crystal in Phase 2, triggering Light's End",
                            wipe_time), wipe_death_ids

        if mechanic_counts.get("naarus_lament", 0) >= 2:
            label, desc = _get_wipe_label("naarus_lament")
            return WipeInfo("naarus_lament", label, desc, wipe_time), wipe_death_ids

        if mechanic_counts.get("radiance", 0) >= 3:
            label, desc = _get_wipe_label("radiance")
            return WipeInfo("radiance", label, desc, wipe_time), wipe_death_ids

        tank = self._check_tank_death(wipe_cluster, wipe_death_ids, wipe_time, tank_ids, "Phase 2")
        if tank:
            return tank
        return self._fallback_wipe(mechanic_counts, wipe_time, wipe_death_ids, "Phase 2", fight_deaths)

    # ── Phase 3 ──────────────────────────────────────────────────────────────

    def _classify_p3_wipe(self, wipe_cluster, wipe_death_ids, mechanic_counts, wipe_time, damage_events, fight_start, abilities, fight_deaths, tank_ids):
        # Constellation kills crystal holder → cascade (LE, midnight, naaru's lament, etc).
        # The trigger death may be inside or outside the wipe cluster.
        # Only match if the cascade is from crystal-failure mechanics (not dissonance/terminate).
        cascade_cats = {"lights_end", "midnight", "naarus_lament", "ambient", "unknown", "resonance", "radiance"}
        constellation_triggers = [
            d for d in fight_deaths
            if d["category"] == "dark_constellation"
            and d["player_id"] not in tank_ids
        ]
        for ct in constellation_triggers:
            all_after = [
                d for d in fight_deaths
                if d["fight_relative_ms"] > ct["fight_relative_ms"]
                and d["fight_relative_ms"] <= ct["fight_relative_ms"] + 10_000
                and d["category"] != "dark_constellation"
            ]
            deaths_after = [d for d in all_after if d["category"] in cascade_cats]
            if len(deaths_after) >= 3 and len(deaths_after) >= len(all_after) * 0.5:
                label, desc = _get_wipe_label("lights_end_constellation")
                return WipeInfo("lights_end_constellation", label,
                                f"Constellation hit crystal carrier ({ct['player_name']}), causing a cascade wipe",
                                wipe_time), wipe_death_ids

        if mechanic_counts.get("lights_end", 0) >= 3:
            label, desc = _get_wipe_label("lights_end")
            return WipeInfo("lights_end", label, desc, wipe_time), wipe_death_ids

        result = self._resolve_dissonance_vs_soak(wipe_cluster, mechanic_counts, wipe_time, wipe_death_ids)
        if result:
            return result

        if mechanic_counts.get("stellar_implosion", 0) >= 3:
            label, desc = _get_wipe_label("stellar_implosion")
            return WipeInfo("stellar_implosion", label, desc, wipe_time), wipe_death_ids

        if mechanic_counts.get("radiance", 0) >= 3:
            label, desc = _get_wipe_label("radiance")
            return WipeInfo("radiance", label, desc, wipe_time), wipe_death_ids

        da_count = mechanic_counts.get("dark_archangel", 0) + mechanic_counts.get("black_tide", 0)
        if da_count >= 3:
            label, desc = _get_wipe_label("dark_archangel")
            return WipeInfo("dark_archangel", label, desc, wipe_time), wipe_death_ids

        tank = self._check_tank_death(wipe_cluster, wipe_death_ids, wipe_time, tank_ids, "Phase 3")
        if tank:
            return tank
        return self._fallback_wipe(mechanic_counts, wipe_time, wipe_death_ids, "Phase 3", fight_deaths)

    # ── Phase 4 ──────────────────────────────────────────────────────────────

    def _classify_p4_wipe(self, wipe_cluster, wipe_death_ids, mechanic_counts, wipe_time, fight_deaths):
        # Starsplinter hitting the stack — check before enrage since it's the root cause
        if mechanic_counts.get("starsplinter", 0) >= 3:
            label, desc = _get_wipe_label("starsplinter_stack")
            return WipeInfo("starsplinter_stack", label, desc, wipe_time), wipe_death_ids

        all_counts = self._count_mechanics(fight_deaths)
        has_enrage_ability = all_counts.get("enrage", 0) >= 1
        last_death_ms = fight_deaths[-1]["fight_relative_ms"] if fight_deaths else 0
        if has_enrage_ability or last_death_ms >= ENRAGE_THRESHOLD_MS:
            label, desc = _get_wipe_label("enrage")
            return WipeInfo("enrage", label, desc, wipe_time), wipe_death_ids

        if mechanic_counts.get("naarus_lament", 0) >= 2:
            label, desc = _get_wipe_label("naarus_lament")
            return WipeInfo("naarus_lament", label, desc, wipe_time), wipe_death_ids

        if mechanic_counts.get("radiance", 0) >= 3:
            label, desc = _get_wipe_label("radiance")
            return WipeInfo("radiance", label, desc, wipe_time), wipe_death_ids

        return self._fallback_wipe(mechanic_counts, wipe_time, wipe_death_ids, "Phase 4", fight_deaths)

    # ── Called-wipe / attrition detection ───────────────────────────────

    def _detect_called_wipe(self, fight_deaths, wipe_cluster, wipe_death_ids, mechanic_counts,
                            wipe_time, damage_events, fight_start, abilities):
        # Called wipe: 3+ darkwell deaths = players running into center to die.
        # Exclude cascade effects (LE, midnight, etc) from comparison — those are
        # consequences of a crystal failure, not independent root causes.
        darkwell_count = mechanic_counts.get("darkwell", 0)
        if darkwell_count >= 3:
            cascade_exclude = {"darkwell", "ambient", "unknown", "lights_end", "midnight",
                               "naarus_lament", "radiance", "resonance"}
            non_dw = {k: v for k, v in mechanic_counts.items() if k not in cascade_exclude}
            top_non_dw = max(non_dw.values(), default=0)
            if darkwell_count > top_non_dw:
                first_dw_ms = min(d["fight_relative_ms"] for d in fight_deaths if d["category"] == "darkwell")
                pre_dw = [d for d in fight_deaths
                          if d["fight_relative_ms"] < first_dw_ms
                          and d["category"] not in ("darkwell", "ambient", "unknown")]
                pre_dw_causes = {}
                for d in pre_dw:
                    pre_dw_causes[d["category"]] = pre_dw_causes.get(d["category"], 0) + 1
                terminate_pre = pre_dw_causes.get("terminate", 0)
                if terminate_pre >= 2:
                    label, desc = _get_wipe_label("terminate")
                    return WipeInfo("terminate", label,
                                    f"{desc} ({terminate_pre} players killed) — {darkwell_count} players ran to center",
                                    wipe_time), wipe_death_ids
                cause_str = ""
                if pre_dw_causes:
                    non_cascade = {k: v for k, v in pre_dw_causes.items() if k not in cascade_exclude}
                    if non_cascade:
                        top = max(non_cascade, key=non_cascade.get)
                        top_label = DEATH_LABELS.get(top, DEATH_LABELS["unknown"])[0]
                        cause_str = f" — {len(pre_dw)} early death(s) to {top_label}"
                label, desc = _get_wipe_label("attrition")
                return WipeInfo("attrition", label,
                                f"Early deaths drained battle rezzes{cause_str} — {darkwell_count} players ran to center",
                                wipe_time), wipe_death_ids

        early_deaths = [d for d in fight_deaths if d["death_order"] not in wipe_death_ids]
        if not early_deaths:
            return None

        # Missed interrupt: if 2+ Terminate deaths happened in a tight cluster
        # (same cast), classify as the kick — not attrition
        all_terminate = [d for d in fight_deaths if d["category"] == "terminate"]
        if len(all_terminate) >= 2:
            times = [d["fight_relative_ms"] for d in all_terminate]
            if max(times) - min(times) < 5000:
                label, desc = _get_wipe_label("terminate")
                return WipeInfo("terminate", label,
                                f"{desc} ({len(all_terminate)} players killed)",
                                wipe_time), wipe_death_ids

        # Crystal cascade: a trigger mechanic (glaive, beam, etc.) kills a crystal
        # holder, causing mass ambient deaths. The killing blow is often ambient
        # (Glimmering, Shattered Sky) rather than Light's End directly. Detect this
        # pattern and defer to the phase classifier.
        trigger_cats = {"glaive", "beam", "starsplinter", "criticality", "dark_constellation"}
        for td in wipe_cluster:
            if td["category"] in trigger_cats:
                ambient_after = [
                    d for d in wipe_cluster
                    if d["fight_relative_ms"] > td["fight_relative_ms"]
                    and d["fight_relative_ms"] <= td["fight_relative_ms"] + 8_000
                    and d["category"] in ("ambient", "unknown", "lights_end", "midnight",
                                          "naarus_lament", "radiance", "resonance")
                ]
                if len(ambient_after) >= 5:
                    return None

        if mechanic_counts.get("lights_end", 0) >= 1:
            if any(d["category"] in trigger_cats for d in wipe_cluster):
                return None
            le_deaths = [d for d in wipe_cluster if d["category"] == "lights_end"]
            if le_deaths:
                first_le_ms = min(d["fight_relative_ms"] for d in le_deaths)
                if any(d["category"] in trigger_cats and d["fight_relative_ms"] <= first_le_ms + 2000
                       for d in fight_deaths):
                    return None
                le_time = min(d["timestamp_ms"] for d in le_deaths)
                window_start = le_time - 10_000
                for e in damage_events:
                    if window_start <= e["timestamp"] <= le_time:
                        aname = abilities.get(e.get("abilityGameID"), {}).get("name", "")
                        cat = _categorize(aname)
                        if cat in trigger_cats:
                            return None

        # P4 enrage fights should be classified by the phase classifier, not as attrition
        phase = _get_phase_at_time(wipe_time)
        if phase == "p4":
            last_death_ms = fight_deaths[-1]["fight_relative_ms"] if fight_deaths else 0
            if last_death_ms >= ENRAGE_THRESHOLD_MS:
                return None

        # Standard attrition: multiple diverse early deaths + no dominant mechanic in wipe cluster
        if len(early_deaths) < 2:
            return None

        non_ambient = {k: v for k, v in mechanic_counts.items() if k not in ("ambient", "unknown")}
        cluster_size = max(len(wipe_cluster), 1)
        top_count = max(non_ambient.values(), default=0)
        dominant_fraction = top_count / cluster_size

        if dominant_fraction >= 0.3:
            return None

        label, desc = _get_wipe_label("attrition")

        early_causes = {}
        for d in early_deaths:
            if d["category"] not in ("ambient", "unknown"):
                early_causes[d["category"]] = early_causes.get(d["category"], 0) + 1

        if early_causes:
            top = max(early_causes, key=early_causes.get)
            top_label = DEATH_LABELS.get(top, DEATH_LABELS["unknown"])[0]
            return WipeInfo("attrition", label,
                            f"Early deaths ({top_label}) depleted battle rezzes — raid could not recover ({len(fight_deaths)} total deaths)",
                            wipe_time), wipe_death_ids

        return WipeInfo("attrition", label,
                        f"{desc} ({len(fight_deaths)} total deaths across the fight)",
                        wipe_time), wipe_death_ids

    # ── Shared helpers ───────────────────────────────────────────────────────

    def _resolve_dissonance_vs_soak(self, wipe_cluster, mechanic_counts, wipe_time, wipe_death_ids):
        has_dissonance = mechanic_counts.get("dissonance", 0) >= 4
        has_soak = mechanic_counts.get("naarus_lament", 0) >= 2
        if has_dissonance and has_soak:
            first_dissonance = min(d["fight_relative_ms"] for d in wipe_cluster if d["category"] == "dissonance")
            first_soak = min(d["fight_relative_ms"] for d in wipe_cluster if d["category"] == "naarus_lament")
            if first_soak < first_dissonance:
                label, desc = _get_wipe_label("naarus_lament")
                return WipeInfo("naarus_lament", label, desc, wipe_time), wipe_death_ids
            label, desc = _get_wipe_label("dissonance")
            n = mechanic_counts["dissonance"]
            return WipeInfo("dissonance", label, f"{desc} ({n} players killed)", wipe_time), wipe_death_ids
        if has_dissonance:
            label, desc = _get_wipe_label("dissonance")
            n = mechanic_counts["dissonance"]
            return WipeInfo("dissonance", label, f"{desc} ({n} players killed)", wipe_time), wipe_death_ids
        if has_soak:
            label, desc = _get_wipe_label("naarus_lament")
            return WipeInfo("naarus_lament", label, desc, wipe_time), wipe_death_ids
        return None

    def _check_tank_death(self, wipe_cluster, wipe_death_ids, wipe_time, tank_ids, phase_name):
        if not tank_ids:
            return None
        if any(d["category"] == "lights_end" for d in wipe_cluster):
            return None
        for d in wipe_cluster:
            if d["player_id"] in tank_ids and d["category"] not in ("darkwell", "terminate"):
                cascade = [x for x in wipe_cluster if x["fight_relative_ms"] > d["fight_relative_ms"]]
                if len(cascade) >= 2:
                    label, desc = _get_wipe_label("tank_death")
                    return WipeInfo("tank_death", label,
                                    f"Tank ({d['player_name']}) died in {phase_name}, causing a cascade wipe",
                                    wipe_time), wipe_death_ids
        return None

    def _fallback_wipe(self, mechanic_counts, wipe_time, wipe_death_ids, phase_name, fight_deaths=None):
        non_generic = {k: v for k, v in mechanic_counts.items() if k not in ("ambient", "unknown")}
        if non_generic:
            top = max(non_generic, key=non_generic.get)
            if top in WIPE_LABELS:
                label, desc = _get_wipe_label(top)
            else:
                label, desc = DEATH_LABELS.get(top, DEATH_LABELS["unknown"])
            return WipeInfo(top, label, desc, wipe_time), wipe_death_ids
        if fight_deaths and len(fight_deaths) >= 4:
            non_wipe = [d for d in fight_deaths if d["death_order"] not in wipe_death_ids]
            if len(non_wipe) >= 2:
                label, desc = _get_wipe_label("attrition")
                return WipeInfo("attrition", label,
                                f"{desc} ({len(fight_deaths)} total deaths across the fight)",
                                wipe_time), wipe_death_ids
        label, desc = _get_wipe_label("unknown")
        return WipeInfo("unknown", label, desc, wipe_time), wipe_death_ids

    def _get_wipe_cluster(self, fight_deaths: list[dict], window_ms: int = 15_000) -> list[dict]:
        if not fight_deaths:
            return []
        last_time = fight_deaths[-1]["fight_relative_ms"]
        return [d for d in fight_deaths if last_time - d["fight_relative_ms"] < window_ms]

    def _count_mechanics(self, deaths: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in deaths:
            cat = d["category"]
            counts[cat] = counts.get(cat, 0) + 1
        return counts
