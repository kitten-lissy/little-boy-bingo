#!/usr/bin/env python3
"""Check Team 1's collection logs and kill counts, and record what's new since the bingo started.

Sources (all public):
- WikiSync (sync.runescape.wiki): collection log item IDs, for players using the WikiSync plugin
- TempleOSRS: collection log with item names, for players who sync with the Temple plugin
- Official OSRS hiscores: kill counts for everyone, including mobile players

The first run at or after START takes a baseline snapshot. Later runs compare against it,
so only items and kills gained during the event are reported. Output: data/status.json.
"""
import json
import re
import subprocess
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BASE = DATA / "baseline"
START = datetime(2026, 11, 20, 1, 0, tzinfo=timezone.utc)  # 8 pm EST Thu 19 Nov
UA = "little-boy-bingo-tracker"

PLAYERS = [
    {"name": "Kitten Lissy", "board": "Little"},
    {"name": "Primal Sin", "board": "Little"},
    {"name": "DemonWolfy", "board": "Little"},
    {"name": "Trobro12", "board": "Little", "note": "Mobile only: no plugins, hiscores only"},
    {"name": "SSora", "board": "Big"},
    {"name": "Lasrgatr", "board": "Big"},
    {"name": "Caffeine Guy", "board": "Big"},
]

PETS = (r"^(pet .*|baby mole|kalphite princess|prince black dragon|callisto cub|vet'ion jr\.?|venenatis spiderling|"
        r"scorpia's offspring|snakeling|hellpuppy|smoke devil|abyssal orphan|noon|vorki|olmlet|lil' zik|"
        r"tumeken's guardian|ikkle hydra|little nightmare|nexling|muphin|baron|butch|lil'viathan|wisp|sraracha|"
        r"beef|huberte|smol heredit|yami|dom|nid|moxi|scurrius|bran|tzrek-jad|jal-nib-rek|youngllef|"
        r"maggot marquess|soup|quetzin)$")

TILES = {
    "Little": {
        1: r"hallowfell|jar of stone|^noon$", 2: r"fire element staff crown|ice element staff crown",
        3: r"^magic fang$|trident of the seas|trident of the swamp",
        4: r"twisted bow|kodai insignia|elder maul|dragon claws|ancestral (hat|robe)|dinh's bulwark|dexterous prayer scroll|"
           r"arcane prayer scroll|twisted buckler|dragon hunter crossbow|osmumten's fang|lightbearer|elidinis' ward|"
           r"masori (mask|body|chaps)|tumeken's shadow|scythe of vitur|ghrazi rapier|sanguinesti staff|justiciar|"
           r"avernic defender hilt|cache of runes",
        5: r"basilisk jaw",
        6: r"bandos (chestplate|tassets|boots|hilt)|armadyl (helmet|chestplate|chainskirt|hilt|crossbow)|"
           r"saradomin (sword|hilt)|saradomin's light|staff of the dead|zamorakian spear|steam battlestaff|zamorak hilt",
        7: r"tome of earth|dragon hunter wand|hueycoatl hide",
        8: r"^(berserker|warrior|archer|seers) ring$",
        9: r"(blood|blue|eclipse) moon|eclipse atlatl|dual macuahuitl|blue moon spear",
        10: r"^(ahrim|dharok|guthan|karil|torag|verac)'s",
        11: r"tome of (fire|water|earth)",
        12: r"hill giant club|bryophyta's essence",
        13: r"^fire cape$",
        14: r"(draconic|skeletal|wyvern) visage",
        15: r"sarachnis cudgel|jar of eyes|^sraracha$",
        16: r"black tourmaline core|bandos boots",
        17: r"dragon warhammer|elder maul|bandos hilt|godsword shard",
        20: r"(odium|malediction) (shard|ward)",
        21: r"cow slippers",
        22: r"belle's folly",
        23: r"dragonbone necklace|vorkath's head",
        24: PETS,
        25: r"chugging barrel|potion storage",
    },
    "Big": {
        1: r"elder venator fang|crimson kisten|maggot marquess", 2: r"oathplate (helm|chest|legs)|soulflame horn",
        3: r"avernic treads|eye of ayak|mokhaiotl cloth",
        4: r"scythe of vitur|ghrazi rapier|sanguinesti staff|justiciar|avernic defender hilt|tumeken's shadow|"
           r"osmumten's fang|lightbearer|elidinis' ward|masori (mask|body|chaps)",
        5: r"imbued heart|eternal gem|dust battlestaff|mist battlestaff",
        6: r"virtus|(bellator|magus|ultor|venator) vestige|chromium ingot|executioner's axe head|leviathan's lure|"
           r"siren's staff|eye of the duke",
        7: r"torva|nihil horn|zaryte vambraces|ancient hilt|nexling",
        8: r"twisted ancestral colour kit|sanguine dust|holy ornament kit|sanguine ornament kit",
        9: r"craw's bow|thammaron's sceptre|viggora's chainmace|ancient effigy|ancient relic",
        10: r"ancestral (hat|robe)|justiciar|masori (mask|body|chaps)",
        11: r"crystal tool seed|zalcano shard|smolcano",
        12: r"venator shard",
        15: r"crystal weapon seed|crystal armour seed",
        16: r"(armadyl|bandos|saradomin|zamorak|ancient) hilt|godsword shard",
        17: r"^jar of ",
        19: r"ancient icon|(blood|ice|smoke|shadow) quartz",
        20: r"voidwaker (blade|hilt|gem)",
        21: r"cow slippers",
        22: r"sunfire fanatic|echo crystal|tonalztics|dizana's quiver|smol heredit",
        23: r"inquisitor's|(eldritch|harmonised|volatile) orb|parasitic egg",
        24: PETS,
        25: r"infernal cape",
    },
}
STARRED = {"Little": {2, 6, 8, 19}, "Big": {2, 7, 10, 11, 16, 20}}
# Tiles the tracker can't see (CAs, kill tasks, every-member tiles): marked done by hand only.
MANUAL = {"Little": {13}, "Big": {13, 14, 18, 25}}

