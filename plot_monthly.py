"""Monthly incident exhibits, Jan 2020 - Oct 2026.

Exhibit 1: total monthly incidents across a fixed panel of vendors.
Exhibit 2: the big platforms (AWS, Google Cloud, Microsoft Azure, Slack), one row each.
Writes exhibit1_panel_monthly.png, exhibit2_big_platforms.png, data/monthly.csv, data/panel.csv.
"""
import collections
import csv
import datetime as dt
import pathlib
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = pathlib.Path(__file__).parent
FIRST, LAST = "2020-01", "2026-10"          # Nov 2026 is incomplete
JOINED_BY, ACTIVE_FROM, MAX_GAP = "2020-04-01", "2026-01-01", 180
MAINT = re.compile(r"\[scheduled\]|scheduled maintenance|planned maintenance", re.I)
BIG = [("aws", "AWS"), ("gcp", "Google Cloud"), ("azure", "Microsoft Azure"), ("slack", "Slack")]

NAVY, BLUE, GRAY, SHADE, INK = "#051C2C", "#2251FF", "#7F7F7F", "#F0F0F0", "#1A1A1A"
plt.rcParams.update({
    "font.family": "Arial", "font.size": 10.5, "text.color": INK,
    "axes.edgecolor": GRAY, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": GRAY,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "axes.grid": False, "figure.facecolor": "white", "axes.facecolor": "white",
})
MON = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def label(m):
    return f"{MON[int(m[5:]) - 1]} {m[:4]}"


MONTHS = []
y, m = map(int, FIRST.split("-"))
while f"{y:04d}-{m:02d}" <= LAST:
    MONTHS.append(f"{y:04d}-{m:02d}")
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
X = range(len(MONTHS))
IDX = {m: i for i, m in enumerate(MONTHS)}

# ---------------------------------------------------------------- data
rows = []
for f in ("incidents.csv", "incidents_big.csv"):
    for r in csv.DictReader(open(ROOT / "data" / f)):
        if r["vendor_id"] == "twilio" or r["impact"] == "maintenance" or MAINT.search(r["title"]):
            continue
        if r["vendor_id"] == "slack" and r["impact"] not in ("incident", "outage"):
            continue  # Slack also posts notices
        rows.append(r)

first, last, name = {}, {}, {}
days = collections.defaultdict(list)
by = collections.defaultdict(collections.Counter)  # vendor -> month -> n
for r in rows:
    v, d = r["vendor_id"], r["started_on"]
    first[v], last[v], name[v] = min(first.get(v, "9"), d), max(last.get(v, ""), d), r["vendor"]
    if FIRST <= d[:7] <= LAST:
        days[v].append(dt.date.fromisoformat(d))
        by[v][d[:7]] += 1


def max_gap(v):
    ds = sorted(days[v])
    return max((b - a).days for a, b in zip(ds, ds[1:])) if len(ds) > 1 else 9999


# Fixed panel: publishing by Q1 2020, still publishing in 2026, never silent
# for more than 180 days in between (silence that long is a reporting gap).
eligible = [v for v in first if first[v] < JOINED_BY and last[v] >= ACTIVE_FROM]
panel = sorted(v for v in eligible if max_gap(v) <= MAX_GAP)
dropped = {name[v]: max_gap(v) for v in eligible if v not in panel}
total = [sum(by[v][m] for v in panel) for m in MONTHS]

with open(ROOT / "data/monthly.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["month", f"fixed_panel_{len(panel)}"] + [v for v, _ in BIG])
    for i, m in enumerate(MONTHS):
        w.writerow([m, total[i]] + [by[v][m] for v, _ in BIG])
with open(ROOT / "data/panel.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["vendor_id", "vendor", "first_incident", "last_incident",
                "longest_silence_days", "incidents_jan2020_oct2026"])
    for v in panel:
        w.writerow([v, name[v], first[v], last[v], max_gap(v), sum(by[v].values())])


