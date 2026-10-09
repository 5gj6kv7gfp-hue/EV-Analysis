"""Compute the city Quality-of-Life (QoL) index and compare it with cost of living.

Domains
  Person-level (weights estimated from BRFSS life-satisfaction regression, 70% of the index):
    mental health, physical health, social connection, economic security
  Place-level (weights set from the literature, 30% of the index):
    safety, commute, air quality, climate

For the person-level domains, each domain's raw score is the city's predicted life-satisfaction
contribution: sum of (BRFSS coefficient x city prevalence). Their relative weights are the
cross-city standard deviations of those contributions, i.e. how much each domain actually
moves predicted life satisfaction between these cities.

Outputs: data/city_index.csv, data/index_meta.json, output/sensitivity.csv
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
c = pd.read_csv(ROOT / "data/city_indicators.csv", dtype={"fips": str})
coef_all = pd.read_csv(ROOT / "data/brfss_coefficients.csv")

PERSON_SHARE = 0.70
PLACE_WEIGHTS = {"safety": 0.15, "commute": 0.07, "air": 0.04, "climate": 0.04}

PERSON_DOMAINS = {   # domain -> {BRFSS variable: city column (percent)}
    "mental": {"fmd": "MHLTH"},
    "physical": {"fairpoor": "GHLTH", "fpd": "PHLTH"},
    "social": {"lonely": "LONELINESS", "nosupport": "EMOTIONSPT"},
    "economic": {"housinsec": "HOUSINSECU", "utilthreat": "SHUTUTILITY", "transport": "LACKTRPT",
                 "foodinsec": "FOODINSECU", "unemployed": "unemp_share_16p"},
}
LABELS = {"mental": "Mental health", "physical": "Physical health", "social": "Social connection",
          "economic": "Economic security", "safety": "Safety", "commute": "Commute",
          "air": "Air quality", "climate": "Climate", "income": "Purchasing power"}


def z(s):
    return (s - s.mean()) / s.std(ddof=0)


def person_raw(coef):
    """Predicted life-satisfaction contribution of each person-level domain (LS points)."""
    out = {}
    for d, items in PERSON_DOMAINS.items():
        out[d] = sum(coef[v] * c[col] / 100 for v, col in items.items())
    return pd.DataFrame(out)


def place_raw():
    return pd.DataFrame({
        "safety": (z(-np.log(c.murder_rate + 1)) + z(-np.log(c.violent_rate))) / 2,
        "commute": -c.commute_min,
        "air": -c.pm25,
        "climate": -c.degree_days,
        # Not in the default index: median household income deflated by local prices (log)
        "income": np.log(c.med_hh_income / (c.col_index / 100)),
    })


def build(coef, person_share=PERSON_SHARE, place_weights=PLACE_WEIGHTS):
    pr = person_raw(coef)
    sd = pr.std(ddof=0)
    w = (sd / sd.sum() * person_share).to_dict()
    w.update(place_weights)
    raw = pd.concat([pr, place_raw()], axis=1)
    zs = raw.apply(z)
    comp = sum(w[d] * zs[d] for d in w)
    score = 100 + 10 * z(comp)
    return score, zs, raw, w, sd


coef = coef_all[coef_all.outcome == "ls"].set_index("var").coef
score, zs, raw, weights, sd = build(coef)
c["qol"] = score
for d in zs:
    c[f"z_{d}"] = zs[d]
c["pred_ls_person"] = raw[list(PERSON_DOMAINS)].sum(axis=1)

# QoL relative to cost: residual from a linear fit of QoL on cost of living
b, a0 = np.polyfit(c.col_index, c.qol, 1)
c["qol_vs_cost"] = c.qol - (a0 + b * c.col_index)
r_col = np.corrcoef(c.col_index, c.qol)[0, 1]
c["rank_qol"] = c.qol.rank(ascending=False).astype(int)
c["rank_value"] = c.qol_vs_cost.rank(ascending=False).astype(int)
c.to_csv(ROOT / "data/city_index.csv", index=False)

# ---------------------------------------------------------------- sensitivity
alts = {}
eq = {d: 1 / 8 for d in ["mental", "physical", "social", "economic", "safety", "commute", "air", "climate"]}
alts["equal_weights"] = 100 + 10 * z(sum(eq[d] * zs[d] for d in eq))
alts["person_only"] = build(coef, 1.0, {k: 0 for k in PLACE_WEIGHTS})[0]
alts["place_heavy_50_50"] = build(coef, 0.5, {k: v * 0.5 / 0.3 for k, v in PLACE_WEIGHTS.items()})[0]
alts["very_satisfied_coefs"] = build(coef_all[coef_all.outcome == "very_sat"].set_index("var").coef)[0]
alts["no_climate"] = build(coef, PERSON_SHARE / 0.96, {**PLACE_WEIGHTS, "climate": 0})[0]
w_inc = {d: v * 0.9 for d, v in weights.items()}
w_inc["income"] = 0.10
alts["with_purchasing_power_10pct"] = 100 + 10 * z(sum(w_inc[d] * zs[d] for d in w_inc))
sens = []
top_base = set(c.nlargest(20, "qol").label)
for k, s in alts.items():
    sens.append({"variant": k, "spearman_vs_base": round(s.rank().corr(c.qol.rank()), 3),
                 "top20_overlap": len(top_base & set(c.label[s.nlargest(20).index])),
                 "corr_with_cost": round(np.corrcoef(c.col_index, s)[0, 1], 3)})
sens = pd.DataFrame(sens)
sens.to_csv(ROOT / "output/sensitivity.csv", index=False)

meta = {
    "weights": {d: round(v, 4) for d, v in weights.items()},
    "labels": LABELS,
    "person_domain_sd_ls_points": {d: round(v, 5) for d, v in sd.items()},
    "brfss_coefficients": coef.round(4).to_dict(),
    "trend": {"slope": b, "intercept": a0, "r": r_col},
    "n_cities": len(c),
}
(ROOT / "data/index_meta.json").write_text(json.dumps(meta, indent=2))

pd.set_option("display.width", 200)
print("Weights:", {d: round(v, 3) for d, v in weights.items()})
print("Person-domain SD of predicted LS (points):", sd.round(4).to_dict())
print(f"QoL vs cost: r = {r_col:.2f}, slope = {b:.2f} QoL pts per COL pt")
print(sens.to_string(index=False))
cols = ["label", "qol", "col_index", "qol_vs_cost", "z_mental", "z_physical", "z_social", "z_economic",
        "z_safety", "z_commute", "z_air", "z_climate"]
print(c.sort_values("qol", ascending=False)[cols].head(15).round(2).to_string(index=False))
print(c.sort_values("qol")[cols].head(10).round(2).to_string(index=False))
print(c.sort_values("qol_vs_cost", ascending=False)[cols].head(12).round(2).to_string(index=False))
