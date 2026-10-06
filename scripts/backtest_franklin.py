"""Backtest: do precinct-level shifts in vote-by-mail predict election outcomes in Franklin County?

For each pair of consecutive comparable elections (midterm->midterm, presidential->presidential),
we measure the same "mail tilt" statistic used for 2022->2026 and compare it with what actually
happened to turnout composition and the final two-party result.

Statistics per pair (baseline year A -> target year B, matched precincts):
  mail_tilt        Reweight precinct D share of A's *mail* vote by B's mail ballots instead of A's.
                   (The 2022->2026 analysis's "composition shift".) Pure geography of mail.
  turnout_tilt     Same reweighting for *all* ballots, using precinct D share of A's total vote.
                   The geographic part of the real turnout shift.
  actual_swing     Change in county D two-party share of the top-of-ticket race, A -> B.
  rho_mail_total   Spearman corr across precincts of dlog(mail ballots) vs dlog(total ballots):
                   does a precinct's mail change track its turnout change?
  rho_mail_swing   Spearman corr of dlog(mail ballots) vs change in precinct D share.

Inputs: data/raw/fc_{year}gen_precinct_group.xlsx for 2014-2024 (see README for URLs).
Outputs: data/processed/backtest_pairs.csv, data/processed/backtest_years.csv,
         output/backtest_tilts.png
"""
import pathlib
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import openpyxl  # noqa: E402
import pandas as pd  # noqa: E402

from analyze_franklin import BLUE, GRAY, GRID, INK, INK2, RAW, OUT, PROC, norm_precinct, style  # noqa: E402

# Wide-format years: sheet, header row index for race / candidate / vote-type, name column,
# first data row, D and R candidate name fragments, and the mail / total vote-type labels.
WIDE = {
    2014: dict(sheet="General 2014", race=1, cand=2, vtype=3, name=1, data=5,
               d="FitzGerald", r="Kasich", mail="ABSENTEE MAIL", total="TOTAL VOTE",
               ballots="BALLOTS CAST TOTAL", reg_col=10),
    2016: dict(sheet="GEN2016", race=1, cand=2, vtype=4, name=1, data=5,
               d="Hillary Clinton", r="Trump", mail="Absentee Paper", total="Total Vote",
               ballots="BALLOTS CAST", reg_col=12),
    2018: dict(sheet="UNITYTOTALS", race=0, cand=1, vtype=3, name=1, data=4,
               d="Cordray", r="DeWine", mail="Absentee Paper", total="Total Vote",
               ballots="BALLOTS CAST", reg_col=12),
    2020: dict(sheet="Election Result 2020 With Dist", race=0, cand=1, vtype=4, name=25, data=5,
               d="Biden", r="Trump", mail="Absentee", total="TOTAL",
               ballots="BALLOTS CAST", reg_col=27),
}
# Long-format years (one row per precinct x vote-type group: mail, in-office, election day,
# provisional). Columns: name, registered, ballots, then D and R top-of-ticket columns.
LONG = {
    2022: dict(d="Whaley", r="DeWine"),
    2024: dict(d="Harris", r="Trump"),
}
TOP = {2014: "Governor", 2016: "President", 2018: "Governor", 2020: "President",
       2022: "Governor", 2024: "President"}
PAIRS = [(2014, 2018), (2018, 2022), (2016, 2020), (2020, 2024)]


def strip_split(name):
    return re.sub(r"\s+\d+$", "", str(name).strip())


