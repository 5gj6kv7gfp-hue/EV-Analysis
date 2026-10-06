"""Who is requesting 2026 mail ballots? Voter-history profile of requesters, by party and precinct lean.

Joins the 2026 absentee-by-mail list to the countywide voter file (LOCAL_ID = COUNTY ID) and
classifies every registrant by midterm vote history:

  New since 2022     registered after the 2022 general (Nov 8, 2022)
  Skipped 2022       registered in time for 2022 but did not vote in it
  Voted 2022 only    voted in 2022 but not 2018 (including registered after the 2018 general)
  Voted 2018 & 2022  habitual midterm voter

Party is the *pre-2026* affiliation: the most recent D or R primary ballot before 2026. Using
the current code would be circular, since taking a 2026 primary ballot is itself a sign of
engagement, and Franklin's 2026 primary drew 122k D ballots vs 50k R.

Outputs: data/processed/propensity_2026_*.csv, output/propensity_*.png, output/propensity_summary.json
"""
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from analyze_franklin import (BLUE, INK, INK2, OUT, PROC, RAW, RED,  # noqa: E402
                              norm_precinct, style)

GEN_2018 = "2018 GENERAL ELECTION 11/6/2018"
GEN_2022 = "2022 GENERAL ELECTION"
PRI_2026 = "2026 PRIMARY ELECTION"
TIERS = ["New since 2022", "Skipped 2022", "Voted 2022 only", "Voted 2018 & 2022"]
TIER_COLORS = ["#86b6ef", "#5598e7", "#256abf", "#104281"]  # ordinal blue ramp, light -> dark
PARTY_NAMES = {"D": "Democratic", "R": "Republican", "U": "No party primary"}


def load():
    cols = pd.read_csv(RAW / "fc_voterfile_2026.txt", sep="\t", nrows=0, encoding="latin1").columns
    primaries = [c for c in cols if "PRIMARY" in c.upper() and not c.startswith("2026")]  # newest first
    v = pd.read_csv(RAW / "fc_voterfile_2026.txt", sep="\t", dtype=str, encoding="latin1",
                    usecols=["COUNTY ID", "REGISTERED", "STATUS", "PRECINCT NAME WITH SPLIT",
                             GEN_2018, GEN_2022, PRI_2026, *primaries])
    reg = pd.to_datetime(v.REGISTERED, format="%m/%d/%Y", errors="coerce")
    voted18, voted22 = v[GEN_2018].notna(), v[GEN_2022].notna()
    v["tier"] = np.select(
        [reg > "2022-11-08", ~voted22, voted22 & ~voted18],
        TIERS[:3], default=TIERS[3])
    party = pd.Series("U", index=v.index)
    for c in reversed(primaries):  # oldest first, so newer primaries overwrite
        party = party.mask(v[c].isin(["D", "R"]), v[c])
    v["party_pre2026"] = party
    v["voted_2026_primary"] = v[PRI_2026].notna()
    v["precinct"] = v["PRECINCT NAME WITH SPLIT"].str.replace(r"\s+\d+$", "", regex=True).map(norm_precinct)

    a = pd.read_csv(RAW / "fc_abs_mail_2026.txt", sep="\t", dtype=str, encoding="latin1",
                    usecols=["LOCAL_ID"])
    v["requested"] = v["COUNTY ID"].isin(set(a.LOCAL_ID))
    lean = pd.read_csv(PROC / "franklin_precinct_vbm_2022_2026.csv", usecols=["precinct", "lean_bin"])
    v = v.merge(lean, on="precinct", how="left")
    return v[["tier", "party_pre2026", "voted_2026_primary", "requested", "lean_bin", "STATUS"]], \
        len(a), int(v.requested.sum())


def pct_table(d, by):
    t = pd.crosstab(d[by], d.tier, normalize="index").reindex(columns=TIERS) * 100
    t["requesters"] = d.groupby(by).size()
    return t


