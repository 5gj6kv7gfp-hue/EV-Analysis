"""Pennsylvania: 2026 mail ballots vs 2022 and 2024 at the same number of days before Election Day.

PA has no in-person early voting, so mail ballots are the whole pre-Election-Day vote. The Dept.
of State publishes voter-level mail ballot files on data.pa.gov (Socrata) for every general
election, with party, birth date, application and ballot-return dates. Counts are aggregated
server-side with SoQL so nothing voter-level is downloaded.

Outputs: data/processed/pa_mail_daily.csv, data/processed/pa_mail_sameday.csv,
         data/processed/pa_mail_age_sameday.csv
"""
import pathlib

import pandas as pd
import requests

PROC = pathlib.Path(__file__).resolve().parents[1] / "data" / "processed"
DATASETS = {2022: "uhfm-zhus", 2024: "3q5t-ddp8", 2026: "nbwd-pfn4"}
EDAY = {2022: "2022-11-08", 2024: "2024-11-05", 2026: "2026-11-03"}
PARTY = {"D": "D", "DEM": "D", "R": "R", "REP": "R"}


def soql(dataset, **params):
    params = {f"${k}": v for k, v in params.items()}
    params.setdefault("$limit", 50000)
    r = requests.get(f"https://data.pa.gov/resource/{dataset}.json", params=params, timeout=600)
    r.raise_for_status()
    return pd.DataFrame(r.json())


def daily(year, date_col):
    d = soql(DATASETS[year], select=f"party, {date_col} as dt, count(*) as n",
             where=f"{date_col} IS NOT NULL", group=f"party, {date_col}")
    d["n"] = d.n.astype(int)
    d["party"] = d.party.str.strip().map(PARTY).fillna("U")
    d["days_before"] = (pd.Timestamp(EDAY[year]) - pd.to_datetime(d.dt.str[:10], errors="coerce")).dt.days
    return d.dropna(subset=["days_before"]).groupby(["party", "days_before"], as_index=False).n.sum().assign(year=year)


def age_by_party(year, days_before):
    """Returned ballots by party and birth year, up to the same-day cutoff."""
    cutoff = (pd.Timestamp(EDAY[year]) - pd.Timedelta(days=days_before)).strftime("%Y-%m-%d")
    # 2022 stores full birth dates (a timestamp column); later years store "YYYY-MM" text.
    # Group by birth year server-side where possible so results stay under the row limit.
    dob = "date_extract_y(dateofbirth)" if year == 2022 else "dateofbirth"
    d = soql(DATASETS[year], select=f"party, {dob} as dob, count(*) as n",
             where=f"ballotreturneddate IS NOT NULL AND ballotreturneddate <= '{cutoff}'",
             group=f"party, {dob}")
    d["dob"] = d.dob.astype(str)
    d["n"] = d.n.astype(int)
    d["party"] = d.party.str.strip().map(PARTY).fillna("U")
    d["age"] = year - pd.to_numeric(d.dob.str[:4], errors="coerce")
    d["age_group"] = pd.cut(d.age, [0, 29, 44, 64, 130], labels=["18-29", "30-44", "45-64", "65+"])
    return d.groupby(["party", "age_group"], observed=True).n.sum().unstack().assign(year=year)


def main():
    ret = pd.concat([daily(y, "ballotreturneddate") for y in DATASETS], ignore_index=True)
    req = pd.concat([daily(y, "appreturndate") for y in DATASETS], ignore_index=True)
    ret.assign(kind="returned").pipe(lambda r: pd.concat([r, req.assign(kind="requested")])) \
        .to_csv(PROC / "pa_mail_daily.csv", index=False)

    cur = ret[ret.year == 2026].groupby("days_before").n.sum()
    now = int(cur[cur >= 1000].index.min())  # latest day with real volume
    rows = []
    for y in DATASETS:
        r = ret[(ret.year == y) & (ret.days_before >= now)].groupby("party").n.sum().reindex(["D", "R", "U"], fill_value=0)
        q = req[(req.year == y) & (req.days_before >= now)].groupby("party").n.sum().reindex(["D", "R", "U"], fill_value=0)
        rows.append({"year": y, "days_before": now,
                     **{f"returned_{p}": int(r[p]) for p in "DRU"}, "returned": int(r.sum()),
                     "returned_D_minus_R_pts": 100 * (r.D - r.R) / r.sum(),
                     **{f"requested_{p}": int(q[p]) for p in "DRU"}, "requested": int(q.sum()),
                     **{f"return_rate_{p}": 100 * r[p] / q[p] for p in "DRU"}})
    same = pd.DataFrame(rows)
    same.to_csv(PROC / "pa_mail_sameday.csv", index=False, float_format="%.2f")

    ages = pd.concat([age_by_party(y, now) for y in (2022, 2026)])
    ages.to_csv(PROC / "pa_mail_age_sameday.csv", float_format="%.0f")

    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(f"Same-day cutoff: {now} days before Election Day")
        print(same.round(1).T)
        print(ages)


if __name__ == "__main__":
    main()
