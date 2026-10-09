"""Assemble one row per large US city with every indicator the index uses.

Unit: Census place (city proper) with 2024 ACS population >= MIN_POP.
Output: data/city_indicators.csv (+ data/city_build_log.txt with match diagnostics).
"""
from pathlib import Path
import re
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"
MIN_POP = 200_000
log_lines = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    log_lines.append(s)


# ---------------------------------------------------------------- ACS 2024 1-year
geo = pd.read_csv(RAW / "acs2024_1yr/Geos20241YR.txt", sep="|", dtype=str)
geo = geo[geo.SUMLEVEL.isin(["160", "310"])][["GEO_ID", "SUMLEVEL", "STUSAB", "STATE", "PLACE", "CBSA", "NAME"]]


def acs(table):
    t = pd.read_csv(RAW / f"acs2024_1yr/acsdt1y2024-{table}.dat", sep="|", dtype={"GEO_ID": str})
    t = t[t.GEO_ID.isin(geo.GEO_ID)]
    est = [c for c in t.columns if "_E" in c]
    t[est] = t[est].apply(pd.to_numeric, errors="coerce")
    return t.set_index("GEO_ID")[est]


a = geo.set_index("GEO_ID").copy()
t = acs("b01003"); a["pop"] = t["B01003_E001"]
t = acs("b19013"); a["med_hh_income"] = t["B19013_E001"]
t = acs("b23025")
a["unemp_rate"] = 100 * t["B23025_E005"] / t["B23025_E003"]
a["unemp_share_16p"] = 100 * t["B23025_E005"] / t["B23025_E001"]
t1, t2 = acs("b08013"), acs("b08303")
a["commute_min"] = t1["B08013_E001"] / t2["B08303_E001"]
t = acs("b25064"); a["med_gross_rent"] = t["B25064_E001"]
t = acs("b25077"); a["med_home_value"] = t["B25077_E001"]
t = acs("b17001"); a["poverty_rate"] = 100 * t["B17001_E002"] / t["B17001_E001"]
t = acs("b19083"); a["gini"] = t["B19083_E001"]
t = acs("b15003"); a["ba_plus"] = 100 * t[[f"B15003_E0{k}" for k in (22, 23, 24, 25)]].sum(axis=1) / t["B15003_E001"]
t = acs("b25106")
burd = [f"B25106_E{k:03d}" for k in (6, 10, 14, 18, 22, 28, 32, 36, 40, 44)]
a["cost_burden_30"] = 100 * t[burd].sum(axis=1) / t["B25106_E001"]
a = a.reset_index()

metro_acs = a[a.SUMLEVEL == "310"][["CBSA", "med_gross_rent"]].rename(columns={"med_gross_rent": "metro_med_gross_rent"})
city = a[(a.SUMLEVEL == "160") & (a["pop"] >= MIN_POP) & (a.STUSAB != "PR")].copy()
city["fips"] = city.STATE + city.PLACE
city["place_name"] = city.NAME.str.split(",").str[0]
log(f"ACS places with pop >= {MIN_POP:,}: {len(city)}")

# Short display name: strip Census legal suffixes
SUFFIX = re.compile(r"\s+(city|town|village|municipality|borough|CDP|urban county|city and borough|"
                    r"consolidated government|unified government|metropolitan government|metro government|"
                    r"county)(\s+\(balance\))?$", re.I)


def short_name(n):
    n = re.sub(r"\s+\(balance\)$", "", n)
    n = SUFFIX.sub("", n)
    n = {"Nashville-Davidson": "Nashville", "Louisville/Jefferson County": "Louisville",
         "Lexington-Fayette": "Lexington", "Urban Honolulu": "Honolulu", "Augusta-Richmond County": "Augusta",
         "Athens-Clarke County": "Athens", "Macon-Bibb County": "Macon", "Boise City": "Boise",
         "San Buenaventura (Ventura)": "Ventura", "Indianapolis city": "Indianapolis"}.get(n, n)
    return n


city["city"] = city.place_name.map(short_name)
city["label"] = city.city + ", " + city.STUSAB

# ---------------------------------------------------------------- Gazetteer coordinates
gz = pd.read_csv(RAW / "gazetteer/2024_Gaz_place_national.txt", sep="\t", dtype=str)
gz.columns = [c.strip() for c in gz.columns]
gz = gz.rename(columns={"GEOID": "fips", "INTPTLAT": "lat", "INTPTLONG": "lon", "ALAND_SQMI": "land_sqmi"})
for c in ("lat", "lon", "land_sqmi"):
    gz[c] = pd.to_numeric(gz[c].str.strip())
