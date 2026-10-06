"""Franklin County, OH: precinct-level vote-by-mail, 2022 General vs 2026 General, by partisanship.

Inputs (data/raw, produced by fetch_franklin.py):
  fc_2022gen_precinct_group.xlsx  2022 General official results, one row per precinct x
                                  vote-type group (mail absentee, in-office absentee,
                                  election day, provisional)
  fc_abs_mail_2026.txt            2026 General absentee-by-mail list (one row per request)
  fc_voterfile_2026.txt           current countywide voter file

Outputs:
  data/processed/franklin_precinct_vbm_2022_2026.csv   precinct table
  data/processed/franklin_vbm_by_lean.csv              summary by 2022 precinct lean
  data/processed/franklin_vbm_by_party_2026.csv        2026 request rates by party affiliation
  output/*.png                                         charts
  output/summary.json                                  headline numbers
"""
import json
import pathlib
import re

import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, PROC, OUT = ROOT / "data" / "raw", ROOT / "data" / "processed", ROOT / "output"

# 2022 results spell out municipality names; 2026 files abbreviate them.
ABBREV = {
    "COLUMBUS": "COLS", "CANAL WINCHESTER": "CANAL WIN", "DUBLIN": "DUB", "GAHANNA": "GAH",
    "HILLIARD": "HILL", "REYNOLDSBURG": "REYNS", "UPPER ARLINGTON": "UA", "WORTHINGTON": "WORTH",
}
GROUPS = ["mail", "in_office", "election_day", "provisional"]  # row order within each precinct
LEAN_BINS = [0, 40, 50, 60, 70, 80, 100.01]
LEAN_LABELS = ["<40% D", "40-50% D", "50-60% D", "60-70% D", "70-80% D", "80%+ D"]

BLUE, RED, GRAY = "#2a78d6", "#e34948", "#a3a29c"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def norm_precinct(name):
    """'COLUMBUS 01-A' / 'COLS 1-A' / 'COLS 01-A 01' -> 'COLS 1-A'."""
    s = re.sub(r"\s+", " ", str(name).strip().upper())
    for full, ab in ABBREV.items():
        if s.startswith(full + " ") or s.startswith(full + "-"):
            s = ab + s[len(full):]
    return re.sub(r"(?<=\s)0+(\d)", r"\1", s)


def load_2022():
    x = pd.read_excel(RAW / "fc_2022gen_precinct_group.xlsx", header=None, skiprows=3)
    x = x.rename(columns={1: "seq", 2: "name", 3: "reg22", 4: "ballots", 5: "dewine", 6: "whaley"})
    x = x[x["name"].astype(str).str.match(r"^[A-Z][A-Z .]+[ -]")]  # drop totals / other-county rows
    x = x[~x["name"].str.contains("County|COUNTY")].copy()
    x["group"] = x.groupby("seq").cumcount().map(dict(enumerate(GROUPS)))
    wide = x.pivot_table(index=["seq", "name", "reg22"], columns="group",
                         values=["ballots", "dewine", "whaley"], aggfunc="sum")
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]
    wide = wide.reset_index()
    out = pd.DataFrame({
        "precinct": wide["name"].map(norm_precinct),
        "precinct_name_2022": wide["name"],
        "reg_2022": wide["reg22"],
        "mail_ballots_2022": wide["ballots_mail"],
        "total_ballots_2022": wide[[f"ballots_{g}" for g in GROUPS]].sum(axis=1),
        "gov_d_2022": wide[[f"whaley_{g}" for g in GROUPS]].sum(axis=1),
        "gov_r_2022": wide[[f"dewine_{g}" for g in GROUPS]].sum(axis=1),
        "mail_gov_d_2022": wide["whaley_mail"],
        "mail_gov_r_2022": wide["dewine_mail"],
    })
    return out


