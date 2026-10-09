"""Export the artifact data bundle and draw the static charts.

Outputs:
  output/qol_data.json        data embedded in the interactive page
  output/qol_vs_cost.png      static scatter, well-being index vs cost of living
  output/wellbeing_factors.png BRFSS life-satisfaction effects
  output/city_rankings.csv    tidy ranking table
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from adjustText import adjust_text

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
c = pd.read_csv(ROOT / "data/city_index.csv", dtype={"fips": str})
meta = json.loads((ROOT / "data/index_meta.json").read_text())
coefs = pd.read_csv(ROOT / "data/brfss_coefficients.csv")
LS_SD = 0.623   # weighted SD of the 1-4 life-satisfaction score (from 02_brfss_weights.py)

DOMAINS = ["mental", "physical", "social", "economic", "safety", "commute", "air", "climate", "income"]
DESC = {
    "mental": "Frequent mental distress (14+ bad days a month)",
    "physical": "Fair/poor self-rated health; frequent physical distress",
    "social": "Loneliness; lacking social and emotional support",
    "economic": "Housing insecurity, utility shut-off threats, transport barriers, food insecurity, unemployment",
    "safety": "Homicide and violent-crime rates, 2023-2025",
    "commute": "Mean one-way commute time",
    "air": "Fine-particle (PM2.5) pollution, 2023-2025",
    "climate": "Heating + cooling degree days, 1991-2020 normals",
    "income": "Median household income adjusted for local prices (off by default)",
}
FACTOR_LABELS = {
    "nosupport": "Lacks social & emotional support", "fmd": "Frequent mental distress",
    "lonely": "Feels lonely", "fairpoor": "Fair or poor health", "partnered": "Married or partnered",
    "unemployed": "Unemployed", "transport": "Lacks reliable transportation", "fpd": "Frequent physical distress",
    "housinsec": "Couldn't pay rent/mortgage/utilities", "unable_work": "Unable to work",
    "utilthreat": "Utility shut-off threat", "log_inc": "Household income doubled", "foodinsec": "Food insecure",
}

# ---------------------------------------------------------------- data bundle
w = meta["weights"]
w.setdefault("income", 0.0)
cities = []
for _, r in c.iterrows():
    cities.append({
        "n": r.label, "st": r.STUSAB, "reg": r.region, "pop": int(r["pop"]),
        "col": round(r.col_index, 1), "rpp": round(r.rpp_all, 1), "metro": r.cbsa_title,
        "z": {d: round(r[f"z_{d}"], 3) for d in DOMAINS},
        "raw": {
            "inc": int(r.med_hh_income), "rent": int(r.med_gross_rent), "unemp": round(r.unemp_rate, 1),
            "fmd": round(r.MHLTH, 1), "fph": round(r.GHLTH, 1), "lonely": round(r.LONELINESS, 1),
            "nosup": round(r.EMOTIONSPT, 1), "housins": round(r.HOUSINSECU, 1), "foodins": round(r.FOODINSECU, 1),
            "murder": round(r.murder_rate, 1), "violent": int(round(r.violent_rate)), "commute": round(r.commute_min, 1),
            "pm25": round(r.pm25, 1), "dd": int(round(r.degree_days)), "hdd": int(round(r.hdd)), "cdd": int(round(r.cdd)),
        },
        "src": {"health": r.health_source, "social": r.hrsn_source, "crime": r.crime_years},
    })

ls = coefs[coefs.outcome == "ls"].set_index("var")
single = coefs[coefs.outcome == "ls_single"].set_index("var")
dis = coefs[coefs.outcome == "dissat"].set_index("var")
factors = []
for v in FACTOR_LABELS:
    k = np.log(2) if v == "log_inc" else 1.0     # express income as the effect of doubling it
    factors.append({"key": v, "label": FACTOR_LABELS[v],
                    "sd": round(k * ls.coef[v] / LS_SD, 3), "se": round(k * ls.se[v] / LS_SD, 3),
                    "alone": round(k * single.coef[v] / LS_SD, 3),
                    "dissat_pp": round(100 * k * dis.coef[v], 1)})
factors.sort(key=lambda f: f["sd"])

bundle = {
    "domains": [{"key": d, "label": meta["labels"][d], "desc": DESC[d], "w": round(w.get(d, 0), 4),
                 "group": "person" if d in ("mental", "physical", "social", "economic") else
                          ("optional" if d == "income" else "place")} for d in DOMAINS],
    "cities": cities, "factors": factors,
    "brfss_n": 325940,
}
(OUT / "qol_data.json").write_text(json.dumps(bundle, separators=(",", ":")))

rank = c.sort_values("qol", ascending=False)[
    ["rank_qol", "label", "qol", "col_index", "qol_vs_cost", "rank_value", "pop", "rpp_all", "z_mental", "z_physical",
     "z_social", "z_economic", "z_safety", "z_commute", "z_air", "z_climate", "med_hh_income", "murder_rate",
     "violent_rate", "commute_min", "pm25", "degree_days", "hrsn_source"]].round(2)
rank.to_csv(OUT / "city_rankings.csv", index=False)

# ---------------------------------------------------------------- static scatter
INK, MUTED, GRID, BLUE, ORANGE, SURF = "#0b0b0b", "#898781", "#e1e0d9", "#2a78d6", "#eb6834", "#fcfcfb"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": "#c3c2b7",
                     "axes.labelcolor": "#52514e", "xtick.color": MUTED, "ytick.color": MUTED})
fig, ax = plt.subplots(figsize=(13, 8.5), dpi=150)
fig.patch.set_facecolor(SURF); ax.set_facecolor(SURF)
ax.grid(color=GRID, lw=0.8); ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
size = 18 + 260 * np.sqrt(c["pop"] / c["pop"].max())
ax.axvline(100, color="#c3c2b7", lw=1); ax.axhline(100, color="#c3c2b7", lw=1)
xs = np.linspace(c.col_index.min() - 1, c.col_index.max() + 1, 50)
ax.plot(xs, meta["trend"]["intercept"] + meta["trend"]["slope"] * xs, color=MUTED, lw=1)
ax.scatter(c.col_index, c.qol, s=size, color=BLUE, alpha=0.6, edgecolor=SURF, linewidth=1.2, zorder=3)
lab = set(c.nlargest(12, "qol").label) | set(c.nsmallest(8, "qol").label) | set(c.nlargest(10, "pop").label) \
    | set(c.nlargest(4, "col_index").label) | set(c.nsmallest(4, "col_index").label)
dup = c.label.str.rsplit(",", n=1).str[0].duplicated(keep=False)
texts = [ax.text(r.col_index, r.qol, r.label if dup[i] else r.label.rsplit(",", 1)[0], fontsize=8.5, color=INK, zorder=4)
         for i, r in c[c.label.isin(lab)].iterrows()]
adjust_text(texts, ax=ax, x=c.col_index.values, y=c.qol.values, expand=(1.2, 1.4),
            arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6))
ax.set_xlabel("Cost of living  (US average = 100; BEA 2024 metro price parities, housing adjusted to city rents)")
ax.set_ylabel("Well-being index  (130-city average = 100, SD = 10)")
y0, y1 = ax.get_ylim(); x0, x1 = ax.get_xlim()
ax.text(x0 + 0.4, y1 - 0.8, "Higher well-being, lower cost", color="#52514e", fontsize=9, va="top", weight="bold")
ax.text(x1 - 0.4, y0 + 0.8, "Lower well-being, higher cost", color="#52514e", fontsize=9, ha="right", weight="bold")
ax.set_title(f"Well-being vs. cost of living, 130 largest US cities   (r = {meta['trend']['r']:.2f})",
             loc="left", fontsize=13, color=INK, weight="bold", pad=12)
fig.text(0.01, 0.005, "Index: CDC PLACES 2024-25, ACS 2024, crimeindex.org (FBI UCR) 2023-25, EPA AQS 2023-25, "
         "NOAA normals; weights from BRFSS 2023-24 life-satisfaction model + literature. Dot size = population.",
         fontsize=7.5, color=MUTED)
fig.tight_layout(rect=(0, 0.02, 1, 1))
fig.savefig(OUT / "qol_vs_cost.png", facecolor=SURF)
plt.close(fig)

# ---------------------------------------------------------------- static factor chart
f = pd.DataFrame(factors)
fig, ax = plt.subplots(figsize=(9, 5.6), dpi=150)
fig.patch.set_facecolor(SURF); ax.set_facecolor(SURF)
y = np.arange(len(f))
ax.barh(y, f.sd, height=0.55, color=np.where(f.sd < 0, "#e34948", BLUE), xerr=1.96 * f.se,
        error_kw=dict(ecolor=MUTED, lw=0.8))
ax.scatter(f.alone, y, marker="|", s=120, color=INK, zorder=3, label="Effect on its own (demographic controls only)")
ax.set_yticks(y, f.label); ax.axvline(0, color="#c3c2b7", lw=1)
ax.grid(axis="x", color=GRID, lw=0.8); ax.set_axisbelow(True)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.set_xlabel("Change in life satisfaction (standard deviations), holding the other factors constant")
ax.set_title("What moves life satisfaction: BRFSS 2023-24, 325,940 US adults", loc="left", fontsize=12,
             weight="bold", color=INK)
ax.legend(frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(0, -0.12))
fig.tight_layout()
fig.savefig(OUT / "wellbeing_factors.png", facecolor=SURF)
plt.close(fig)
print("wrote", [p.name for p in OUT.iterdir()])