def load_wide(year):
    cfg = WIDE[year]
    ws = openpyxl.load_workbook(RAW / f"fc_{year}gen_precinct_group.xlsx", read_only=True)[cfg["sheet"]]
    rows = list(ws.iter_rows(values_only=True))
    hdr = rows[:cfg["data"]]
    ncol = len(hdr[0])

    def ffill(r):
        out, cur = [], None
        for c in range(ncol):
            v = hdr[r][c]
            if v is not None and str(v).strip():
                cur = str(v).strip()
            out.append(cur)
        return out

    race, cand, vt = ffill(cfg["race"]), ffill(cfg["cand"]), [
        (str(v).strip() if v is not None else None) for v in hdr[cfg["vtype"]]]
    # Some years put the "BALLOTS CAST" label on the candidate row rather than the race row.
    race = [c if c and c.upper().startswith("BALLOTS") else r for r, c in zip(race, cand)]

    def col(race_pred, cand_pred, vtype):
        hits = [c for c in range(ncol) if race_pred(race[c] or "") and cand_pred(cand[c] or "")
                and vt[c] == vtype]
        return hits[0]

    is_top = lambda s: s.startswith(TOP[year])  # noqa: E731
    any_ = lambda s: True  # noqa: E731
    is_ballots = lambda s: s.upper().startswith(cfg["ballots"].upper())  # noqa: E731
    cols = {
        "mail_ballots": col(is_ballots, any_, cfg["mail"]),
        "total_ballots": col(is_ballots, any_, cfg["total"]),
        "d_mail": col(is_top, lambda s: cfg["d"] in s, cfg["mail"]),
        "d_total": col(is_top, lambda s: cfg["d"] in s, cfg["total"]),
        "r_mail": col(is_top, lambda s: cfg["r"] in s, cfg["mail"]),
        "r_total": col(is_top, lambda s: cfg["r"] in s, cfg["total"]),
        "reg": cfg["reg_col"],
    }
    recs = []
    for r in rows[cfg["data"]:]:
        nm = r[cfg["name"]]
        if not nm or not re.match(r"^[A-Za-z]", str(nm)) or "TOTAL" in str(nm).upper():
            continue
        # 2014 appends precinct subtotals and polling-location rollups after the split rows;
        # keep only split rows (code like "01001A-1") so nothing is double counted.
        if year == 2014 and not re.match(r"^\d{5}[A-Z]{1,2}-\d+$", str(r[2] or "")):
            continue
        recs.append({"precinct": norm_precinct(strip_split(nm)),
                     **{k: pd.to_numeric(r[c], errors="coerce") for k, c in cols.items()}})
    return pd.DataFrame(recs).groupby("precinct").sum(min_count=1).reset_index()


def load_long(year):
    cfg = LONG[year]
    x = pd.read_excel(RAW / f"fc_{year}gen_precinct_group.xlsx", header=None)
    cand_row = x.iloc[2].astype(str)
    dcol = cand_row[cand_row.str.contains(cfg["d"])].index[0]
    rcol = cand_row[cand_row.str.contains(cfg["r"])].index[0]
    x = x.iloc[3:]
    x = x[x[2].astype(str).str.match(r"^[A-Z][A-Z .]+[ -]") &
          ~x[2].astype(str).str.contains("County|COUNTY")].copy()
    x["g"] = x.groupby(1).cumcount()
    num = lambda s: pd.to_numeric(s, errors="coerce")  # noqa: E731
    x["precinct"] = x[2].map(norm_precinct)
    x["ballots"], x["d"], x["r"], x["reg"] = num(x[4]), num(x[dcol]), num(x[rcol]), num(x[3])
    tot = x.groupby("precinct").agg(total_ballots=("ballots", "sum"), d_total=("d", "sum"),
                                    r_total=("r", "sum"), reg=("reg", "first"))
    mail = x[x.g == 0].groupby("precinct").agg(mail_ballots=("ballots", "sum"),
                                               d_mail=("d", "sum"), r_mail=("r", "sum"))
    return tot.join(mail).reset_index()


def load(year):
    d = load_wide(year) if year in WIDE else load_long(year)
    d["dshare"] = 100 * d.d_total / (d.d_total + d.r_total)
    d["dshare_mail"] = 100 * d.d_mail / (d.d_mail + d.r_mail)
    return d


def year_summary(y, d):
    return {
        "year": y, "race": TOP[y], "precincts": len(d),
        "total_ballots": int(d.total_ballots.sum()), "mail_ballots": int(d.mail_ballots.sum()),
        "mail_pct_of_ballots": round(100 * d.mail_ballots.sum() / d.total_ballots.sum(), 1),
        "d_share_overall": round(100 * d.d_total.sum() / (d.d_total.sum() + d.r_total.sum()), 2),
        "d_share_mail": round(100 * d.d_mail.sum() / (d.d_mail.sum() + d.r_mail.sum()), 2),
    }


