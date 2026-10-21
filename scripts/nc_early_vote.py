"""North Carolina: is the early vote informative? Same-day comparison for 2026 and a 2014-2024 backtest.

NC publishes a statewide voter-level absentee file for every general election (mail and
one-stop/early in-person), with party registration and request/return dates. The final file
for each past election contains every return date, so the electorate "as of N days before
Election Day" can be rebuilt for any year. During an election the public file only lists
*returned* ballots (requests are confidential until returned), so returns are the
comparable measure.

Steps:
  1. For each year, download the absentee zip, reduce it to daily returned-ballot counts by
     party x method x days-before-election, and delete the raw CSV (the files are large).
  2. Pull precinct results (results_pct) and compute the statewide top-race D two-party share
     overall and among mail ballots.
  3. Compare 2026 returns at its current day-before-election with every past year at the same
     point, and test whether early-return partisanship tracked final outcomes.

Outputs: data/processed/nc_returns_daily.csv, nc_results.csv, nc_backtest.csv,
         output/nc_early_margin_vs_result.png
"""
import datetime as dt
import io
import pathlib
import sys
import zipfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from analyze_franklin import BLUE, GRAY, INK, INK2, OUT, PROC, RED, style  # noqa: E402

RAW = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw" / "nc"
S3 = "https://s3.amazonaws.com/dl.ncsbe.gov/ENRS/"
ELECTIONS = {
    2014: "2014-11-04", 2016: "2016-11-08", 2018: "2018-11-06", 2020: "2020-11-03",
    2022: "2022-11-08", 2024: "2024-11-05", 2026: "2026-11-03",
}
# Top-of-ticket statewide partisan race. 2018 had no Senate/governor race; the statewide
# Supreme Court seat (Earls-D vs two Republicans) is used, combining both R candidates.
TOP_RACE = {2014: "US SENATE", 2016: "US PRESIDENT", 2018: "NC SUPREME COURT ASSOCIATE JUSTICE",
            2020: "US PRESIDENT", 2022: "US SENATE", 2024: "US PRESIDENT"}
ACCEPTED_PREFIX = ("ACCEPTED",)
PARTY = {"DEM": "D", "REP": "R"}  # everything else (UNA, LIB, GRE, ...) -> U


def tag(year):
    return ELECTIONS[year].replace("-", "_")


def fetch(url, dest):
    if not dest.exists():
        r = requests.get(url, timeout=1800)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


def daily_returns(year):
    """Daily accepted returned-ballot counts by party, method and days before Election Day."""
    cache = RAW / f"returns_daily_{year}.csv"
    if cache.exists():
        return pd.read_csv(cache)
    RAW.mkdir(parents=True, exist_ok=True)
    zpath = fetch(f"{S3}{tag(year)}/absentee_{tag(year).replace('_', '')}.zip",
                  RAW / f"absentee_{year}.zip")
    eday = pd.Timestamp(ELECTIONS[year])
    cols = ["voter_party_code", "ballot_req_type", "ballot_rtn_dt", "ballot_rtn_status"]
    parts = []
    with zipfile.ZipFile(zpath) as z:
        name = [n for n in z.namelist() if n.endswith(".csv")][0]
        with z.open(name) as f:
            for chunk in pd.read_csv(io.TextIOWrapper(f, encoding="latin1"), usecols=cols,
                                     dtype=str, chunksize=500_000):
                chunk = chunk[chunk.ballot_rtn_status.fillna("").str.strip().str.startswith(ACCEPTED_PREFIX)]
                rtn = pd.to_datetime(chunk.ballot_rtn_dt, format="%m/%d/%Y", errors="coerce")
                chunk = chunk.assign(
                    days_before=(eday - rtn).dt.days,
                    party=chunk.voter_party_code.str.strip().map(PARTY).fillna("U"),
                    method=chunk.ballot_req_type.str.strip().replace({"ONE-STOP": "EARLY_IN_PERSON"}))
                parts.append(chunk.dropna(subset=["days_before"])
                             .groupby(["method", "party", "days_before"]).size())
    out = (pd.concat(parts).groupby(level=[0, 1, 2]).sum().rename("ballots").reset_index()
           .assign(year=year))
    out.to_csv(cache, index=False)
    if year != 2026:
        zpath.unlink()  # raw past-year zips are 40-240 MB each; the daily table is all we need
    return out


def results(year):
    zpath = fetch(f"{S3}{tag(year)}/results_pct_{tag(year).replace('_', '')}.zip",
                  RAW / f"results_pct_{year}.zip")
    with zipfile.ZipFile(zpath) as z:
        name = [n for n in z.namelist() if n.endswith(".txt") or n.endswith(".csv")][0]
        r = pd.read_csv(z.open(name), sep="\t", dtype=str, encoding="latin1")
    r.columns = [c.strip() for c in r.columns]
    contest = r["Contest Name"].str.upper().str.strip()
    r = r[contest.str.startswith(TOP_RACE[year])]
    if year == 2018:  # three seats? keep the one Earls ran in
        seat = r.loc[r.Choice.str.contains("Earls", case=False), "Contest Name"].iloc[0]
        r = r[r["Contest Name"] == seat]
    party = r["Choice Party"].str.strip().map(PARTY)
    mail_col = [c for c in r.columns if c.lower().startswith("absentee")][0]
    tot = pd.to_numeric(r["Total Votes"], errors="coerce")
    mail = pd.to_numeric(r[mail_col], errors="coerce")
    g = pd.DataFrame({"party": party, "tot": tot, "mail": mail}).dropna(subset=["party"]).groupby("party").sum()
    return {"year": year, "contest": r["Contest Name"].iloc[0],
            "d_share_result": 100 * g.tot["D"] / (g.tot["D"] + g.tot["R"]),
            "d_share_mail_vote": 100 * g.mail["D"] / (g.mail["D"] + g.mail["R"]),
            "total_two_party_votes": int(g.tot.sum())}


