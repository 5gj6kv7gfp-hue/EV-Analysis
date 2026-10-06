# Ohio vote-by-mail by precinct: 2022 vs 2026 (Franklin County)

Compares precinct-level vote-by-mail (VBM) activity in the **November 2022** and
**November 2026** general elections, and how the change varies with precinct partisanship.

**As of:** 2026 mail-ballot requests received through **Oct 5, 2026**. Ballots started going
out Oct 6, so no 2026 ballots have been returned yet.

## Scope: why only Franklin County

No statewide precinct-level absentee file exists for Ohio. The Secretary of State publishes only
county totals, and its site returned HTTP 403 from this environment. Each county board of
elections publishes (or doesn't publish) its own files. **Franklin County** (Columbus, ~905k
registrants, the state's largest county) has both pieces needed:

| Need | Source |
|---|---|
| 2026 mail requests, one row per voter, with precinct and party affiliation | Franklin BOE *Absentee by Mail Voter List (Current Election)* |
| 2026 registration by precinct and party | Franklin BOE countywide `VOTERFILE.TXT` |
| 2022 mail ballots by precinct, with candidate votes | Franklin BOE 2022 General *Official Results, Precinct Detail (XLSX)*, split by vote type (mail absentee / in-office absentee / election day / provisional) |

The voter file's vote-history columns record *whether* someone voted, not *how*. So the 2022 side
has to come from the precinct canvass.

## Method

- **Precinct match:** 2022 names ("COLUMBUS 01-A") are normalized to 2026 abbreviations ("COLS 1-A").
  876 precincts match. 8 exist only in 2022 and 13 only in 2026. 855 of the matched precincts have
  stable boundaries, meaning 2026 registration is within 0.67–1.5× of 2022 registration. Every
  result below holds when the analysis is limited to those 855.
- **Partisanship:**
  - *Precinct lean* is Whaley's two-party share in the 2022 governor race, counting all ballots.
  - *Voter party* is the BOE affiliation code. In Ohio this comes from the voter's most recent
    partisan primary ballot. Most voters are "U" (unaffiliated).
- **Comparison:** 2026 requests to date are compared with 2022 final mail ballots cast. The two
  counts are at different stages, so the analysis looks at **relative** shifts: each lean group's
  share of the countywide total, and each precinct's ratio of 2026 requests to 2022 mail ballots
  compared with the county ratio (0.67). If requests in all precincts mature at the same pace,
  these relative measures are unbiased.

## Findings

![share by lean](output/share_by_lean.png)

| Precinct lean (2022 gov, D two-party) | Precincts | 2022 mail ballots | 2026 requests | Share 2022 | Share 2026 | Change (pts) | 2026 req ÷ 2022 mail |
|---|---:|---:|---:|---:|---:|---:|---:|
| <40% D | 93 | 12,100 | 8,641 | 12.0% | 12.9% | **+0.9** | 0.71 |
| 40–50% D | 184 | 26,670 | 17,675 | 26.4% | 26.3% | −0.1 | 0.66 |
| 50–60% D | 223 | 28,620 | 19,167 | 28.4% | 28.5% | +0.2 | 0.67 |
| 60–70% D | 153 | 15,322 | 10,226 | 15.2% | 15.2% | +0.1 | 0.67 |
| 70–80% D | 113 | 10,967 | 6,847 | 10.9% | 10.2% | **−0.7** | 0.62 |
| 80%+ D | 110 | 7,232 | 4,590 | 7.2% | 6.8% | **−0.3** | 0.63 |
| **County (matched)** | 876 | 100,911 | 67,146 | | | | **0.67** |

1. **There is a small but statistically real shift toward Republican-leaning precincts.** The
   reddest precincts (<40% D) have already reached 71% of their 2022 mail-ballot volume. The
   bluest precincts (70%+ D) are at 62–63%. Across precincts:
   - Spearman ρ between lean and log(2026 requests ÷ 2022 mail ballots) is −0.12 (p < 0.001).
   - The weighted fit implies a ratio of about 0.70 in a 30% D precinct and 0.62 in an 85% D
     precinct, roughly a 12% relative gap.
   - Bootstrap 95% CI for the slope: −0.010 to −0.032 log points per +10 pts D.
   - The pattern is the same using 2026 voter-file affiliation as the lean measure.

   ![scatter](output/precinct_ratio_scatter.png)

2. **The effect on the mail electorate's partisan makeup is small.** Suppose each precinct's 2022
   mail ballots voted the same way in 2026 but came in 2026-request proportions. Whaley's share
   of the mail vote would move from **57.3% to 57.0%** (−0.4 pts). The geographic shift is real but
   only worth tenths of a point.

3. **Among people who have a partisan affiliation, Republicans are requesting mail ballots at a
   higher rate than Democrats** (2026 to date, countywide):

   | Affiliation | Registered | Requests | Request rate | Share of requests |
   |---|---:|---:|---:|---:|
   | Democratic | 144,190 | 17,217 | 11.9% | 25.1% |
   | Republican | 74,092 | 10,114 | **13.7%** | 14.7% |
   | Unaffiliated | 685,762 | 41,186 | 6.0% | 60.0% |

   ![party](output/request_rate_by_party_2026.png)

   D-affiliated voters still outnumber R-affiliated requesters about 1.7 to 1. The share of
   requests from D-affiliated voters climbs steadily with precinct lean, from 19% in the reddest
   group to 38% in the bluest, and the R share falls from 21% to 4%. There's no 2022 voter-level
   list to compare against, so this part is a 2026 snapshot only.

### Bottom line

Franklin County mail activity in 2026 is running about two-thirds of 2022's final mail-ballot
volume at the start of voting. The gap is somewhat smaller in Republican-leaning precincts than in
heavily Democratic ones: red precincts are slightly over-represented relative to 2022, and the
bluest urban precincts are slightly under-represented. The size of the shift is modest, about
1 point of county share at each end. Statewide, mail voting has been falling as a share of early votes. In the May 2026 primary, mail
was 38% of early votes, down from 52% in May 2022. This county's data shows that drop is slightly
steeper in Democratic areas. **It is not evidence of a large partisan swing in turnout.**

## Caveats

- **Different stages.** 2026 is requests at day 28 before the election. 2022 is final ballots
  returned. If late requesters, or voters who never return their ballot, lean differently by
  partisanship, the comparison is biased. Rerun this after Election Day for a like-for-like
  comparison of 2026 returned ballots with 2022 mail ballots.
- **Party codes reflect primary history.** The 2026 Democratic primary drew unusually high
  Democratic participation, which moves some voters from U to D. That inflates D affiliation
  counts relative to earlier years.
- **One county.** Franklin is about 11% of Ohio's electorate and is strongly Democratic. The result
  may not generalize statewide. Other counties' boards would have to be queried one by one.

## Reproduce

```bash
pip install -r requirements.txt
python scripts/fetch_franklin.py     # downloads raw BOE files to data/raw/ (gitignored, contains PII)
python scripts/analyze_franklin.py   # writes data/processed/*.csv, output/*.png, output/summary.json
```

## Outputs

- `data/processed/franklin_precinct_vbm_2022_2026.csv` — one row per matched precinct
- `data/processed/franklin_vbm_by_lean.csv` (and `_stable_precincts.csv`) — lean-group summaries
- `data/processed/franklin_vbm_by_party_2026.csv` — 2026 request rate by affiliation
- `output/summary.json` — headline statistics
