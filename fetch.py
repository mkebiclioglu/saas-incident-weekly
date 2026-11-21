"""Fetch every incident a set of vendors published on their Atlassian Statuspage
status page, Jan 2015 onward, via the public paginated /history.json endpoint.

Writes data/incidents.csv (one row per incident) and data/vendors.csv
(one row per vendor, with when its status page was created = coverage start).

Stdlib only. Each history.json page covers 3 months; we walk back until the
page window ends before 2015-01-01 or before the vendor's page existed.
"""
import csv
import html
import json
import pathlib
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "data"
UA = "incident-history-research/1.0 (+https://github.com)"
START = "2015-01-01"

# (id, display name, category, base URL). Enterprise SaaS + cloud/dev
# infrastructure vendors whose public Statuspage history.json responds.
VENDORS = [
    # cloud / dev infrastructure
    ("github", "GitHub", "infra", "https://www.githubstatus.com"),
    ("bitbucket", "Bitbucket", "infra", "https://bitbucket.status.atlassian.com"),
    ("npm", "npm", "infra", "https://status.npmjs.org"),
    ("circleci", "CircleCI", "infra", "https://status.circleci.com"),
    ("travisci", "Travis CI", "infra", "https://www.traviscistatus.com"),
    ("linode", "Linode", "infra", "https://status.linode.com"),
    ("digitalocean", "DigitalOcean", "infra", "https://status.digitalocean.com"),
    ("scaleway", "Scaleway", "infra", "https://status.scaleway.com"),
    ("akamai", "Akamai", "infra", "https://www.akamaistatus.com"),
    ("netlify", "Netlify", "infra", "https://www.netlifystatus.com"),
    ("vercel", "Vercel", "infra", "https://www.vercel-status.com"),
    ("render", "Render", "infra", "https://status.render.com"),
    ("redhat", "Red Hat", "infra", "https://status.redhat.com"),
    ("jfrog", "JFrog Cloud", "infra", "https://status.jfrog.io"),
    ("elastic", "Elastic Cloud", "infra", "https://status.elastic.co"),
    ("mongodb", "MongoDB Cloud", "infra", "https://status.cloud.mongodb.com"),
    ("snowflake", "Snowflake", "infra", "https://status.snowflake.com"),
    ("confluent", "Confluent Cloud", "infra", "https://status.confluent.cloud"),
    ("twilio", "Twilio (incl. SendGrid)", "infra", "https://status.twilio.com"),
    ("mailgun", "Mailgun", "infra", "https://status.mailgun.com"),
    ("pusher", "Pusher", "infra", "https://status.pusher.com"),
    ("cloudinary", "Cloudinary", "infra", "https://status.cloudinary.com"),
    ("imgix", "imgix", "infra", "https://status.imgix.com"),
    ("sentry", "Sentry", "infra", "https://status.sentry.io"),
    ("newrelic", "New Relic", "infra", "https://status.newrelic.com"),
    ("loggly", "Loggly", "infra", "https://status.loggly.com"),
    ("launchdarkly", "LaunchDarkly", "infra", "https://status.launchdarkly.com"),
    ("segment", "Segment", "infra", "https://status.segment.com"),
    ("contentful", "Contentful", "infra", "https://status.contentful.com"),
    # enterprise SaaS
    ("jira", "Jira", "saas", "https://jira-software.status.atlassian.com"),
    ("confluence", "Confluence", "saas", "https://confluence.status.atlassian.com"),
    ("trello", "Trello", "saas", "https://trello.status.atlassian.com"),
    ("dropbox", "Dropbox", "saas", "https://status.dropbox.com"),
    ("box", "Box", "saas", "https://status.box.com"),
    ("hubspot", "HubSpot", "saas", "https://status.hubspot.com"),
    ("zoom", "Zoom", "saas", "https://status.zoom.us"),
    ("smartsheet", "Smartsheet", "saas", "https://status.smartsheet.com"),
    ("airtable", "Airtable", "saas", "https://status.airtable.com"),
    ("monday", "monday.com", "saas", "https://status.monday.com"),
    ("figma", "Figma", "saas", "https://status.figma.com"),
    ("asana", "Asana", "saas", "https://status.asana.com"),
    ("lucid", "Lucid", "saas", "https://status.lucid.co"),
    ("gusto", "Gusto", "saas", "https://status.gusto.com"),
    ("mixpanel", "Mixpanel", "saas", "https://status.mixpanel.com"),
    ("typeform", "Typeform", "saas", "https://status.typeform.com"),
    ("surveymonkey", "SurveyMonkey", "saas", "https://status.surveymonkey.com"),
    ("shopify", "Shopify", "saas", "https://www.shopifystatus.com"),
]

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
MONTH_NAMES = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 ** i)


