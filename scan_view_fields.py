import json
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(r"d:\GithubProjects\hap-droid\droidbot_events")
counter = Counter()
types = defaultdict(set)

def walk(obj, path="view"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            counter[p] += 1
            types[p].add(type(v).__name__)
            walk(v, p)
    elif isinstance(obj, list):
        p = f"{path}[]"
        counter[p] += 1
        types[p].add("list")
        for it in obj:
            walk(it, p)

for f in ROOT.glob("event_*.json"):
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        v = data.get("event", {}).get("view")
        if isinstance(v, (dict, list)):
            walk(v, "event.view")
    except Exception:
        pass

for k, n in counter.most_common():
    print(f"{k}\tcount={n}\ttypes={','.join(sorted(types[k]))}")