def year_avgs(series):
    acc = collections.defaultdict(list)
    for mo, n in zip(MONTHS, series):
        acc[mo[:4]].append(n)
    return {yr: sum(v) / len(v) for yr, v in acc.items()}


# ---------------------------------------------------------------- helpers
def xaxis(ax, labels=True):
    ticks = [i for i, mo in enumerate(MONTHS) if mo.endswith("-01")]
    ax.set_xticks(ticks, [MONTHS[i][:4] for i in ticks] if labels else [])
    ax.tick_params(axis="both", length=0)
    ax.tick_params(axis="x", pad=6)
    ax.set_xlim(-1, len(MONTHS))


def header(fig, title, subtitle):
    fig.text(0.06, 0.975, title, fontsize=16, weight="bold", color=NAVY, va="top")
    fig.text(0.06, 0.925, subtitle, fontsize=10.5, color=GRAY, va="top", linespacing=1.4)


def footer(fig, text):
    fig.text(0.06, 0.015, text, fontsize=8, color=GRAY, va="bottom", linespacing=1.5)


def callout(ax, i, y, text, tx, ty, ha="left"):
    ax.annotate(text, xy=(i, y), xytext=(tx, ty), ha=ha, va="center", fontsize=9.5, color=INK,
                linespacing=1.35,
                arrowprops=dict(arrowstyle="-", color=GRAY, lw=0.8, shrinkA=3, shrinkB=2))


# ---------------------------------------------------------------- exhibit 1
avgs = year_avgs(total)
a0, a1 = avgs[FIRST[:4]], avgs[LAST[:4]]
chg = (a1 / a0 - 1) * 100
overall = sum(total) / len(total)
trend = (f"held roughly flat at ~{5 * round(overall / 5):.0f} a month" if abs(chg) < 10
         else f"{'rose' if chg > 0 else 'fell'} {abs(chg):.0f}%")

fig, ax = plt.subplots(figsize=(12, 6.4))
fig.subplots_adjust(left=0.08, right=0.97, top=0.76, bottom=0.17)
ax.bar(X, total, width=0.7, color=NAVY)
ymax = max(total)
for yr, a in avgs.items():
    idx = [i for i, mo in enumerate(MONTHS) if mo.startswith(yr)]
    ax.hlines(a, idx[0] - 0.45, idx[-1] + 0.45, color=BLUE, lw=2)
    ax.text((idx[0] + idx[-1]) / 2, ymax * 1.24, f"{a:,.0f}", ha="center", fontsize=11,
            weight="bold", color=BLUE)
ax.text(-1, ymax * 1.34, "Average incidents per month, by year (blue lines)", fontsize=9.5,
        color=BLUE)
pk = max(X, key=lambda i: total[i])
lo = min(X, key=lambda i: total[i])
callout(ax, pk, total[pk], f"High: {total[pk]} ({label(MONTHS[pk])})", pk, ymax * 1.09,
        ha="center")
callout(ax, lo, total[lo], f"Low: {total[lo]} ({label(MONTHS[lo])})", lo, ymax * 1.09,
        ha="center")
ax.set_ylim(0, ymax * 1.38)
ax.set_yticks(range(0, int(ymax) + 1, 50))
ax.set_ylabel("Incidents reported per month")
ax.set_xlabel("Month the incident started")
xaxis(ax)
header(fig, f"Publicly reported incidents across {len(panel)} SaaS and cloud vendors\n"
            f"have {trend} since 2020",
       f"Monthly incidents posted on vendors' own status pages, Jan 2020 – Oct 2026; same {len(panel)} "
       "vendors throughout, incl. AWS and Slack")
fig.texts[0].set_y(0.985)
fig.texts[1].set_y(0.865)
footer(fig, "Note: Fixed panel = vendors publishing since Q1 2020 and never silent >180 days (list in "
            "data/panel.csv). Twilio and scheduled maintenance excluded. Google Cloud and Azure\n"
            "are not in the panel (gaps in public reporting) – see Exhibit 2. "
            "Source: Statuspage history.json, AWS Health Dashboard feeds via the Internet Archive, "
            "slack-status.com.")
