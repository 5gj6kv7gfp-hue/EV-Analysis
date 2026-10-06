"""Download Franklin County (OH) BOE source files into data/raw/ (not committed: contains voter PII).

Sources
- 2026 absentee-by-mail voter list (current election) and countywide voter file:
  https://vote.franklincountyohio.gov/maps-and-data/voter-and-absentee-data-files
  (ASP.NET "ElectionVault" page; files are served via form postback.)
- 2014-2024 General official results, precinct x vote-type group exports (XLSX):
  https://vote.franklincountyohio.gov/election-info/<year>
"""
import pathlib
import re
import sys
import urllib.parse

import requests
from bs4 import BeautifulSoup

RAW = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw"
VAULT = "https://vote.franklincountyohio.gov/maps-and-data/voter-and-absentee-data-files"
GETMEDIA = "https://vote.franklincountyohio.gov/getmedia/"
# General-election official results by precinct x vote-type group, linked from
# https://vote.franklincountyohio.gov/election-info/<year>
RESULTS = {
    2014: "4b690b68-a10b-41d1-8947-9bd4f115954e/Precinct-Level-Group-Detail-With-Overlaps",
    2016: "9e0270f2-b6fb-44f6-9910-ba7092deb9a6/2016-General-Election-with-Overlaps-Precinct-Detail-and-Groups",
    2018: "b3db9f60-356b-40c1-9d19-bae59f2fbede/General-2018-Official-with-Groups",
    2020: "c1663e97-e9e0-48db-a226-6e2637c1f312/2020-General-Election",
    2022: "74e76239-02d4-4bb6-8ca0-bdea84a1995e/Election-Export-Precinct-by-group",
    2024: "484f73e8-f2e2-465f-9092-6f56c952757e/Official-Results-by-Precinct-With-Group-Detail",
}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "Chrome/128 Safari/537.36"}

# served filename on the ElectionVault page -> local filename
VAULT_FILES = {
    "Absentee by Mail Voter List (Current Election).txt": "fc_abs_mail_2026.txt",
    "VOTERFILE.TXT": "fc_voterfile_2026.txt",
}


def vault_download(session, filename, out):
    """Find the ElectionVault button whose download is named `filename` and save it.

    Button labels on the page don't reliably line up with the files served, so each
    candidate is matched on the response's Content-Disposition filename instead.
    """
    page = session.get(VAULT, timeout=60)
    soup = BeautifulSoup(page.text, "html.parser")
    form = soup.find("form")
    base = {i["name"]: i.get("value", "") for i in form.find_all("input")
            if i.get("name") and i.get("type") in ("hidden", None, "text")}
    url = urllib.parse.urljoin(page.url, form.get("action"))
    for target in re.findall(r"uniqueID':'([^']+btnDownload)'", page.text):
        data = dict(base, __EVENTTARGET=target, __EVENTARGUMENT="")
        with session.post(url, data=data, stream=True, timeout=900) as r:
            r.raise_for_status()
            served = re.search(r'filename="?([^";]+)', r.headers.get("content-disposition", ""))
            if not served or served.group(1).strip() != filename:
                continue
            with open(out, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
            return
    raise RuntimeError(f"{filename} not found on {VAULT}")


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update(UA)
    for served, name in VAULT_FILES.items():
        print("downloading", served, file=sys.stderr)
        vault_download(s, served, RAW / name)
    for year, path in RESULTS.items():
        print(f"downloading {year} general precinct-by-group results", file=sys.stderr)
        r = s.get(GETMEDIA + path, timeout=600)
        r.raise_for_status()
        (RAW / f"fc_{year}gen_precinct_group.xlsx").write_bytes(r.content)


if __name__ == "__main__":
    main()