def start_date(ts, group_year, group_month):
    """'Nov <var data-var='date'>19</var>, <var ...>17:06</var> - ...' -> 'YYYY-MM-DD'.
    The display string has no year. Statuspage lists an incident under the
    month it was resolved, so the start is never after the group month: a
    start month later than the group month means the previous year (e.g. an
    incident open Dec 2025 -> Oct 2026 appears under October 2026)."""
    text = re.sub(r"<[^>]+>", "", html.unescape(ts or "")).strip()
    m = re.match(r"([A-Z][a-z]{2})\s+(\d{1,2})", text)
    if not m or m.group(1) not in MONTHS:
        return None  # unparseable -> no record, never a guessed date
    month, day = MONTHS[m.group(1)], int(m.group(2))
    year = group_year - 1 if month > group_month else group_year
    return f"{year:04d}-{month:02d}-{day:02d}"


def fetch_vendor(v):
    vid, name, cat, base = v
    rows, seen_windows, page, created = {}, set(), 1, None
    skipped = 0
    while True:
        d = get(f"{base}/history.json?page={page}")
        created = created or d["page_status"]["page"]["created_at"][:10]
        window = (d.get("start_time"), d.get("end_time"))
        if window in seen_windows:  # endpoint ignoring ?page
            break
        seen_windows.add(window)
        for mo in d["months"]:
            gm = MONTH_NAMES[mo["name"]]
            for inc in mo["incidents"]:
                day = start_date(inc.get("timestamp"), mo["year"], gm)
                if day is None:
                    skipped += 1
                    continue
                rows[inc["code"]] = {
                    "vendor_id": vid, "vendor": name, "category": cat,
                    "incident_id": inc["code"], "started_on": day,
                    "impact": inc.get("impact") or "",
                    "title": (inc.get("name") or "").strip(),
                    "url": f"{base}/incidents/{inc['code']}",
                }
        st = (d.get("start_time") or "")[:10]
        if not st or st < START or st < created[:8] + "01":
            break
        page += 1
        time.sleep(0.3)
    print(f"{vid:14s} pages={page:3d} incidents={len(rows):6d} created={created} unparsed={skipped}",
          file=sys.stderr)
    return v, created, list(rows.values()), skipped


def main():
    DATA.mkdir(exist_ok=True)
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(fetch_vendor, VENDORS))
    incidents, vendors = [], []
    for (vid, name, cat, base), created, rows, skipped in results:
        rows = [r for r in rows if r["started_on"] >= START]
        incidents += rows
        vendors.append({"vendor_id": vid, "vendor": name, "category": cat, "status_page": base,
                        "page_created": created, "incidents_since_2015": len(rows),
                        "first_incident": min((r["started_on"] for r in rows), default=""),
                        "unparsed": skipped})
    incidents.sort(key=lambda r: (r["started_on"], r["vendor_id"], r["incident_id"]))
    for path, rows in ((DATA / "incidents.csv", incidents), (DATA / "vendors.csv", vendors)):
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    print(f"{len(incidents)} incidents from {len(vendors)} vendors", file=sys.stderr)


if __name__ == "__main__":
    main()
