"""Aggregate data/incidents.csv to weekly counts and draw incidents_weekly.png."""
import csv
import collections
import datetime as dt
import pathlib
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402

ROOT = pathlib.Path(__file__).parent
FIRST_WEEK = dt.date(2014, 12, 29)   # Monday of the week containing 2015-01-01
LAST_WEEK = dt.date(2026, 11, 9)     # last complete Mon-Sun week (ends 2026-11-15)
PANEL_JOINED_BY, PANEL_ACTIVE_FROM = "2015-04-01", "2026-01-01"
MAINT = re.compile(r"\[scheduled\]|scheduled maintenance|planned maintenance", re.I)

BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#52514e"
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def week_of(day):
    d = dt.date.fromisoformat(day)
    return d - dt.timedelta(days=d.weekday())


def rolling(xs, n=13):
    out = []
    for i in range(len(xs)):
        w = xs[max(0, i - n + 1): i + 1]
        out.append(sum(w) / len(w) if i >= n - 1 else None)
    return out


rows = [r for r in csv.DictReader(open(ROOT / "data/incidents.csv"))
        if r["impact"] != "maintenance" and not MAINT.search(r["title"])
        and FIRST_WEEK <= week_of(r["started_on"]) <= LAST_WEEK]

first, last = {}, {}
for r in rows:
    v = r["vendor_id"]
    first[v] = min(first.get(v, "9"), r["started_on"])
    last[v] = max(last.get(v, ""), r["started_on"])
panel = sorted(v for v in first
               if first[v] < PANEL_JOINED_BY and last[v] >= PANEL_ACTIVE_FROM and v != "twilio")

weeks = []
w = FIRST_WEEK
while w <= LAST_WEEK:
    weeks.append(w)
    w += dt.timedelta(days=7)

allv, notw, pan = (collections.Counter() for _ in range(3))
for r in rows:
    k = week_of(r["started_on"])
    allv[k] += 1
    if r["vendor_id"] != "twilio":
        notw[k] += 1
    if r["vendor_id"] in panel:
        pan[k] += 1
# A vendor counts as covered from its first published incident onward; if it has
# published nothing in the final 180 days (e.g. Shopify, Lucid) coverage ends at
# its last incident.
def cover_end(v):
    lw = week_of(last[v])
    return LAST_WEEK if (LAST_WEEK - lw).days <= 180 else lw
covered = {w: sum(week_of(first[v]) <= w <= cover_end(v) for v in first) for w in weeks}
lo, hi = covered[weeks[12]], max(covered.values())

series = {
    "all_vendors": [allv[w] for w in weeks],
    "excl_twilio": [notw[w] for w in weeks],
    "fixed_panel": [pan[w] for w in weeks],
}
with open(ROOT / "data/weekly.csv", "w", newline="") as f:
    wr = csv.writer(f)
    wr.writerow(["week_start", "all_vendors", "excl_twilio", "fixed_panel_17", "vendors_publishing"])
    for i, w in enumerate(weeks):
        wr.writerow([w.isoformat(), series["all_vendors"][i], series["excl_twilio"][i],
                     series["fixed_panel"][i], covered[w]])

# ---- figure -------------------------------------------------------------
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID, "grid.linewidth": 0.8,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
})
fig, axes = plt.subplots(3, 1, figsize=(13, 10.5), sharex=True,
                         gridspec_kw={"height_ratios": [3, 2, 1.2], "hspace": 0.32})
x = weeks


def draw(ax, ys, color, label):
    ax.plot(x, ys, color=color, lw=0.7, alpha=0.28)
    avg = rolling(ys)
    ax.plot(x, avg, color=color, lw=2, label=f"{label} (13-week avg)")
    ax.annotate(f"{avg[-1]:.0f}/wk", (x[-1], avg[-1]), xytext=(6, 0), textcoords="offset points",
                va="center", fontsize=9, color=INK)


ax = axes[0]
draw(ax, series["all_vendors"], BLUE, f"All {len(first)} vendors")
draw(ax, series["excl_twilio"], ORANGE, "Excluding Twilio")
ax.set_title(f"All vendors in the sample (coverage grows from {lo} to {hi} vendors over the period)",
             loc="left", fontsize=11, color=INK)
ax.set_ylabel("incidents / week")
ax.legend(loc="upper left", frameon=False, labelcolor=INK)

ax = axes[1]
draw(ax, series["fixed_panel"], AQUA, f"Fixed panel of {len(panel)} vendors")
ax.set_title(f"Fixed panel: {len(panel)} vendors publishing continuously since Q1 2015 "
             "(like-for-like trend)", loc="left", fontsize=11, color=INK)
ax.set_ylabel("incidents / week")
ax.legend(loc="upper left", frameon=False, labelcolor=INK)

ax = axes[2]
ax.step(x, [covered[w] for w in weeks], where="post", color=GRAY, lw=2)
ax.set_title("Vendors with published incident history that week (coverage)",
             loc="left", fontsize=11, color=INK)
ax.set_ylabel("vendors")
ax.set_ylim(0, 50)
ax.xaxis.set_major_locator(mdates.YearLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax.set_xlim(x[0], x[-1] + dt.timedelta(days=120))

for a in axes:
    a.set_ylim(bottom=0)
    a.tick_params(length=0)

fig.suptitle("Weekly publicly reported incidents: enterprise SaaS & cloud infrastructure, "
             "Jan 2015 – Nov 2026", x=0.07, ha="left", fontsize=14, color=INK, weight="bold")
fig.text(0.07, 0.935, "Vendor-published incidents from 47 Atlassian Statuspage status pages; "
         "scheduled maintenance excluded. Thin line = weekly count, thick = 13-week average.",
         fontsize=9.5, color=INK2)
fig.text(0.07, 0.03, "Not covered: AWS, Azure, Google Cloud, Microsoft 365, Salesforce, Slack, "
         "Cloudflare, Datadog, Okta (no public multi-year archive). Source & method: see README.",
         fontsize=8.5, color=INK2)
fig.savefig(ROOT / "incidents_weekly.png", dpi=150, bbox_inches="tight")
print(f"weeks={len(weeks)} incidents={len(rows)} panel={panel}")
