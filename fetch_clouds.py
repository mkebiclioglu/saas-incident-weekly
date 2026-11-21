"""Incident history for the big players that do not run Statuspage.

  gcp    Google Cloud  - union of Internet Archive snapshots of the official
                         status.cloud.google.com/incidents.json (each snapshot
                         holds ~12 months, snapshots are ~monthly) + live feed
  aws    AWS           - union of Internet Archive snapshots of the official
                         Health Dashboard feeds: status.aws.amazon.com/data.json
                         (to 2023) and history-events-...s3.../historyevents.json
                         (2023 on, ~12-month window) + live feed
  azure  Microsoft Azure - live azure.status.microsoft history (Post Incident
                         Reviews, retained 5 years)
  slack  Slack         - slack-status.com day pages (full history)

Writes data/incidents_big.csv with the same columns as data/incidents.csv
plus `source`. Raw downloads are cached in .cache/ (gitignored).
"""
import csv
import datetime as dt
import gzip
import hashlib
import html
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).parent
CACHE = ROOT / ".cache"
UA = "incident-history-research/1.0"
SINCE = "2019-06-01"  # snapshots from here cover Jan 2020 onward


def fetch(url, cache=True, tries=4):
    CACHE.mkdir(exist_ok=True)
    path = CACHE / hashlib.sha1(url.encode()).hexdigest()
    if cache and path.exists():
        return path.read_bytes()
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
            if cache:
                path.write_bytes(body)
            return body
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def text(body):
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return body.decode(enc)
        except UnicodeDecodeError:
            pass
    return body.decode("utf-8", "replace")


def snapshots(url):
    """One Internet Archive capture per month of `url` since SINCE (each
    feed snapshot holds months of history, so this leaves no gaps)."""
    q = urllib.parse.urlencode({"url": url, "output": "json", "filter": "statuscode:200",
                                "fl": "timestamp", "from": SINCE.replace("-", "")[:6]})
    for i in range(5):
        try:
            rows = json.loads(fetch(f"https://web.archive.org/cdx/search/cdx?{q}", cache=False))[1:]
            break
        except ValueError:
            time.sleep(10 * (i + 1))
    else:
        raise RuntimeError(f"CDX lookup failed for {url}")
    picked = {}
    for (ts,) in rows:
        picked.setdefault(ts[:6], ts)
    return sorted(picked.values())


def wayback(ts, url):
    time.sleep(1)  # be polite to the Internet Archive
    return text(fetch(f"https://web.archive.org/web/{ts}id_/{url}"))


def json_array_salvage(s):
    """Parse a JSON array, keeping every complete element if the capture was truncated."""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    dec, out, i = json.JSONDecoder(), [], s.index("[") + 1
    while True:
        while i < len(s) and s[i] in " \n\r\t,":
            i += 1
        try:
            obj, i = dec.raw_decode(s, i)
        except json.JSONDecodeError:
            return out
        out.append(obj)


def day(ts):
    return dt.datetime.fromtimestamp(int(ts), dt.UTC).date().isoformat()


# ---------------------------------------------------------------- GCP
def gcp():
    url = "https://status.cloud.google.com/incidents.json"
    docs = [(ts, wayback(ts, url)) for ts in snapshots("status.cloud.google.com/incidents.json")]
    docs.append(("live", text(fetch(url, cache=False))))
    rows = {}
    for ts, s in docs:
        try:
            items = json_array_salvage(s)
        except ValueError:
            print(f"gcp snapshot {ts}: not JSON, skipped", file=sys.stderr)
            continue
        for x in items:
            if not isinstance(x, dict) or not x.get("begin"):
                continue
            # The pre-2021 schema posts one record per product plus a pointer
            # "linked to a single Google incident"; keep only the parent.
            mru = x.get("most_recent_update") or x.get("most-recent-update") or {}
            if "linked to a single Google incident" in (mru.get("text") or ""):
                continue
            desc = (x.get("external_desc") or "").strip().split("\n")[0]
            # Key on start minute + description so the same incident seen
            # under the old (number/uri) and new (id) schema counts once.
            key = x["begin"][:16] + "|" + re.sub(r"\W+", "", desc.lower())[:60]
            link = (f"https://status.cloud.google.com/incidents/{x['id']}" if x.get("id")
                    else "https://status.cloud.google.com" + (x.get("uri") or ""))
            rows[key] = {
                "vendor_id": "gcp", "vendor": "Google Cloud", "category": "hyperscaler",
                "incident_id": x.get("id") or x.get("uri") or str(x.get("number")),
                "started_on": x["begin"][:10],
                "impact": (x.get("severity") or "").lower(),
                "title": desc[:200], "url": link,
                "source": "status.cloud.google.com/incidents.json (live + Internet Archive)",
            }
    return list(rows.values())