QUESTS = {}
# Hiscore bosses whose kills count as effort toward each tile.
RAIDS = ["Chambers of Xeric", "Chambers of Xeric: Challenge Mode", "Theatre of Blood", "Theatre of Blood: Hard Mode", "Tombs of Amascut", "Tombs of Amascut: Expert Mode"]
GWD = ["General Graardor", "Commander Zilyana", "Kree'Arra", "K'ril Tsutsaroth"]
DT2 = ["Vardorvis", "Duke Sucellus", "The Leviathan", "The Whisperer"]
KC_TILES = {
    "Little": {
        1: ["Mad Angel", "Grotesque Guardians"], 2: ["The Royal Titans"], 3: ["Zulrah", "Kraken"], 4: RAIDS,
        6: GWD, 7: ["The Hueycoatl"], 8: ["Dagannoth Rex", "Dagannoth Prime", "Dagannoth Supreme"],
        9: ["Lunar Chests"], 10: ["Barrows Chests"], 11: ["Wintertodt", "Tempoross", "The Hueycoatl"],
        12: ["Obor", "Bryophyta"], 13: ["TzTok-Jad"], 14: ["Vorkath", "King Black Dragon"], 15: ["Sarachnis"],
        16: ["Grotesque Guardians", "General Graardor"], 17: ["General Graardor", "Theatre of Blood"], 18: RAIDS,
        19: GWD, 20: ["Scorpia", "Chaos Fanatic", "Crazy Archaeologist"], 21: ["Brutus"],
        22: ["Shellbane Gryphon"], 23: ["Vorkath"],
    },
    "Big": {
        1: ["Maggot King"], 2: ["Yama"], 3: ["Doom of Mokhaiotl"],
        4: ["Theatre of Blood", "Theatre of Blood: Hard Mode", "Tombs of Amascut", "Tombs of Amascut: Expert Mode"],
        6: DT2, 7: ["Nex"], 8: ["Chambers of Xeric", "Chambers of Xeric: Challenge Mode", "Theatre of Blood", "Theatre of Blood: Hard Mode"],
        10: RAIDS, 11: ["Zalcano"], 12: ["Phantom Muspah"], 14: DT2, 15: ["The Gauntlet", "The Corrupted Gauntlet"],
        16: GWD + ["Nex"],
        17: ["Zulrah", "Grotesque Guardians", "Sarachnis", "Kalphite Queen", "Abyssal Sire", "Alchemical Hydra", "Cerberus",
             "Kraken", "Thermonuclear Smoke Devil", "Giant Mole", "King Black Dragon", "Nightmare", "Araxxor"],
        18: ["Yama"], 19: ["Phantom Muspah"] + DT2,
        20: ["Callisto", "Venenatis", "Vet'ion", "Artio", "Spindel", "Calvar'ion"], 21: ["Brutus"], 22: ["Sol Heredit"],
        23: ["Phosani's Nightmare"], 25: ["TzTok-Jad", "TzKal-Zuk"],
    },
}