def load_2026():
    a = pd.read_csv(RAW / "fc_abs_mail_2026.txt", sep="\t", dtype=str, encoding="latin1")
    a["precinct"] = a["PRECINCT_NAME"].map(norm_precinct)
    a["PARTY"] = a["PARTY"].fillna("U").str.strip().replace({"": "U"})
    a = a.drop_duplicates("LOCAL_ID")
    req = a.pivot_table(index="precinct", columns="PARTY", values="LOCAL_ID", aggfunc="count",
                        fill_value=0)
    req = req.reindex(columns=["D", "R", "U", "L"], fill_value=0)
    req.columns = [f"req26_{c}" for c in req.columns]
    req["requests_2026"] = req.sum(axis=1)
    asof = pd.to_datetime(a["DATE_REQUESTED"], errors="coerce").max()

    v = pd.read_csv(RAW / "fc_voterfile_2026.txt", sep="\t", dtype=str, encoding="latin1",
                    usecols=["STATE ID", "STATUS", "party", "PRECINCT NAME WITH SPLIT"])
    v["precinct"] = v["PRECINCT NAME WITH SPLIT"].str.replace(r"\s+\d+$", "", regex=True).map(norm_precinct)
    v["party"] = v["party"].fillna("U").str.strip().replace({"": "U"})
    reg = v.pivot_table(index="precinct", columns="party", values="STATE ID", aggfunc="count",
                        fill_value=0).reindex(columns=["D", "R", "U", "L"], fill_value=0)
    reg.columns = [f"reg26_{c}" for c in reg.columns]
    reg["reg_2026"] = reg.sum(axis=1)
    reg["reg_active_2026"] = v[v["STATUS"] == "ACT"].groupby("precinct").size()
    return req.join(reg, how="outer").fillna(0).reset_index(), asof, a, v


def wavg(x, w):
    return float(np.average(x, weights=w))