# ---------------------------------------------------------------- AWS
def aws():
    old = "https://status.aws.amazon.com/data.json"
    new = "https://history-events-us-west-2-prod.s3.amazonaws.com/historyevents.json"
    rows = {}

    def add(service, date, title):
        key = f"{service}:{date}"
        rows[key] = {
            "vendor_id": "aws", "vendor": "AWS", "category": "hyperscaler",
            "incident_id": key, "started_on": day(date), "impact": "",
            "title": re.sub(r"^\[RESOLVED\]\s*", "", title or "").strip()[:200],
            "url": "https://health.aws.amazon.com/health/status",
            "source": "AWS Health Dashboard feeds (Internet Archive + live)",
        }

    for ts in snapshots("status.aws.amazon.com/data.json"):
        try:
            d = json.loads(wayback(ts, old))
        except ValueError:
            continue
        for x in d.get("archive", []):
            add(x.get("service"), x["date"], x.get("summary"))
    docs = [wayback(ts, new) for ts in snapshots(
        "history-events-us-west-2-prod.s3.amazonaws.com/historyevents.json")]
    docs.append(text(fetch(new, cache=False)))
    for s in docs:
        try:
            d = json.loads(s)
        except ValueError:
            continue
        for service, events in d.items():
            for e in events:
                log = e.get("event_log") or [{}]
                add(service, e["date"], log[0].get("summary"))
    return list(rows.values())


# ---------------------------------------------------------------- Azure
def azure():
    rows, page = {}, 1
    pat = re.compile(r'data-target="#incident-history-collapse-([A-Za-z0-9_-]+)".*?'
                     r'hide-text">(\d\d)/(\d\d)/(\d{4})</span>\s*'
                     r'<div class="col-md-8 incident-history-title">\s*(.*?)\s*</div>', re.S)
    while True:
        s = text(fetch("https://azure.status.microsoft/en-us/statushistoryapi/?serviceSlug=all"
                       f"&regionSlug=all&startDate=all&page={page}&shdrefreshflag=true", cache=False))
        found = pat.findall(s)
        if not found:
            break
        for tid, mm, dd, yyyy, title in found:
            rows.setdefault(tid, {
                "vendor_id": "azure", "vendor": "Microsoft Azure", "category": "hyperscaler",
                "incident_id": tid, "started_on": f"{yyyy}-{mm}-{dd}", "impact": "pir",
                "title": html.unescape(re.sub(r"\s+", " ", title))[:200],
                "url": f"https://azure.status.microsoft/en-us/status/history/?trackingid={tid}",
                "source": "azure.status.microsoft status history (PIRs)",
            })
        page += 1
        time.sleep(0.5)
    return list(rows.values())


# ---------------------------------------------------------------- Slack
def slack_day(d):
    s = text(fetch(f"https://slack-status.com/{d}"))
    out = []
    for block in s.split('<div class="incident">')[1:]:
        kind = re.search(r'<p class="bold">\s*([^<]+?)\s*</p>', block)
        title = re.search(r'<h3 class="bold title[^"]*">\s*(.*?)\s*</h3>', block, re.S)
        out.append((d, kind.group(1) if kind else "", html.unescape(title.group(1)) if title else ""))
    return out


def slack(start="2020-01-01", end=None):
    end = dt.date.fromisoformat(end) if end else dt.date.today()
    days, d = [], dt.date.fromisoformat(start)
    while d <= end:
        days.append(d.isoformat())
        d += dt.timedelta(days=1)
    with ThreadPoolExecutor(4) as ex:
        found = [x for xs in ex.map(slack_day, days) for x in xs]
    # A multi-day incident appears on every day it spans: keep the first day
    # of each run of the same (type, title) on consecutive days.
    rows, last_seen = [], {}
    for d, kind, title in sorted(found):
        key = (kind, title)
        prev = last_seen.get(key)
        last_seen[key] = d
        if prev and (dt.date.fromisoformat(d) - dt.date.fromisoformat(prev)).days <= 1:
            continue
        rows.append({
            "vendor_id": "slack", "vendor": "Slack", "category": "saas",
            "incident_id": f"{d}:{title[:40]}", "started_on": d,
            "impact": kind.lower(), "title": title[:200],
            "url": f"https://slack-status.com/{d}", "source": "slack-status.com day pages",
        })
    return rows


def main():
    which = sys.argv[1:] or ["gcp", "aws", "azure", "slack"]
    out = ROOT / "data/incidents_big.csv"
    for name in which:  # save after each source so one failure loses nothing
        got = globals()[name]()
        print(f"{name:6s} {len(got):6d} incidents, "
              f"{min(r['started_on'] for r in got)} .. {max(r['started_on'] for r in got)}",
              file=sys.stderr)
        rows = [r for r in csv.DictReader(open(out)) if r["vendor_id"] != name] if out.exists() else []
        rows += got
        rows.sort(key=lambda r: (r["started_on"], r["vendor_id"], r["incident_id"]))
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