ITEM_NAMES = json.loads((ROOT / "scripts" / "item_names.json").read_text())


def get_json(url):
    out = subprocess.run(["curl", "-s", "-L", "--max-time", "30", "-A", UA, url],
                         capture_output=True, text=True).stdout
    time.sleep(2)  # be gentle with the free APIs
    try:
        return json.loads(out)
    except ValueError:
        return None


def wikisync(name):
    d = get_json(f"https://sync.runescape.wiki/runelite/player/{urllib.parse.quote(name)}/STANDARD")
    if not d or "collection_log" not in d:
        return None
    ids = d.get("collection_log") or []
    QUESTS[name] = d.get("quests") or {}
    return {str(i): ITEM_NAMES.get(str(i), f"Item {i}") for i in ids}


def temple(name):
    d = get_json("https://templeosrs.com/api/collection-log/player_collection_log.php?player="
                 f"{urllib.parse.quote(name)}&categories=all&includenames=1&onlyitems=1")
    if not d or "data" not in d:
        return None
    items = {}
    for it in d["data"].get("items", []):
        items[str(it["id"])] = it["name"]
    return items


def hiscores(name):
    d = get_json(f"https://secure.runescape.com/m=hiscore_oldschool/index_lite.json?player={urllib.parse.quote(name)}")
    if not d or "activities" not in d:
        return None
    acts = {a["name"]: a["score"] for a in d["activities"] if a["score"] > 0}
    acts["_skills"] = {sk["name"]: sk["level"] for sk in d.get("skills", [])}
    return acts


def norm_name(name):
    """'Prospector boots 29478' and 'Prospector boots' are the same collection log slot."""
    return re.sub(r"\s+\d+$", "", name).strip().lower()


def tiles_for(board, item_name):
    return [t for t, pat in TILES[board].items() if re.search(pat, item_name, re.I)]


TITLES = {
    "Little": ["Whats your angel?", "Titan your Belt", "Tried and Dented", "ZE PANTY RAID", "Guarding my face",
               "Godly Gamer", "Hueycoatl and the News", "Daggan These Nuts", "Perilous Times", "Can i Barrow some of your time?",
               "Tell it ToMe Straight", "Big mean Greenie or Mr Mammal?", "Hot Stuff", "Draconic Dreams", "Big Ass Spider",
               "Sweet kicks", "Dropping Defence Matters", "Getting the hang of this", "You GODa be kidding me", "Warding off Evil",
               "Beefy Tile", "Pigeon Crusher", "Dragon Slayer", "What's Following me?", "CHUG CHUG CHUG"],
    "Big": ["Maggot Crusher", "Yama Time", "Dinner with the bug", "Uncomfortable Raider", "HOW RARE IS IT??",
            "Just Deserts", "Time to get Nexy", "Nice Recolor!", "Spooky Ghosts!", "Raid armor",
            "Zalcanic mine", "Purple Prison", "Speedy Boys", "WAKE ME UP", "Big Mean Prison",
            "FETCH THE GODSWORD", "One man, One Jar", "Contract Killer", "Fancy Staff", "Void Gatherer",
            "Unholy Cow!", "Showmanship", "Kasper's Nightmare", "Can I pet it?", "You can't Be Tzharrious"],
}

