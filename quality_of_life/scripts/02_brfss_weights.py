"""Estimate how much each person-level factor moves life satisfaction (BRFSS 2023-2024).

Outcome: LSATISFY recoded 1-4 (4 = very satisfied). Survey-weighted least squares with
demographic controls and state x year fixed effects. Binary predictors are coded to match
the CDC PLACES city-level definitions, so a coefficient times a city prevalence is that
factor's contribution to the city's predicted average life satisfaction.

Writes data/brfss_coefficients.csv.
"""
from pathlib import Path
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

ROOT = Path(__file__).resolve().parents[1]
d = pd.read_csv(ROOT / "data/brfss_ls.csv.gz")

d = d[d.LSATISFY.between(1, 4)].copy()
d["ls"] = 5 - d.LSATISFY                      # 4 very satisfied ... 1 very dissatisfied
d["very_sat"] = (d.LSATISFY == 1).astype(float)
d["dissat"] = (d.LSATISFY >= 3).astype(float)

def days_ge14(x):
    x = x.where(x.between(1, 30) | (x == 88))
    return np.where(x.isna(), np.nan, ((x >= 14) & (x <= 30)).astype(float))

def yes(x):                                    # 1 = yes, 2 = no, else missing
    return np.where(x == 1, 1.0, np.where(x == 2, 0.0, np.nan))

def freq(x, hits):                             # 1 always ... 5 never
    return np.where(x.between(1, 5), x.isin(hits).astype(float), np.nan)

d["fmd"] = days_ge14(d.MENTHLTH)                         # PLACES MHLTH
d["fpd"] = days_ge14(d.PHYSHLTH)                         # PLACES PHLTH
d["fairpoor"] = np.where(d.GENHLTH.between(1, 5), (d.GENHLTH >= 4).astype(float), np.nan)  # GHLTH
d["lonely"] = freq(d.SDLONELY, [1, 2, 3])                # PLACES LONELINESS
d["nosupport"] = freq(d.EMTSUPRT, [3, 4, 5])             # PLACES EMOTIONSPT
d["foodinsec"] = freq(d.SDHFOOD1, [1, 2, 3])             # PLACES FOODINSECU
d["housinsec"] = yes(d.SDHBILLS)                         # PLACES HOUSINSECU
d["utilthreat"] = np.where(d.SDHUTILS.isin([1, 3]), 1.0, np.where(d.SDHUTILS == 2, 0.0, np.nan))
d["transport"] = yes(d.SDHTRNSP)                         # PLACES LACKTRPT
d["unemployed"] = np.where(d.EMPLOY1.between(1, 8), d.EMPLOY1.isin([3, 4]).astype(float), np.nan)
d["unable_work"] = np.where(d.EMPLOY1.between(1, 8), (d.EMPLOY1 == 8).astype(float), np.nan)
d["partnered"] = np.where(d.MARITAL.between(1, 6), d.MARITAL.isin([1, 6]).astype(float), np.nan)
mid = {1: 5, 2: 12.5, 3: 17.5, 4: 22.5, 5: 30, 6: 42.5, 7: 62.5, 8: 87.5, 9: 125, 10: 175, 11: 250}
d["log_inc"] = np.log(d.INCOME3.map(mid))
d["age"] = d._AGEG5YR.where(d._AGEG5YR.between(1, 13))
d["race"] = d._RACE.where(d._RACE.between(1, 8))
d["educ"] = d._EDUCAG.where(d._EDUCAG.between(1, 4))
d["st_yr"] = d._STATE.astype(int).astype(str) + "_" + d.YEAR.astype(str)
d["w"] = d._LLCPWT / d._LLCPWT.mean()

X = ["fmd", "fpd", "fairpoor", "lonely", "nosupport", "foodinsec", "housinsec", "utilthreat",
     "transport", "unemployed", "unable_work", "partnered", "log_inc"]
ctrl = "C(age) + C(race) + C(educ) + C(SEXVAR) + C(st_yr)"
m = d.dropna(subset=X + ["age", "race", "educ", "SEXVAR"]).copy()
print(f"N = {len(m):,} respondents, {m._STATE.nunique()} states")

rows = []
for outcome in ["ls", "very_sat", "dissat"]:
    fit = smf.wls(f"{outcome} ~ {' + '.join(X)} + {ctrl}", data=m, weights=m.w).fit(
        cov_type="cluster", cov_kwds={"groups": m.st_yr.astype("category").cat.codes})
    for x in X:
        rows.append({"outcome": outcome, "var": x, "coef": fit.params[x], "se": fit.bse[x]})
    print(outcome, "R2 =", round(fit.rsquared, 3))
# Bivariate (no other factors) for comparison of raw associations
for x in X:
    fit = smf.wls(f"ls ~ {x} + {ctrl}", data=m, weights=m.w).fit()
    rows.append({"outcome": "ls_single", "var": x, "coef": fit.params[x], "se": fit.bse[x]})

out = pd.DataFrame(rows)
out.to_csv(ROOT / "data/brfss_coefficients.csv", index=False)
wide = out.pivot(index="var", columns="outcome", values="coef").loc[X]
print(wide.round(3).to_string())
sd = np.sqrt(np.average((m.ls - np.average(m.ls, weights=m.w))**2, weights=m.w))
print("weighted mean ls", round(np.average(m.ls, weights=m.w), 3), "sd", round(sd, 3))
