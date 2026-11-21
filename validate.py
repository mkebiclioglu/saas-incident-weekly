"""Cross-check start dates parsed from history.json display strings against
each vendor's structured /api/v2/incidents.json (ISO timestamps, last 50)."""
import csv
import datetime as dt
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).parent
ours = {r["incident_id"]: r for r in csv.DictReader(open(ROOT / "data/incidents.csv"))}
tot = exact = one = worse = missing = 0
for v in csv.DictReader(open(ROOT / "data/vendors.csv")):
    req = urllib.request.Request(v["status_page"] + "/api/v2/incidents.json",
                                 headers={"User-Agent": "incident-history-research/1.0"})
    try:
        incs = json.load(urllib.request.urlopen(req, timeout=20))["incidents"]
    except Exception as e:
        print(f"{v['vendor_id']}: API unavailable ({e})")
        continue
    for i in incs:
        api_day = (i.get("started_at") or i["created_at"])[:10]
        if api_day < "2015-01-01":
            continue
        tot += 1
        if i["id"] not in ours:
            missing += 1
            continue
        d = abs((dt.date.fromisoformat(ours[i["id"]]["started_on"]) - dt.date.fromisoformat(api_day)).days)
        exact += d == 0
        one += d == 1
        worse += d > 1
print(f"checked {tot}: exact {exact}, off by 1 day {one}, off by >1 day {worse}, "
      f"not (yet) in history {missing}")