def main():
    PROC.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    p22 = load_2022()
    p26, asof, req_rows, voters = load_2026()

    df = p22.merge(p26, on="precinct", how="outer", indicator=True)
    match = df["_merge"].value_counts().to_dict()
    df = df[df["_merge"] == "both"].drop(columns="_merge").copy()

    df["gov_dshare_2022"] = 100 * df.gov_d_2022 / (df.gov_d_2022 + df.gov_r_2022)
    df["mail_gov_dshare_2022"] = 100 * df.mail_gov_d_2022 / (df.mail_gov_d_2022 + df.mail_gov_r_2022)
    df["aff_dshare_2026"] = 100 * df.reg26_D / (df.reg26_D + df.reg26_R)
    df["mail_rate_2022"] = 100 * df.mail_ballots_2022 / df.reg_2022
    df["req_rate_2026"] = 100 * df.requests_2026 / df.reg_2026
    # Boundary stability: registration should not swing wildly if the precinct is the same place.
    df["reg_ratio"] = df.reg_2026 / df.reg_2022
    df["stable"] = df.reg_ratio.between(0.67, 1.5)
    df["lean_bin"] = pd.cut(df.gov_dshare_2022, LEAN_BINS, labels=LEAN_LABELS, right=False)

    tot22, tot26 = df.mail_ballots_2022.sum(), df.requests_2026.sum()
    df["share_2022"] = 100 * df.mail_ballots_2022 / tot22
    df["share_2026"] = 100 * df.requests_2026 / tot26
    # >1: precinct's slice of the county's mail universe grew; <1: shrank.
    df["share_index"] = df.share_2026 / df.share_2022
    df["log_ratio"] = np.log((df.requests_2026 + 0.5) / (df.mail_ballots_2022 + 0.5))

    cols = ["precinct", "precinct_name_2022", "lean_bin", "gov_dshare_2022", "aff_dshare_2026",
            "reg_2022", "reg_2026", "stable", "mail_ballots_2022", "mail_rate_2022",
            "mail_gov_dshare_2022", "requests_2026", "req_rate_2026", "req26_D", "req26_R",
            "req26_U", "req26_L", "share_2022", "share_2026", "share_index"]
    df[cols].sort_values("precinct").to_csv(PROC / "franklin_precinct_vbm_2022_2026.csv",
                                            index=False, float_format="%.3f")

    # ---- summary by partisan lean -------------------------------------------------------
    def summarize(d):
        g = d.groupby("lean_bin", observed=True)
        s = pd.DataFrame({
            "precincts": g.size(),
            "reg_2022": g.reg_2022.sum(),
            "reg_2026": g.reg_2026.sum(),
            "mail_ballots_2022": g.mail_ballots_2022.sum(),
            "requests_2026": g.requests_2026.sum(),
            "req26_D": g.req26_D.sum(), "req26_R": g.req26_R.sum(), "req26_U": g.req26_U.sum(),
            "mail_gov_d_2022": g.mail_gov_d_2022.sum(), "mail_gov_r_2022": g.mail_gov_r_2022.sum(),
        })
        s["mail_rate_2022"] = 100 * s.mail_ballots_2022 / s.reg_2022
        s["req_rate_2026"] = 100 * s.requests_2026 / s.reg_2026
        s["share_2022"] = 100 * s.mail_ballots_2022 / s.mail_ballots_2022.sum()
        s["share_2026"] = 100 * s.requests_2026 / s.requests_2026.sum()
        s["share_change_pts"] = s.share_2026 - s.share_2022
        s["share_index"] = s.share_2026 / s.share_2022
        s["ratio_26req_to_22mail"] = s.requests_2026 / s.mail_ballots_2022
        s["mail_whaley_share_2022"] = 100 * s.mail_gov_d_2022 / (s.mail_gov_d_2022 + s.mail_gov_r_2022)
        s["req26_pct_D"] = 100 * s.req26_D / s.requests_2026
        s["req26_pct_R"] = 100 * s.req26_R / s.requests_2026
        s["req26_pct_U"] = 100 * s.req26_U / s.requests_2026
        return s

    by_lean = summarize(df)
    by_lean_stable = summarize(df[df.stable])
    by_lean.to_csv(PROC / "franklin_vbm_by_lean.csv", float_format="%.3f")
    by_lean_stable.to_csv(PROC / "franklin_vbm_by_lean_stable_precincts.csv", float_format="%.3f")

    # ---- 2026 requests by party affiliation (countywide, all precincts) ------------------
    reg_party = voters.party.value_counts()
    req_party = req_rows.PARTY.value_counts()
    by_party = pd.DataFrame({"registered_2026": reg_party, "requests_2026": req_party}).fillna(0)
    by_party["request_rate_pct"] = 100 * by_party.requests_2026 / by_party.registered_2026
    by_party["share_of_requests_pct"] = 100 * by_party.requests_2026 / by_party.requests_2026.sum()
    by_party.to_csv(PROC / "franklin_vbm_by_party_2026.csv", float_format="%.3f")

    # ---- precinct-level relationship -------------------------------------------------------
    def slope(d, x):
        w = d.mail_ballots_2022 + d.requests_2026
        b = np.polyfit(d[x], d.log_ratio, 1, w=np.sqrt(w))
        return float(b[0] * 10)  # change in log ratio per +10 pts D

    stable = df[df.stable]
    # Composition effect: what the 2022 mail electorate's governor vote would have been had mail
    # ballots come from precincts in 2026-request proportions (holding each precinct's 2022 mail
    # D share fixed). Isolates the geographic shift; says nothing about within-precinct change.
    has_mail = df[(df.mail_gov_d_2022 + df.mail_gov_r_2022) > 0]
    comp22 = wavg(has_mail.mail_gov_dshare_2022, has_mail.mail_ballots_2022)
    comp26 = wavg(has_mail.mail_gov_dshare_2022, has_mail.requests_2026)

    summary = {
        "as_of_latest_request_date_2026": str(asof.date()),
        "precinct_match": {"matched": int(match.get("both", 0)),
                           "only_2022": int(match.get("left_only", 0)),
                           "only_2026": int(match.get("right_only", 0)),
                           "stable_boundaries": int(df.stable.sum())},
        "county_mail_ballots_2022_matched": int(tot22),
        "county_requests_2026_matched": int(tot26),
        "county_ratio_26req_to_22mail": round(tot26 / tot22, 3),
        "spearman_lean_vs_log_ratio": round(df[["gov_dshare_2022", "log_ratio"]].corr("spearman").iloc[0, 1], 3),
        "spearman_lean_vs_log_ratio_stable": round(stable[["gov_dshare_2022", "log_ratio"]].corr("spearman").iloc[0, 1], 3),
        "weighted_slope_log_ratio_per_10pts_D_2022gov": round(slope(df, "gov_dshare_2022"), 4),
        "weighted_slope_log_ratio_per_10pts_D_2022gov_stable": round(slope(stable, "gov_dshare_2022"), 4),
        "weighted_slope_log_ratio_per_10pts_D_affiliation_2026": round(slope(df.dropna(subset=["aff_dshare_2026"]), "aff_dshare_2026"), 4),
        "mail_electorate_whaley_share_2022_actual": round(comp22, 2),
        "mail_electorate_whaley_share_reweighted_to_2026_requests": round(comp26, 2),
        "composition_shift_pts": round(comp26 - comp22, 2),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))

    charts(df, by_lean, by_party)
    print(json.dumps(summary, indent=2))
    with pd.option_context("display.width", 250, "display.max_columns", 40):
        print(by_lean.round(2).T)
        print(by_lean_stable[["precincts", "share_change_pts", "ratio_26req_to_22mail"]].round(3))
        print(by_party.round(2))


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def charts(df, by_lean, by_party):
    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK, "axes.labelcolor": INK2})

    # 1. Share of county mail universe, 2022 vs 2026, by precinct lean
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    x = np.arange(len(by_lean))
    w = 0.38
    b1 = ax.bar(x - w / 2 - 0.01, by_lean.share_2022, w, color=GRAY, label="2022 mail ballots cast (final)")
    b2 = ax.bar(x + w / 2 + 0.01, by_lean.share_2026, w, color=BLUE, label="2026 mail requests (to date)")
    for bars in (b1, b2):
        for r in bars:
            ax.text(r.get_x() + r.get_width() / 2, r.get_height() + 0.4, f"{r.get_height():.1f}",
                    ha="center", va="bottom", fontsize=8, color=INK2)
    ax.set_xticks(x, by_lean.index.astype(str))
    ax.set_xlabel("Precinct lean (Whaley two-party share, 2022 governor)")
    ax.set_ylabel("% of countywide total")
    ax.set_title("Where Franklin County's mail ballots come from, 2022 vs 2026", loc="left",
                 fontsize=11, color=INK)
    ax.set_ylim(0, by_lean[["share_2022", "share_2026"]].max().max() * 1.12)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "share_by_lean.png")
    plt.close(fig)

    # 2. Precinct scatter: lean vs 2026 requests per 2022 mail ballot
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=150)
    d = df[df.mail_ballots_2022 >= 20]
    ratio = d.requests_2026 / d.mail_ballots_2022
    ax.scatter(d.gov_dshare_2022, ratio, s=np.clip(d.mail_ballots_2022 / 6, 8, 80), color=BLUE,
               alpha=0.45, edgecolor="white", linewidth=0.6)
    xs = np.linspace(d.gov_dshare_2022.min(), d.gov_dshare_2022.max(), 50)
    b = np.polyfit(d.gov_dshare_2022, np.log(ratio.clip(lower=0.01)), 1,
                   w=np.sqrt(d.mail_ballots_2022 + d.requests_2026))
    ax.plot(xs, np.exp(np.polyval(b, xs)), color=INK, linewidth=2, label="Weighted log-linear fit")
    county = df.requests_2026.sum() / df.mail_ballots_2022.sum()
    ax.axhline(county, color=INK2, linewidth=1, linestyle="--")
    ax.text(xs.max(), county * 1.04, f"County overall: {county:.2f}", fontsize=8, color=INK2, ha="right")
    ax.set_yscale("log")
    ax.yaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_yticks([0.25, 0.5, 1, 2], ["0.25", "0.5", "1", "2"])
    ax.set_ylim(0.2, 3.2)
    ax.set_xlabel("Whaley two-party share in precinct, 2022 governor (%)")
    ax.set_ylabel("2026 requests ÷ 2022 mail ballots")
    ax.set_title("Precinct mail activity in 2026 relative to 2022 (dot size = 2022 mail ballots)",
                 loc="left", fontsize=11, color=INK)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "precinct_ratio_scatter.png")
    plt.close(fig)

    # 3. 2026 request rate by party affiliation
    bp = by_party.loc[[p for p in ["D", "R", "U"] if p in by_party.index]]
    fig, ax = plt.subplots(figsize=(6.5, 3.4), dpi=150)
    names = {"D": "Democratic", "R": "Republican", "U": "Unaffiliated"}
    colors = {"D": BLUE, "R": RED, "U": GRAY}
    bars = ax.bar([names[i] for i in bp.index], bp.request_rate_pct, 0.55,
                  color=[colors[i] for i in bp.index])
    for r, n in zip(bars, bp.requests_2026):
        ax.text(r.get_x() + r.get_width() / 2, r.get_height() + 0.25,
                f"{r.get_height():.1f}%  ({int(n):,})", ha="center", fontsize=8.5, color=INK2)
    ax.set_ylabel("% of registrants who requested")
    ax.set_title("2026 mail-ballot request rate by party affiliation", loc="left", fontsize=11, color=INK)
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "request_rate_by_party_2026.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