# Hard requirements from the OSRS Wiki. ("skill", name, level) or ("quest", name). "soft" = recommended only.
REQS = {
    "Little": {
        2: [("soft_combat", 90)], 3: [("skill", "Slayer", 87)],
        5: [("skill", "Slayer", 60), ("quest", "The Fremennik Exiles")],
        6: [("quest", "Troll Stronghold")], 19: [("quest", "Troll Stronghold")],
        9: [("quest", "Perilous Moons")], 10: [("quest", "Priest in Peril")],
        16: [("skill", "Slayer", 75), ("quest", "Troll Stronghold")],
        21: [("quest", "The Ides of Milk")], 22: [("quest", "Troubled Tortugans")],
        23: [("quest", "Dragon Slayer II")],
        25: [("skill", "Herblore", 60), ("quest", "Children of the Sun")],
    },
    "Big": {
        1: [("quest", "The Blood Moon Rises")], 2: [("quest", "A Kingdom Divided")], 18: [("quest", "A Kingdom Divided")],
        3: [("quest", "The Final Dawn")],
        6: [("quest", "Desert Treasure II - The Fallen Empire")], 14: [("quest", "Desert Treasure II - The Fallen Empire")],
        11: [("quest", "Song of the Elves"), ("skill", "Mining", 70), ("skill", "Smithing", 70)],
        12: [("quest", "Secrets of the North")],
        13: [("quest", "Dragon Slayer II"), ("quest", "Song of the Elves"), ("quest", "Monkey Madness II")],
        15: [("quest", "Song of the Elves")], 16: [("quest", "Troll Stronghold")],
        19: [("quest", "Secrets of the North"), ("quest", "Desert Treasure II - The Fallen Empire")],
        21: [("quest", "The Ides of Milk")], 22: [("quest", "Children of the Sun")],
    },
}