def pair_stats(a, b, ya, yb):
    m = a.merge(b, on="precinct", suffixes=("_a", "_b"))
    m = m[(m.mail_ballots_a > 0) & (m.total_ballots_a > 0) & (m.total_ballots_b > 0)]
    m = m[(m.reg_b / m.reg_a).between(0.67, 1.5)]  # stable boundaries only
    m = m.dropna(subset=["dshare_a", "dshare_mail_a", "dshare_b"])
    wavg = lambda x, w: float(np.average(x, weights=w))  # noqa: E731
    mail_base = wavg(m.dshare_mail_a, m.mail_ballots_a)
    tot_base = wavg(m.dshare_a, m.total_ballots_a)
    dlog_mail = np.log((m.mail_ballots_b + .5) / (m.mail_ballots_a + .5))
    dlog_tot = np.log(m.total_ballots_b / m.total_ballots_a)
    swing = m.dshare_b - m.dshare_a
    county = lambda d, r: 100 * d.sum() / (d.sum() + r.sum())  # noqa: E731
    return {
        "pair": f"{ya}->{yb}", "matched_precincts": len(m),
        "mail_tilt_pts": round(wavg(m.dshare_mail_a, m.mail_ballots_b) - mail_base, 2),
        "turnout_tilt_pts": round(wavg(m.dshare_a, m.total_ballots_b) - tot_base, 2),
        "actual_swing_pts": round(county(m.d_total_b, m.r_total_b) - county(m.d_total_a, m.r_total_a), 2),
        "mail_ballot_growth": round(m.mail_ballots_b.sum() / m.mail_ballots_a.sum(), 3),
        "rho_mail_vs_turnout_change": round(pd.Series(dlog_mail).corr(pd.Series(dlog_tot), method="spearman"), 3),
        "rho_mail_change_vs_swing": round(pd.Series(dlog_mail).corr(swing, method="spearman"), 3),
        "rho_lean_vs_mail_change": round(m.dshare_a.corr(dlog_mail, method="spearman"), 3),
        "rho_lean_vs_turnout_change": round(m.dshare_a.corr(dlog_tot, method="spearman"), 3),
    }


def chart(pairs, current):
    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK, "axes.labelcolor": INK2})
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    labels = list(pairs.pair) + ["2022->2026\n(requests to date)"]
    mail = list(pairs.mail_tilt_pts) + [current]
    turn = list(pairs.turnout_tilt_pts) + [np.nan]
    x = np.arange(len(labels))
    w = 0.38
    ax.bar(x - w / 2 - 0.01, mail, w, color=BLUE, label="Mail tilt (geography of mail ballots)")
    ax.bar(x + w / 2 + 0.01, turn, w, color=GRAY, label="Turnout tilt (geography of all ballots)")
    for i, (m, t) in enumerate(zip(mail, turn)):
        ax.text(i - w / 2, m + (0.12 if m >= 0 else -0.12), f"{m:+.1f}", ha="center",
                va="bottom" if m >= 0 else "top", fontsize=8, color=INK2)
        if not np.isnan(t):
            ax.text(i + w / 2, t + (0.12 if t >= 0 else -0.12), f"{t:+.1f}", ha="center",
                    va="bottom" if t >= 0 else "top", fontsize=8, color=INK2)
    ax.axhline(0, color=INK2, linewidth=0.8)
    ax.set_xticks(x, labels, fontsize=8.5)
    ax.set_ylabel("Shift in implied D two-party share (pts)")
    ax.set_title("Did the geography of mail ballots foreshadow the geography of turnout?",
                 loc="left", fontsize=11, color=INK, pad=28)
    lim = np.nanmax(np.abs(mail + turn)) * 1.35
    ax.set_ylim(-lim, lim)
    ax.legend(frameon=False, fontsize=8.5, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
    style(ax)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    fig.tight_layout()
    fig.savefig(OUT / "backtest_tilts.png")
    plt.close(fig)


def main():
    years = sorted(set(y for p in PAIRS for y in p))
    data = {y: load(y) for y in years}
    ys = pd.DataFrame([year_summary(y, data[y]) for y in years])
    ys["mail_minus_overall_d"] = (ys.d_share_mail - ys.d_share_overall).round(2)
    pairs = pd.DataFrame([pair_stats(data[a], data[b], a, b) for a, b in PAIRS])
    ys.to_csv(PROC / "backtest_years.csv", index=False)
    pairs.to_csv(PROC / "backtest_pairs.csv", index=False)
    import json
    current = json.loads((OUT / "summary.json").read_text())["composition_shift_pts"]
    chart(pairs, current)
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(ys.to_string(index=False))
        print(pairs.to_string(index=False))


if __name__ == "__main__":
    main()