city = city.merge(gz[["fips", "lat", "lon", "land_sqmi"]], on="fips", how="left")
city["density"] = city["pop"] / city.land_sqmi
# San Francisco's internal point falls offshore (the city includes the Farallon Islands); use City Hall.
city.loc[city.fips == "0667000", ["lat", "lon"]] = 37.7793, -122.4193


def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(h))


# ---------------------------------------------------------------- Metro (CBSA) assignment
l2 = pd.read_excel(RAW / "delineation/list2_2023.xlsx", header=2, dtype=str).dropna(subset=["FIPS Place Code"])
l2 = l2[l2["Metropolitan/Micropolitan Statistical Area"].str.startswith("Metropolitan")]
l2["fips"] = l2["FIPS State Code"] + l2["FIPS Place Code"]
pc = l2.drop_duplicates("fips").set_index("fips")
city["cbsa"] = city.fips.map(pc["CBSA Code"])
city["cbsa_title"] = city.fips.map(pc["CBSA Title"])
# Cities that are not OMB principal cities: take the CBSA of the nearest principal city in the same state.
pcg = pc.reset_index().merge(gz[["fips", "lat", "lon"]], on="fips")
pcg["st"] = pcg.fips.str[:2]
for i, r in city[city.cbsa.isna()].iterrows():
    cand = pcg[pcg.st == r.STATE].copy()
    cand["km"] = haversine(r.lat, r.lon, cand.lat, cand.lon)
    best = cand.nsmallest(1, "km").iloc[0]
    city.loc[i, ["cbsa", "cbsa_title"]] = best["CBSA Code"], best["CBSA Title"]
    log(f"  non-principal city {r.label}: assigned {best['CBSA Title']} via {best['Principal City Name']} ({best.km:.0f} km)")
city = city.merge(metro_acs, left_on="cbsa", right_on="CBSA", how="left").drop(columns=["CBSA_y"], errors="ignore")
city = city.rename(columns={"CBSA_x": "CBSA"}) if "CBSA_x" in city else city

# ---------------------------------------------------------------- BEA Regional Price Parities (2024)
rpp = pd.read_csv(RAW / "bea_rpp/MARPP_MSA_2008_2024.csv", encoding="latin1", dtype=str)
rpp["GeoFIPS"] = rpp.GeoFIPS.str.replace('"', "").str.strip()
rpp["LineCode"] = pd.to_numeric(rpp.LineCode, errors="coerce")
rpp["v"] = pd.to_numeric(rpp["2024"], errors="coerce")
rw = rpp.pivot_table(index="GeoFIPS", columns="LineCode", values="v")
rw.columns = ["rpp_all", "rpp_goods", "rpp_housing", "rpp_utilities", "rpp_other"]
# Implied expenditure weights: regress (all - 100) on component deviations across metros (no intercept).
msa = rw.dropna()
Xc = (msa[["rpp_goods", "rpp_housing", "rpp_utilities", "rpp_other"]] - 100).values
wts, *_ = np.linalg.lstsq(Xc, (msa.rpp_all - 100).values, rcond=None)
w_housing = wts[1]
log("Implied RPP expenditure weights (goods, housing, utilities, other):", np.round(wts, 3))
city = city.merge(rw, left_on="cbsa", right_index=True, how="left")
# City-level cost of living: metro RPP with the housing component rescaled by the city's own
# median gross rent relative to its metro (ACS 2024). Everything else is metro-wide.
city["rent_ratio"] = city.med_gross_rent / city.metro_med_gross_rent
city["col_index"] = city.rpp_all + w_housing * city.rpp_housing * (city.rent_ratio - 1)
log("Cities missing RPP:", city[city.rpp_all.isna()].label.tolist())

# ---------------------------------------------------------------- CDC PLACES (age-adjusted)
P_MEAS = ["MHLTH", "PHLTH", "GHLTH", "DEPRESSION", "LONELINESS", "EMOTIONSPT", "FOODINSECU",
          "HOUSINSECU", "SHUTUTILITY", "LACKTRPT"]