def main():
    v, n_requests, n_matched = load()
    req = v[v.requested]

    comp_party = pct_table(req, "party_pre2026").reindex(["D", "R", "U"])
    comp_lean = pct_table(req.dropna(subset=["lean_bin"]), "lean_bin")
    comp_all = pct_table(req.assign(all="All requesters"), "all")
    comp_pool = pct_table(v.assign(all="All registrants"), "all")

    rate = (v.groupby(["tier", "party_pre2026"]).requested.agg(["sum", "count"])
            .rename(columns={"sum": "requests", "count": "registrants"}))
    rate["request_rate_pct"] = 100 * rate.requests / rate.registrants
    rate = rate.reset_index()
    wide_rate = rate.pivot(index="tier", columns="party_pre2026", values="request_rate_pct").reindex(TIERS)
    wide_rate["R_to_D_ratio"] = wide_rate.R / wide_rate.D

    lean_order = ["<40% D", "40-50% D", "50-60% D", "60-70% D", "70-80% D", "80%+ D"]
    lean_rate = (v.dropna(subset=["lean_bin"]).groupby(["lean_bin", "tier"]).requested.mean()
                 .unstack().reindex(index=lean_order, columns=TIERS) * 100)
    # Request rate of low-propensity voters relative to habitual voters in the same precincts:
    # isolates activation of infrequent voters from the overall mail habits of an area.
    lean_rate["skipped_vs_habitual"] = lean_rate["Skipped 2022"] / lean_rate["Voted 2018 & 2022"]
    lean_rate["new_vs_habitual"] = lean_rate["New since 2022"] / lean_rate["Voted 2018 & 2022"]
    lean_rate.to_csv(PROC / "propensity_2026_request_rates_by_lean.csv", float_format="%.3f")

    prim = (req.groupby(["party_pre2026", "tier"]).voted_2026_primary.mean() * 100).unstack().reindex(
        index=["D", "R", "U"], columns=TIERS)

    comp = pd.concat([comp_all, comp_pool, comp_party.rename(index=lambda p: f"{PARTY_NAMES[p]} requesters"),
                      comp_lean.rename(index=lambda b: f"Precinct {b}")])
    comp.to_csv(PROC / "propensity_2026_composition.csv", float_format="%.2f")
    rate.to_csv(PROC / "propensity_2026_request_rates.csv", index=False, float_format="%.3f")
    prim.to_csv(PROC / "propensity_2026_primary_participation.csv", float_format="%.2f")

    low = lambda t: float(t[TIERS[0]] + t[TIERS[1]])  # noqa: E731  new + skipped 2022
    summary = {
        "requests_in_list": n_requests, "requests_matched_to_voter_file": n_matched,
        "pct_requesters_new_or_skipped_2022": round(low(comp_all.iloc[0]), 1),
        "pct_registrants_new_or_skipped_2022": round(low(comp_pool.iloc[0]), 1),
        "pct_new_or_skipped_by_party": {p: round(low(comp_party.loc[p]), 1) for p in ["D", "R", "U"]},
        "request_rate_pct_by_tier_party": wide_rate.round(2).to_dict(orient="index"),
        "request_rate_pct_by_lean_tier": lean_rate.round(3).to_dict(orient="index"),
    }
    (OUT / "propensity_summary.json").write_text(json.dumps(summary, indent=2))
    charts(comp_party, comp_all, comp_pool, wide_rate)

    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(json.dumps({k: summary[k] for k in list(summary)[:5]}, indent=2))
        print(comp.round(1))
        print(wide_rate.round(2))
        print(prim.round(1))
        print(lean_rate.round(2))


def charts(comp_party, comp_all, comp_pool, wide_rate):
    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK, "axes.labelcolor": INK2})

    # 1. 100% stacked composition by vote-history tier
    rows = pd.concat([comp_pool, comp_all,
                      comp_party.rename(index=lambda p: f"{PARTY_NAMES[p]} requesters")])
    labels = ["All registrants", "All requesters", *[f"{PARTY_NAMES[p]} requesters" for p in ["D", "R", "U"]]]
    rows = rows.loc[labels]
    fig, ax = plt.subplots(figsize=(8.5, 3.6), dpi=150)
    y = np.arange(len(rows))[::-1]
    left = np.zeros(len(rows))
    for tier, color in zip(TIERS, TIER_COLORS):
        vals = rows[tier].values
        ax.barh(y, vals, left=left, color=color, edgecolor="white", linewidth=1.5, height=0.62, label=tier)
        for yi, l, val in zip(y, left, vals):
            if val >= 6:
                ax.text(l + val / 2, yi, f"{val:.0f}%", ha="center", va="center", fontsize=8,
                        color="white" if tier != TIERS[0] else INK)
        left += vals
    ax.set_yticks(y, [f"{lab}  (n={int(n):,})" for lab, n in zip(labels, rows.requesters)], fontsize=8.5)
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of group")
    ax.set_title("2026 mail requesters by midterm vote history", loc="left", fontsize=11, color=INK, pad=26)
    ax.legend(frameon=False, fontsize=8, ncol=4, loc="lower left", bbox_to_anchor=(0, 1.0))
    style(ax)
    ax.grid(False)
    fig.tight_layout()
    fig.savefig(OUT / "propensity_composition.png")
    plt.close(fig)

    # 2. Request rate by tier, D vs R (pre-2026 affiliation)
    fig, ax = plt.subplots(figsize=(8, 3.8), dpi=150)
    x = np.arange(len(TIERS))
    w = 0.38
    for off, p, color in [(-w / 2 - 0.01, "D", BLUE), (w / 2 + 0.01, "R", RED)]:
        bars = ax.bar(x + off, wide_rate[p], w, color=color, label=f"{PARTY_NAMES[p]} (last primary before 2026)")
        for r in bars:
            ax.text(r.get_x() + r.get_width() / 2, r.get_height() + 0.3, f"{r.get_height():.1f}%",
                    ha="center", fontsize=8, color=INK2)
    ax.set_xticks(x, TIERS, fontsize=9)
    ax.set_ylabel("% of registrants who requested")
    ax.set_ylim(0, np.nanmax(wide_rate[["D", "R"]].values) * 1.18)
    ax.set_title("2026 mail-ballot request rate by vote history and party", loc="left", fontsize=11, color=INK)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    style(ax)
    fig.tight_layout()
    fig.savefig(OUT / "propensity_request_rate.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
