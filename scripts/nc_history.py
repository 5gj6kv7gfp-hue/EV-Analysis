"""NC: are 2026's extra early voters new turnout, or the same voters casting ballots earlier?

Each early voter (accepted mail + one-stop, through the same days-before-Election-Day cutoff) is
classified by how they voted in the *previous midterm*:
  early in-person / mail   already an early voter
  election day             voted, but on Election Day: early voting now is a timing shift
  did not vote             includes newly registered voters: this is added turnout
The same is done for 2022's early voters against 2018, giving a like-for-like baseline.

Inputs (downloaded if missing): NCSBE absentee files for 2022 and 2026 (data/raw/nc), and the
statewide voter history file ncvhis_Statewide.zip (streamed; only 2018/2022 generals kept).
Output: data/processed/nc_history_sameday.csv
"""
import io
import pathlib
import sys
import zipfile

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from nc_early_vote import ACCEPTED_PREFIX, ELECTIONS, PARTY, PROC, RAW, S3, fetch, tag  # noqa: E402

HIST_URL = "https://s3.amazonaws.com/dl.ncsbe.gov/data/ncvhis_Statewide.zip"
PRIOR = {2026: "11/08/2022", 2022: "11/06/2018"}
METHOD = {"ABSENTEE ONESTOP": "early in-person", "ABSENTEE BY MAIL": "mail", "ABSENTEE": "mail",
          "ABSENTEE CURBSIDE": "early in-person", "IN-PERSON": "election day",
          "CURBSIDE": "election day", "PROVISIONAL": "election day", "TRANSFER": "election day",
          "ELIGIBLE DID NOT VOTE": "did not vote"}


def early_voters(year, days_before):
    z = fetch(f"{S3}{tag(year)}/absentee_{tag(year).replace('_', '')}.zip", RAW / f"absentee_{year}.zip")
    eday = pd.Timestamp(ELECTIONS[year])
    out = []
    with zipfile.ZipFile(z) as zf:
        name = [n for n in zf.namelist() if n.endswith(".csv")][0]
        with zf.open(name) as f:
            for c in pd.read_csv(io.TextIOWrapper(f, encoding="latin1"), dtype=str, chunksize=500_000,
                                 usecols=["ncid", "voter_party_code", "ballot_rtn_dt", "ballot_rtn_status"]):
                c = c[c.ballot_rtn_status.fillna("").str.strip().str.startswith(ACCEPTED_PREFIX)]
                days = (eday - pd.to_datetime(c.ballot_rtn_dt, format="%m/%d/%Y", errors="coerce")).dt.days
                c = c[days >= days_before]
                out.append(c.assign(party=c.voter_party_code.str.strip().map(PARTY).fillna("U"))[["ncid", "party"]])
    return pd.concat(out).drop_duplicates("ncid")


def prior_method():
    cache = RAW / "ncvhis_2018_2022_generals.csv"
    if cache.exists():
        return pd.read_csv(cache, dtype=str)
    z = fetch(HIST_URL, RAW / "ncvhis_Statewide.zip")
    keep = []
    with zipfile.ZipFile(z) as zf:
        name = [n for n in zf.namelist() if n.endswith(".txt")][0]
        with zf.open(name) as f:
            for c in pd.read_csv(io.TextIOWrapper(f, encoding="latin1"), sep="\t", dtype=str,
                                 chunksize=2_000_000, usecols=["ncid", "election_lbl", "voting_method"]):
                keep.append(c[c.election_lbl.isin(PRIOR.values())])
    h = pd.concat(keep)
    h["method"] = h.voting_method.str.strip().map(METHOD).fillna("election day")
    h = h[h.method != "did not vote"].drop_duplicates(["ncid", "election_lbl"])[["ncid", "election_lbl", "method"]]
    h.to_csv(cache, index=False)
    z.unlink()  # 350 MB; the filtered cache is all that's needed
    return h


def main(days_before=None):
    daily = pd.read_csv(PROC / "nc_returns_daily.csv")
    if days_before is None:
        cur = daily[daily.year == 2026].groupby("days_before").ballots.sum()
        days_before = int(cur[cur >= 100].index.min())
    hist = prior_method()
    rows = []
    for year, lbl in PRIOR.items():
        ev = early_voters(year, days_before)
        prev = hist[hist.election_lbl == lbl][["ncid", "method"]]
        m = ev.merge(prev, on="ncid", how="left").fillna({"method": "did not vote"})
        t = pd.crosstab(m.party, m.method)
        t.loc["All"] = t.sum()
        for party, r in t.iterrows():
            rows.append({"year": year, "prior_midterm": lbl, "party": party, "early_voters": int(r.sum()),
                         **{k: int(r.get(k, 0)) for k in ["early in-person", "mail", "election day", "did not vote"]}})
    out = pd.DataFrame(rows)
    for k in ["early in-person", "mail", "election day", "did not vote"]:
        out[f"pct_{k.replace(' ', '_')}"] = 100 * out[k] / out.early_voters
    out["days_before"] = days_before
    out.to_csv(PROC / "nc_history_sameday.csv", index=False, float_format="%.2f")
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(out.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