def snapshot(daily, year, days_before):
    d = daily[(daily.year == year) & (daily.days_before >= days_before)]
    by = d.groupby("party").ballots.sum().reindex(["D", "R", "U"], fill_value=0)
    n = by.sum()
    return {"returns": int(n), "pct_D": 100 * by.D / n, "pct_R": 100 * by.R / n, "pct_U": 100 * by.U / n,
            "D_minus_R_pts": 100 * (by.D - by.R) / n, "D": int(by.D), "R": int(by.R), "U": int(by.U)}


def main():
    years = list(ELECTIONS)
    daily = pd.concat([daily_returns(y) for y in years], ignore_index=True)
    # Labels changed over the years: 2014 splits mail by voter type; 2024 renamed one-stop.
    daily["method"] = daily.method.replace({"CIVILIAN": "MAIL", "MILITARY": "MAIL", "OVERSEAS": "MAIL",
                                            "EARLY VOTING": "EARLY_IN_PERSON"})
    daily = daily.groupby(["year", "method", "party", "days_before"], as_index=False).ballots.sum()
    daily.to_csv(PROC / "nc_returns_daily.csv", index=False)
    res = pd.DataFrame([results(y) for y in years if y != 2026])
    res.to_csv(PROC / "nc_results.csv", index=False)

    # 2026 data is current to the latest day with real volume; a handful of records carry
    # mis-keyed future return dates and must not set the cutoff.
    cur = daily[daily.year == 2026].groupby("days_before").ballots.sum()
    now = int(cur[cur >= 100].index.min())
    rows = []
    for y in years:
        early = snapshot(daily, y, now)
        final_mail = snapshot(daily[daily.method == "MAIL"], y, -60)
        final_all = snapshot(daily, y, -60)
        rows.append({"year": y, "days_before": now,
                     **{f"early_{k}": v for k, v in early.items()},
                     "final_mail_returns": final_mail["returns"],
                     "final_mail_D_minus_R_pts": final_mail["D_minus_R_pts"],
                     "final_all_early_returns": final_all["returns"],
                     "final_all_D_minus_R_pts": final_all["D_minus_R_pts"]})
    bt = pd.DataFrame(rows).merge(res, on="year", how="left")
    bt.loc[bt.year == 2026, ["final_mail_returns", "final_mail_D_minus_R_pts", "final_all_early_returns",
                             "final_all_D_minus_R_pts"]] = np.nan  # 2026 isn't final
    bt["early_pct_of_final_mail"] = 100 * bt.early_returns / bt.final_mail_returns
    bt["early_pct_of_total_vote"] = 100 * bt.early_returns / bt.total_two_party_votes
    bt.to_csv(PROC / "nc_backtest.csv", index=False, float_format="%.2f")

    past = bt[bt.year != 2026]
    mid = past[past.year.isin([2014, 2018, 2022])]
    print(f"2026 data through {now} days before Election Day")
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(bt[["year", "early_returns", "early_pct_D", "early_pct_R", "early_pct_U", "early_D_minus_R_pts",
                  "final_mail_D_minus_R_pts", "final_all_D_minus_R_pts", "d_share_result",
                  "d_share_mail_vote", "early_pct_of_final_mail", "early_pct_of_total_vote"]].round(2).to_string(index=False))
    for lab, d in [("all", past), ("midterms", mid)]:
        print(lab, "corr(early D-R margin, result D share) =",
              round(d.early_D_minus_R_pts.corr(d.d_share_result), 3), "n =", len(d))
    chart(bt)


def chart(bt):
    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK, "axes.labelcolor": INK2})
    fig, ax = plt.subplots(figsize=(8, 4.4), dpi=150)
    past = bt[bt.year != 2026]
    ax.scatter(past.early_D_minus_R_pts, past.d_share_result, s=70, color=BLUE, edgecolor="white",
               linewidth=1.5, zorder=3)
    for _, r in past.iterrows():
        ax.annotate(f"{r.year}", (r.early_D_minus_R_pts, r.d_share_result), xytext=(7, -3),
                    textcoords="offset points", fontsize=8.5, color=INK2)
    cur = bt[bt.year == 2026].iloc[0]
    ax.axvline(cur.early_D_minus_R_pts, color=RED, linewidth=1.5, linestyle="--")
    ax.text(cur.early_D_minus_R_pts, ax.get_ylim()[1], f" 2026 so far: D{cur.early_D_minus_R_pts:+.0f}",
            color=INK, fontsize=8.5, va="top")
    ax.axhline(50, color=GRAY, linewidth=0.8)
    ax.set_xlabel(f"Accepted ballots returned by {int(cur.days_before)} days out: "
                  "registered D minus R (pts of returns)")
    ax.set_ylabel("Final D two-party share, top race (%)")
    ax.set_title("NC: early party margin vs. the eventual result", loc="left", fontsize=11, color=INK)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "nc_early_margin_vs_result.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