HEALTH = ["MHLTH", "PHLTH", "GHLTH", "DEPRESSION"]
HRSN = ["LONELINESS", "EMOTIONSPT", "FOODINSECU", "HOUSINSECU", "SHUTUTILITY", "LACKTRPT"]
# Extra PLACES measures used only as predictors when imputing missing social-needs measures
AUX = ["CSMOKING", "OBESITY", "ACCESS2", "LPA", "DISABILITY", "BINGE", "DIABETES", "CHECKUP", "COGNITION",
       "INDEPLIVE", "MOBILITY"]
raw25 = pd.read_csv(RAW / "places/places_place_2025.csv", dtype={"locationid": str},
                    usecols=["locationid", "measureid", "data_value", "totalpopulation"])
p25 = raw25[raw25.measureid.isin(P_MEAS + AUX)].pivot_table(index="locationid", columns="measureid", values="data_value")
p25["places_pop"] = raw25.drop_duplicates("locationid").set_index("locationid").totalpopulation
p24 = pd.read_csv(RAW / "places/places_place_2024rel.csv", dtype={"placefips": str}).set_index("placefips")
col24 = {m: m.lower() + "_adjprev" for m in HEALTH + HRSN + AUX}
col24["LONELINESS"] = "isolation_adjprev"   # 2024 release measured "feeling socially isolated"
city = city.merge(p25[[c for c in P_MEAS + AUX if c in p25]], left_on="fips", right_index=True, how="left")
city["health_source"] = np.where(city.MHLTH.notna(), "PLACES 2025 (BRFSS 2023)", None)
city["hrsn_source"] = np.where(city.LONELINESS.notna(), "PLACES 2025 (BRFSS 2023)", None)
# Fill gaps from the 2024 release (BRFSS 2022), calibrated with a linear map fitted on places in both.
both = p25.join(p24[[c for c in col24.values() if c in p24] + ["totalpopulation"]], how="inner")
both = both[pd.to_numeric(both.totalpopulation, errors="coerce") >= 20000]
for m, c24 in col24.items():
    if c24 not in both or m not in both:
        continue
    ok = both[[m, c24]].dropna()
    b, a0 = np.polyfit(ok[c24], ok[m], 1)
    r = np.corrcoef(ok[c24], ok[m])[0, 1]
    need = city[m].isna() & city.fips.isin(p24.index)
    if m in HEALTH + HRSN:
        log(f"  calibrate {m} <- 2024 {c24}: n={len(ok)}, r={r:.3f}, {m} = {a0:.2f} + {b:.3f}*x; filling {need.sum()}")
    city.loc[need, m] = a0 + b * pd.to_numeric(city.loc[need, "fips"].map(p24[c24]), errors="coerce")
fill_h = city.health_source.isna() & city.MHLTH.notna()
city.loc[fill_h, "health_source"] = "PLACES 2024 (BRFSS 2022), calibrated"
fill_s = city.hrsn_source.isna() & city.LONELINESS.notna()
city.loc[fill_s, "hrsn_source"] = "PLACES 2024 (BRFSS 2022), calibrated"
log("Health measures from 2024 release:", city[fill_h].label.tolist())
log("Social-needs measures from 2024 release:", city[fill_s].label.tolist())
# Remaining gaps (states with no social-needs module in either year): impute each measure from the
# other PLACES health measures, fitted on all places >= 50k residents that have it.
pred = HEALTH + AUX
train = p25[(pd.to_numeric(p25.places_pop, errors="coerce") >= 50000)].dropna(subset=pred + HRSN)
need = city.LONELINESS.isna()
from numpy.linalg import lstsq
Xtr = np.column_stack([np.ones(len(train)), train[pred].values])
for m in HRSN:
    beta, *_ = lstsq(Xtr, train[m].values, rcond=None)
    # 5-fold CV R^2 for the log
    idx = np.arange(len(train)) % 5
    resid = []
    for k in range(5):
        bk, *_ = lstsq(Xtr[idx != k], train[m].values[idx != k], rcond=None)
        resid.append(train[m].values[idx == k] - Xtr[idx == k] @ bk)
    cv_r2 = 1 - np.var(np.concatenate(resid)) / np.var(train[m].values)
    Xc_ = np.column_stack([np.ones(need.sum()), city.loc[need, pred].values])
    city.loc[need, m] = Xc_ @ beta
    log(f"  impute {m}: n_train={len(train)}, CV R2={cv_r2:.2f}")
