"""How much of Ohio's "more Democratic early electorate" is a party-label artifact? (Franklin County)

Ohio has no party registration. A voter's party code is the ballot they took in their most recent
partisan primary. Media comparisons such as "the early electorate is N points more Democratic
than at this point in 2024" label 2026 voters with codes that now reflect the May 2026 primary,
and label the 2024 comparison group with codes that reflected the primaries before it.

This script takes the 2026 ballots cast so far (returned mail + early in-person) and labels the
same voters two ways:
  current   the PARTY field on the 2026 absentee lists (includes the 2026 primary)
  2024-era  the code the same rule gave in Oct 2024: 2024 primary ballot, else 2022 primaries
Any gap between the two is relabeling, not a change in who is voting.

Output: data/processed/ohio_label_artifact.csv
"""
import pathlib

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, PROC = ROOT / "data" / "raw", ROOT / "data" / "processed"


def main():
    mail = pd.read_csv(RAW / "fc_abs_mail_2026.txt", sep="\t", dtype=str, encoding="latin1")
    mail = mail[mail["DATE RETURNED"].notna()].assign(method="mail returned")
    inperson = pd.read_csv(RAW / "fc_abs_inperson_2026.txt", sep="\t", dtype=str, encoding="latin1")
    inperson = inperson.assign(method="early in-person")
    cast = pd.concat([mail, inperson])[["LOCAL_ID", "PARTY", "method"]].drop_duplicates("LOCAL_ID")

    # Franklin's PARTY code = the 2026 primary ballot, else the 2024 one (matches 99.7% of
    # requesters): the current and prior even-year primaries. In October 2024 the same rule meant
    # the 2024 primary, else the 2022 primaries (May, then the August legislative primary).
    pre = ["2024 Primary Election", "2022 AUGUST PRIMARY", "2022 PRIMARY ELECTION"]  # priority order
    v = pd.read_csv(RAW / "fc_voterfile_2026.txt", sep="\t", dtype=str, encoding="latin1",
                    usecols=["COUNTY ID", "2026 PRIMARY ELECTION", *pre])
    label = pd.Series("U", index=v.index)
    for c in reversed(pre):
        label = label.mask(v[c].isin(["D", "R"]), v[c])
    v = v.assign(label_2024era=label)[["COUNTY ID", "label_2024era", "2026 PRIMARY ELECTION"]]

    d = cast.merge(v, left_on="LOCAL_ID", right_on="COUNTY ID", how="inner")
    d["label_current"] = d.PARTY.fillna("U").str.strip().where(lambda s: s.isin(["D", "R"]), "U")

    rows = []
    for method, g in [("all ballots cast", d), *d.groupby("method")]:
        row = {"group": method, "ballots": len(g)}
        for lab in ["label_current", "label_2024era"]:
            share = g[lab].value_counts(normalize=True).reindex(["D", "R", "U"], fill_value=0) * 100
            row.update({f"{lab}_D": share.D, f"{lab}_R": share.R, f"{lab}_U": share.U,
                        f"{lab}_D_minus_R": share.D - share.R})
        row["artifact_pts"] = row["label_current_D_minus_R"] - row["label_2024era_D_minus_R"]
        rows.append(row)
    out = pd.DataFrame(rows)
    flows = pd.crosstab(d.label_2024era, d.label_current, margins=True)
    out.to_csv(PROC / "ohio_label_artifact.csv", index=False, float_format="%.2f")
    flows.to_csv(PROC / "ohio_label_flows.csv")
    print(f"matched {len(d):,} of {len(cast):,} ballots cast")
    with pd.option_context("display.width", 250, "display.max_columns", 20):
        print(out.round(1).T)
        print(flows)


if __name__ == "__main__":
    main()