def combat_level(sk):
    try:
        base = 0.25 * (sk["Defence"] + sk["Hitpoints"] + sk["Prayer"] // 2)
        melee = 0.325 * (sk["Attack"] + sk["Strength"])
        rng = 0.325 * (sk["Ranged"] * 3 // 2)
        mag = 0.325 * (sk["Magic"] * 3 // 2)
        return int(base + max(melee, rng, mag))
    except (KeyError, TypeError):
        return None


def check_reqs(name, board, tile, skills):
    """Return ("cant", why) / ("unknown", why) / ("can", "")."""
    missing, unknown, soft = [], [], []
    quests = QUESTS.get(name)
    for r in REQS[board].get(tile, []):
        if r[0] == "skill":
            lvl = skills.get(r[1])
            if lvl is None:
                unknown.append(f"{r[1]} {r[2]}")
            elif lvl < r[2]:
                missing.append(f"{r[1]} {r[2]} (has {lvl})")
        elif r[0] == "quest":
            if not quests:
                unknown.append(r[1])
            elif quests.get(r[1], 0) == 0:
                missing.append(f"{r[1]} not started")
        elif r[0] == "soft_combat":
            cb = combat_level(skills)
            if cb is not None and cb < r[1]:
                soft.append(f"combat {r[1]}+ recommended (has {cb})")
    if missing:
        return "cant", "; ".join(missing)
    if unknown:
        return "unknown", "check: " + ", ".join(unknown)
    return "can", "; ".join(soft)


def build_grid(players, skills_by_player):
    claims = json.loads((DATA / "claims.json").read_text())
    grid = {"Little": [], "Big": []}
    for board in ("Little", "Big"):
        roster = [p for p in players if p["board"] == board]
        for t in range(1, 26):
            row = {"tile": t, "title": TITLES[board][t - 1], "starred": t in STARRED[board], "cells": []}
            for p in roster:
                hits = [i["name"] for i in p["new_items"] if t in i["tiles"]]
                state, why = check_reqs(p["name"], board, t, skills_by_player.get(p["name"], {}))
                if hits:
                    state, why = "progress", ", ".join(hits)
                elif t in claims.get(p["name"], {}).get("tiles", []):
                    if state == "cant":
                        why = "WikiSync says: " + why + " (may be out of date)"
                    state = "claimed"
                row["cells"].append({"player": p["name"], "state": state, "why": why})
            grid[board].append(row)
    doubling = []
    for i in range(25):
        def side(board):
            states = [c["state"] for c in grid[board][i]["cells"]]
            if "progress" in states:
                return "progress"
            if "claimed" in states:
                return "claimed"
            if states and all(s == "cant" for s in states):
                return "blocked"
            return "open"
        doubling.append({"tile": i + 1, "little": TITLES["Little"][i], "big": TITLES["Big"][i],
                         "little_state": side("Little"), "big_state": side("Big")})
    return grid, doubling


def build_boards(players):
    """Per board, per tile: done, who's on it, drops spotted, and whether the same square on the other board is active."""
    claims = json.loads((DATA / "claims.json").read_text())
    done = json.loads((DATA / "done.json").read_text())
    manual_file = DATA / "manual.json"
    manual = json.loads(manual_file.read_text()).get("drops", []) if manual_file.exists() else []
    boards = {}
    for board in ("Little", "Big"):
        roster = [p for p in players if p["board"] == board]
        others = [p for p in players if p["board"] != board]
        tiles = []
        for t in range(1, 26):
            drops = [{"player": p["name"], "item": i["name"]} for p in roster for i in p["new_items"] if t in i["tiles"]]
            drops += [{"player": p["name"], "item": i["name"], "cross": True}
                      for p in others for i in p["new_items"] if t in i.get("other_tiles", [])]
            drops += [{"player": m["player"], "item": m["item"], "manual": True}
                      for m in manual if m.get("board") == board and m.get("tile") == t]
            on_it = [p["name"] for p in roster if t in claims.get(p["name"], {}).get("tiles", [])]
            bosses = set(KC_TILES[board].get(t, []))
            by = []
            for p in players:
                n = sum(k["gain"] for k in p.get("kc_all", []) if k["name"] in bosses)
                if n:
                    by.append({"player": p["name"], "kills": n})
            by.sort(key=lambda x: -x["kills"])
            # Players on this board grinding the tile's bosses count as "on it" even if they didn't say so
            roster_names = {p["name"] for p in roster}
            on_it_kills = [b["player"] for b in by if b["player"] in roster_names and b["player"] not in on_it]
            state = "done" if t in done.get(board, []) else ("on" if on_it or drops or on_it_kills else "none")
            tiles.append({"tile": t, "title": TITLES[board][t - 1], "starred": t in STARRED[board],
                          "manual": t in MANUAL[board],
                          "kills": sum(b["kills"] for b in by), "kills_by": by, "on_it_kills": on_it_kills,
                          "state": state, "on_it": on_it, "drops": drops})
        boards[board] = tiles
    for board, other in (("Little", "Big"), ("Big", "Little")):
        for a, b in zip(boards[board], boards[other]):
            a["x2"] = b["state"] in ("done", "on")
            a["other_title"] = b["title"]
            a["other_state"] = b["state"]
    return boards


def main():
    now = datetime.now(timezone.utc)
    started = now >= START
    BASE.mkdir(parents=True, exist_ok=True)
    out = {"checked": now.strftime("%Y-%m-%d %H:%M UTC"), "started": started,
           "start": START.strftime("%Y-%m-%d %H:%M UTC"), "players": []}
    skills_by_player = {}
    claims_all = json.loads((DATA / "claims.json").read_text())

    for p in PLAYERS:
        name, board = p["name"], p["board"]
        logs = {}
        sources = []
        ws = wikisync(name)
        if ws:
            logs.update(ws)
            sources.append("WikiSync")
        tp = temple(name)
        if tp:
            logs.update(tp)
            sources.append("Temple")
        kc = hiscores(name)
        skills_by_player[name] = (kc or {}).get("_skills", {})
        if kc is not None:
            sources.append("Hiscores")

        snap = {"items": logs, "kc": {k: v for k, v in (kc or {}).items() if k != "_skills"}}
        base_file = BASE / f"{name.replace(' ', '_')}.json"
        if started and not base_file.exists():
            base_file.write_text(json.dumps(snap, indent=1, sort_keys=True))
        base = json.loads(base_file.read_text()) if base_file.exists() else None
        if base is not None:
            changed = False
            if not base["items"] and logs:   # log synced for the first time after the start
                base["items"] = logs
                base["log_since"] = now.strftime("%Y-%m-%d %H:%M UTC")
                changed = True
            if not base["kc"] and snap["kc"]:   # hiscores failed when the baseline was taken
                base["kc"] = snap["kc"]
                changed = True
            if changed:
                base_file.write_text(json.dumps(base, indent=1, sort_keys=True))

        new_items, kc_gains = [], []
        if base:
            # Compare by item name, not ID: WikiSync and Temple sometimes use different IDs for the same item
            base_names = {norm_name(n) for n in base["items"].values()}
            seen = set()
            for iid, iname in sorted(logs.items(), key=lambda x: x[1]):
                key = norm_name(iname)
                if key in base_names or key in seen:
                    continue
                seen.add(key)
                if True:
                    t = tiles_for(board, iname)
                    other = "Big" if board == "Little" else "Little"
                    cross = [x for x in tiles_for(other, iname) if x in STARRED[other]]
                    new_items.append({"name": iname, "tiles": t,
                                      "starred": [x for x in t if x in STARRED[board]],
                                      "other_board": other if cross else "", "other_tiles": cross})
            for act, score in (kc or {}).items():
                if act == "_skills":
                    continue
                gain = score - base["kc"].get(act, 0)
                if gain > 0 and not act.startswith(("Clue Scrolls", "PvP Arena", "LMS", "Collections")):
                    kc_gains.append({"name": act, "gain": gain})
            kc_gains.sort(key=lambda x: -x["gain"])

        sk = (kc or {}).get("_skills", {})
        keep = ["Attack", "Strength", "Defence", "Hitpoints", "Ranged", "Magic", "Prayer", "Slayer", "Agility", "Herblore", "Overall"]
        top_kc = sorted(((v, k) for k, v in (kc or {}).items()
                         if k != "_skills" and not k.startswith(("Clue Scrolls", "PvP Arena", "LMS", "Collections"))),
                        reverse=True)[:8]
        out["players"].append({
            "name": name, "board": board, "note": p.get("note", ""), "sources": sources,
            "combat": combat_level(sk), "skills": {k: sk[k] for k in keep if k in sk},
            "top_kc": [{"name": k, "kc": v} for v, k in top_kc],
            "log_items": len(logs), "has_baseline": bool(base),
            "log_since": (base or {}).get("log_since", ""),
            "going": claims_all.get(name, {}).get("going", []),
            "notes": claims_all.get(name, {}).get("notes", "") or p.get("note", ""),
            "baseline_has_log": bool(base and base["items"]),
            "new_items": new_items, "kc_gains": kc_gains[:12], "kc_all": kc_gains,
        })

    out["grid"], out["doubling"] = build_grid(out["players"], skills_by_player)
    out["boards"] = build_boards(out["players"])
    out["leaderboard"] = sorted(
        [{"player": p["name"], "board": p["board"], "kills": sum(k["gain"] for k in p["kc_all"]),
          "top": [{"name": k["name"], "gain": k["gain"]} for k in p["kc_all"][:3]]} for p in out["players"]],
        key=lambda x: -x["kills"])
    DATA.mkdir(exist_ok=True)
    path = DATA / "status.json"
    if path.exists():
        prev = json.loads(path.read_text())
        if {k: v for k, v in prev.items() if k != "checked"} == {k: v for k, v in out.items() if k != "checked"}:
            print("No changes")
            return
    path.write_text(json.dumps(out, indent=1))
    print(json.dumps({p["name"]: (p["sources"], p["log_items"], len(p["new_items"])) for p in out["players"]}))


if __name__ == "__main__":
    main()
