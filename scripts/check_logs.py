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
    {"name": "PrimalSin", "board": "Little"},
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
    return {a["name"]: a["score"] for a in d["activities"] if a["score"] > 0}


def tiles_for(board, item_name):
    return [t for t, pat in TILES[board].items() if re.search(pat, item_name, re.I)]


def main():
    now = datetime.now(timezone.utc)
    started = now >= START
    BASE.mkdir(parents=True, exist_ok=True)
    out = {"checked": now.strftime("%Y-%m-%d %H:%M UTC"), "started": started,
           "start": START.strftime("%Y-%m-%d %H:%M UTC"), "players": []}

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
        if kc is not None:
            sources.append("Hiscores")

        snap = {"items": logs, "kc": kc or {}}
        base_file = BASE / f"{name.replace(' ', '_')}.json"
        if started and not base_file.exists():
            base_file.write_text(json.dumps(snap, indent=1, sort_keys=True))
        base = json.loads(base_file.read_text()) if base_file.exists() else None

        new_items, kc_gains = [], []
        if base:
            for iid, iname in sorted(logs.items(), key=lambda x: x[1]):
                if iid not in base["items"] and base["items"]:
                    t = tiles_for(board, iname)
                    other = "Big" if board == "Little" else "Little"
                    cross = [x for x in tiles_for(other, iname) if x in STARRED[other]]
                    new_items.append({"name": iname, "tiles": t,
                                      "starred": [x for x in t if x in STARRED[board]],
                                      "other_board": other if cross else "", "other_tiles": cross})
            for act, score in (kc or {}).items():
                gain = score - base["kc"].get(act, 0)
                if gain > 0 and act in base["kc"] and not act.startswith(("Clue Scrolls", "PvP Arena", "LMS")):
                    kc_gains.append({"name": act, "gain": gain})
            kc_gains.sort(key=lambda x: -x["gain"])

        out["players"].append({
            "name": name, "board": board, "note": p.get("note", ""), "sources": sources,
            "log_items": len(logs), "has_baseline": bool(base),
            "baseline_has_log": bool(base and base["items"]),
            "new_items": new_items, "kc_gains": kc_gains[:12],
        })

    DATA.mkdir(exist_ok=True)
    (DATA / "status.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({p["name"]: (p["sources"], p["log_items"], len(p["new_items"])) for p in out["players"]}))


if __name__ == "__main__":
    main()
