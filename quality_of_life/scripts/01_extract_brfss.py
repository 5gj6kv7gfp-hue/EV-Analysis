"""Extract the BRFSS 2023-2024 variables used to estimate life-satisfaction weights.

Reads the national LLCP XPT files (raw/brfss_llcp_YYYY/) in chunks and keeps only the
columns needed, writing data/brfss_ls.csv.gz.
"""
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEEP = ["_STATE", "_STSTR", "_PSU", "_LLCPWT", "SEXVAR", "_AGEG5YR", "_RACE", "_EDUCAG",
        "_INCOMG1", "INCOME3", "EMPLOY1", "MARITAL", "GENHLTH", "PHYSHLTH", "MENTHLTH",
        "LSATISFY", "EMTSUPRT", "SDLONELY", "SDHEMPLY", "FOODSTMP", "SDHFOOD1", "SDHBILLS",
        "SDHUTILS", "SDHTRNSP", "SDHSTRE1", "RENTHOM1", "CHILDREN"]

frames = []
for y in (2023, 2024):
    for chunk in pd.read_sas(ROOT / f"raw/brfss_llcp_{y}/LLCP{y}.XPT", format="xport", chunksize=100_000):
        c = chunk[[k for k in KEEP if k in chunk.columns]].copy()
        c["YEAR"] = y
        frames.append(c[c["LSATISFY"].notna()])
df = pd.concat(frames, ignore_index=True)
df.to_csv(ROOT / "data/brfss_ls.csv.gz", index=False)
print(df.groupby("YEAR").size())
print(df.groupby("YEAR")["_STATE"].nunique())