assert not city.loc[need, pred].isna().any().any(), city.loc[need, pred].isna().sum()
city.loc[need, "hrsn_source"] = "Imputed from other PLACES measures"
log("Social-needs measures imputed:", city[need].label.tolist())
city = city.drop(columns=AUX)

# ---------------------------------------------------------------- Crime (Real-Time Crime Index / FBI UCR)
names = pd.read_csv(ROOT / "data/rtci_agency_names.psv", sep="|", header=None, names=["ori", "agency"], dtype=str)
crime = pd.read_csv(RAW / "rtci/historical_crime_1930_2025_1790092670.csv",
                    usecols=["id", "year", "population", "violent_total", "murder_total"])
crime = crime[crime.year.between(2019, 2025)].dropna(subset=["violent_total"])
# Drop partial-year reports (violent count < half the agency's 2019-2025 median), then keep the
# latest three remaining years from 2022-2025.
crime["med"] = crime.groupby("id").violent_total.transform("median")
crime = crime[(crime.violent_total >= 0.5 * crime.med) & (crime.year >= 2022)]
crime = crime.sort_values("year").groupby("id").tail(3)
cs = crime.groupby("id").agg(pop=("population", "mean"), violent=("violent_total", "sum"),
                             murder=("murder_total", "sum"), vyears=("violent_total", "count"),
                             first_year=("year", "min"), last_year=("year", "max"))
cs["violent_rate"] = 1e5 * cs.violent / (cs["pop"] * cs.vyears)
cs["murder_rate"] = 1e5 * cs.murder / (cs["pop"] * cs.vyears)
cs["crime_years"] = cs.first_year.astype(int).astype(str) + "-" + cs.last_year.astype(int).astype(str)
cs = cs.join(names.set_index("ori"))
cs["st"] = cs.index.str[:2]
cs["st"] = cs.st.replace({"NB": "NE"})  # FBI ORI state prefixes match USPS except Nebraska
cs["key"] = cs.st + "|" + cs.agency.str.lower().str.strip()
OVERRIDE = {  # cities whose police agency is named differently from the place
    "New York, NY": "NY0303000", "Honolulu, HI": "HI0020000", "Las Vegas, NV": "NV0020100",
    "Enterprise, NV": "NV0020100", "Spring Valley, NV": "NV0020100",   # unincorporated; policed by LVMPD
    "Washington, DC": "DCMPD0000", "Jacksonville, FL": "FL0160000", "Augusta, GA": "GA1210000",
    "Arlington, VA": "VA0070100", "Moreno Valley, CA": "CA033320X", "Santa Clarita, CA": "CA0191R0X",
}
city["crime_key"] = city.STUSAB + "|" + city.city.str.lower()
by_key = cs.reset_index().sort_values("pop", ascending=False).drop_duplicates("key").set_index("key")
city["ori"] = city.crime_key.map(by_key["id"])
for lab, ori in OVERRIDE.items():
    city.loc[city.label == lab, "ori"] = ori
city = city.merge(cs[["violent_rate", "murder_rate", "crime_years", "pop"]].rename(columns={"pop": "agency_pop"}),
                  left_on="ori", right_index=True, how="left")
city["agency_pop_ratio"] = city.agency_pop / city["pop"]
odd = city[(city.agency_pop_ratio < 0.7) | (city.agency_pop_ratio > 1.4)]
for _, r in odd.iterrows():
    log(f"  crime coverage check {r.label}: agency pop {r.agency_pop:,.0f} vs city {r['pop']:,.0f} (ori {r.ori})")
log("Cities without crime data:", city[city.violent_rate.isna()].label.tolist())

# ---------------------------------------------------------------- PM2.5 (EPA AQS annual means, 2023-2025)
pm = []
for y in (2023, 2024, 2025):
    e = pd.read_csv(RAW / f"epa_pm/annual_conc_by_monitor_{y}.csv", dtype=str,
                    usecols=["State Code", "County Code", "Site Num", "Parameter Code", "Latitude", "Longitude",
                             "Pollutant Standard", "Event Type", "Arithmetic Mean", "Completeness Indicator"])
    e = e[(e["Parameter Code"] == "88101") & (e["Pollutant Standard"] == "PM25 Annual 2024")
          & (~e["Event Type"].isin(["Events Excluded", "Concurred Events Excluded"]))]
    e["site"] = e["State Code"] + e["County Code"] + e["Site Num"]
    e["pm25"] = pd.to_numeric(e["Arithmetic Mean"])
    e["lat"], e["lon"] = pd.to_numeric(e.Latitude), pd.to_numeric(e.Longitude)
    pm.append(e.groupby("site").agg(pm25=("pm25", "mean"), lat=("lat", "first"), lon=("lon", "first")).assign(year=y))
