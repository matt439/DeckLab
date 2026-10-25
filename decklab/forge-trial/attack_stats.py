"""Per deck: how often the AI attacks. python attack_stats.py TAG [TAG ...]

From each game's log: own turns taken (Turn: lines), turns with at least one attack
("Combat: <player> assigned ... to attack"), attackers per attack, and own turns where the deck
had not attacked yet by round 5. Uses the batch logs listed in results/matchups/<tag>/summary.json.
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path
HERE = Path(__file__).resolve().parent
RE_T = re.compile(r"^Turn: Turn (\d+) \(Ai\((\d)\)-(.*)\)\s*$")
RE_A = re.compile(r"^Combat: Ai\((\d)\)-(.*?) assigned (.*) to attack ")
for tag in sys.argv[1:]:
    s = json.loads((HERE / "results" / "matchups" / tag / "summary.json").read_text(encoding="utf-8"))
    st = defaultdict(lambda: {"turns": 0, "attack_turns": 0, "attackers": 0, "games": 0, "first_attack_round": []})
    for b in s["batches"]:
        cur = None; attacked = set(); first = {}
        names = {}
        for line in Path(b["log"]).read_text(encoding="utf-8", errors="replace").splitlines():
            m = RE_T.match(line)
            if m:
                cur = (int(m[1]), m[3]); st[m[3]]["turns"] += 1; names[m[2]] = m[3]
                continue
            m = RE_A.match(line)
            if m and cur and (cur[0], m[2]) not in attacked:
                attacked.add((cur[0], m[2]))
                d = st[m[2]]; d["attack_turns"] += 1
                d["attackers"] += len(re.findall(r"\(\d+\)", m[3]))  # one "(id)" per attacking card
                first.setdefault(m[2], (cur[0] + 1) // 2)
                continue
            if line.startswith("Game Result:"):
                for n in set(names.values()):
                    st[n]["games"] += 1
                    st[n]["first_attack_round"].append(first.get(n))
                attacked = set(); first = {}; names = {}; cur = None
    print(tag)
    for n, d in st.items():
        fa = [x for x in d["first_attack_round"] if x]
        print(f"  {n:32s} games {d['games']:5d}  own turns {d['turns']:6d}  attacked on {100*d['attack_turns']/d['turns']:4.1f}% of own turns"
              f"  attackers/attack {d['attackers']/max(1,d['attack_turns']):.2f}  first attack round mean {sum(fa)/max(1,len(fa)):.1f}"
              f"  never attacked {sum(1 for x in d['first_attack_round'] if not x)} games")