fig.savefig(ROOT / "exhibit1_panel_monthly.png", dpi=160)
plt.close(fig)

# ---------------------------------------------------------------- exhibit 2
fig, axes = plt.subplots(len(BIG), 1, figsize=(12, 10.5), sharex=True)
fig.subplots_adjust(left=0.08, right=0.97, top=0.85, bottom=0.10, hspace=0.62)
series = {v: [by[v][mo] for mo in MONTHS] for v, _ in BIG}
for ax, (v, lab) in zip(axes, BIG):
    ys = series[v]
    top = max(ys)
    ax.bar(X, ys, width=0.7, color=NAVY)
    start = IDX.get(first[v][:7], 0) if first[v][:7] > FIRST else 0
    a = sum(ys[start:]) / (len(ys) - start)
    ax.text(0, 1.18, lab, transform=ax.transAxes, fontsize=12, weight="bold", color=NAVY)
    ax.text(1, 1.18, f"Avg {a:.1f} per month", transform=ax.transAxes, ha="right",
            fontsize=10, color=BLUE, weight="bold")
    ax.set_ylim(0, top * 1.35)
    ax.set_yticks([0, top])
    ax.set_ylabel("Incidents\nper month", fontsize=9)
    xaxis(ax, labels=(ax is axes[-1]))
    if start:
        ax.axvspan(-1, start - 0.5, color=SHADE, lw=0)
        ax.text((start - 1.5) / 2, top * 0.6, "No public\narchive", ha="center", va="center",
                fontsize=9, color=GRAY)

# Callouts: the reporting changes and events visible in the data.
aws, gcp, az, sl = axes
i = IDX["2021-12"]
callout(aws, i, series["aws"][i], "Dec 2021 us-east-1 outage:\nposted as 8 separate service events",
        i + 4, top_aws := max(series["aws"]) * 1.05)
i = IDX["2025-10"]
callout(aws, i, series["aws"][i], "Oct 2025 us-east-1 outage:\nposted once (“multiple services”)",
        i - 1.5, max(series["aws"]) * 0.62, ha="right")
g_last = max(d for d in days["gcp"] if d <= dt.date(2025, 12, 31))
i = IDX[f"{g_last:%Y-%m}"]
callout(gcp, i, series["gcp"][i], f"Public posts nearly stop after {g_last:%b %Y}\n"
        f"({sum(series['gcp'][i + 1:])} posts in the {len(MONTHS) - i - 1} months since)",
        i - 3, max(series["gcp"]) * 0.95, ha="right")
i = IDX["2022-06"]
callout(az, i, series["azure"][i], "Jun 2022: Microsoft limits Post Incident\nReviews to broad incidents",
        i + 6, max(series["azure"]) * 1.05)
pk = max(X, key=lambda j: series["slack"][j])
callout(sl, pk, series["slack"][pk], f"High: {series['slack'][pk]} ({label(MONTHS[pk])})",
        pk + 4, max(series["slack"]) * 1.1)
axes[-1].set_xlabel("Month the incident started")

header(fig, "For the big platforms, changes in reporting rules move the counts more than outages do",
       "Publicly reported incidents per month, Jan 2020 – Oct 2026; each provider on its own scale")
footer(fig, "Counting: AWS = events on the Health Dashboard (per service and Region until ~2022, then "
            "consolidated); Google Cloud = public status-dashboard incidents; Azure = Post Incident\n"
            "Reviews (retained 5 years, so history starts Nov 2021); Slack = incidents and outages. "
            "Source: AWS and Google Cloud feeds via Internet Archive snapshots + live feeds, "
            "azure.status.microsoft, slack-status.com.")
fig.savefig(ROOT / "exhibit2_big_platforms.png", dpi=160)

print(f"panel={len(panel)}; dropped for gaps={dropped}")
print("year avgs:", {k: round(v, 1) for k, v in avgs.items()})