pm = pd.concat(pm).groupby("site").agg(pm25=("pm25", "mean"), lat=("lat", "first"), lon=("lon", "first"), n_years=("year", "nunique"))
vals, ns = [], []
for _, r in city.iterrows():
    km = haversine(r.lat, r.lon, pm.lat.values, pm.lon.values)
    near = pm[km <= 25]
    if len(near) == 0:
        near = pm.iloc[np.argsort(km)[:2]]
    vals.append(near.pm25.mean()); ns.append(len(near))
city["pm25"] = vals
city["pm25_monitors"] = ns

# ---------------------------------------------------------------- Climate normals (NOAA 1991-2020)
st_files = sorted((RAW / "noaa_normals/ex").glob("*.csv"))
rows = []
for f in st_files:
    try:
        s = pd.read_csv(f, usecols=["STATION", "LATITUDE", "LONGITUDE", "NAME", "ANN-HTDD-NORMAL", "ANN-CLDD-NORMAL",
                                    "ANN-TAVG-NORMAL", "ANN-TMAX-AVGNDS-GRTH090", "ANN-TMIN-AVGNDS-LSTH032"])
    except ValueError:
        continue
    rows.append(s.iloc[0])
norm = pd.DataFrame(rows).dropna(subset=["ANN-HTDD-NORMAL", "ANN-CLDD-NORMAL"])
norm = norm[(norm["ANN-HTDD-NORMAL"] >= 0) & (norm["ANN-CLDD-NORMAL"] >= 0)]
norm["first_order"] = norm.STATION.str.startswith("USW")
clim = []
for _, r in city.iterrows():
    km = haversine(r.lat, r.lon, norm.LATITUDE.values, norm.LONGITUDE.values)
    n2 = norm.assign(km=km)
    fo = n2[n2.first_order & (n2.km <= 40)]
    best = (fo if len(fo) else n2).nsmallest(1, "km").iloc[0]
    clim.append({"hdd": best["ANN-HTDD-NORMAL"], "cdd": best["ANN-CLDD-NORMAL"], "tavg": best["ANN-TAVG-NORMAL"],
                 "days_90f": best["ANN-TMAX-AVGNDS-GRTH090"], "days_frost": best["ANN-TMIN-AVGNDS-LSTH032"],
                 "climate_station": best.NAME, "climate_km": best.km})
city = pd.concat([city.reset_index(drop=True), pd.DataFrame(clim)], axis=1)
city["degree_days"] = city.hdd + city.cdd

# ---------------------------------------------------------------- Census region (for chart color)
REGION = {**{s: "Northeast" for s in "CT ME MA NH RI VT NJ NY PA".split()},
          **{s: "Midwest" for s in "IL IN MI OH WI IA KS MN MO NE ND SD".split()},
          **{s: "South" for s in "DE DC FL GA MD NC SC VA WV AL KY MS TN AR LA OK TX".split()},
          **{s: "West" for s in "AZ CO ID MT NV NM UT WY AK CA HI OR WA".split()}}
city["region"] = city.STUSAB.map(REGION)

keep = ["fips", "label", "city", "STUSAB", "region", "place_name", "pop", "lat", "lon", "density", "cbsa", "cbsa_title",
        "rpp_all", "rpp_housing", "med_gross_rent", "metro_med_gross_rent", "rent_ratio", "col_index",
        "med_hh_income", "unemp_rate", "unemp_share_16p", "commute_min", "med_home_value", "poverty_rate", "gini",
        "ba_plus", "cost_burden_30", *P_MEAS, "health_source", "hrsn_source", "ori", "agency_pop_ratio", "violent_rate", "murder_rate", "crime_years",
        "pm25", "pm25_monitors", "hdd", "cdd", "degree_days", "tavg", "days_90f", "days_frost", "climate_station",
        "climate_km"]
city = city[keep].sort_values("pop", ascending=False)
city.to_csv(ROOT / "data/city_indicators.csv", index=False)
log(f"Wrote {len(city)} cities")
log("Missing counts:\n" + city.isna().sum()[city.isna().sum() > 0].to_string())
(ROOT / "data/city_build_log.txt").write_text("\n".join(log_lines) + "\n")
