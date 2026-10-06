"""Download Franklin County (OH) BOE source files into data/raw/ (not committed: contains voter PII).

Sources
- 2026 absentee-by-mail voter list (current election) and countywide voter file:
  https://vote.franklincountyohio.gov/maps-and-data/voter-and-absentee-data-files
  (ASP.NET "ElectionVault" page; files are served via form postback.)
- 2022 General official results, precinct x vote-type group export (XLSX):
  https://vote.franklincountyohio.gov/election-info/2022
"""
import pathlib
import re
import sys
import urllib.parse

import requests
from bs4 import BeautifulSoup

RAW = pathlib.Path(__file__).resolve().parents[1] / "data" / "raw"
VAULT = "https://vote.franklincountyohio.gov/maps-and-data/voter-and-absentee-data-files"
RESULTS_2022 = ("https://vote.franklincountyohio.gov/getmedia/"
                "74e76239-02d4-4bb6-8ca0-bdea84a1995e/Election-Export-Precinct-by-group")
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
    print("downloading 2022 general precinct-by-group results", file=sys.stderr)
    r = s.get(RESULTS_2022, timeout=300)
    r.raise_for_status()
    (RAW / "fc_2022gen_precinct_group.xlsx").write_bytes(r.content)


if __name__ == "__main__":
    main()
