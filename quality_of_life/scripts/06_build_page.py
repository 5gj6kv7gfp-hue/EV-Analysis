"""Inject the data bundle into the page template -> output/us_city_well_being_index.html"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
tpl = (ROOT / "scripts/page_template.html").read_text()
data = (ROOT / "output/qol_data.json").read_text().replace("</", "<\\/")
(ROOT / "output/us_city_well_being_index.html").write_text(tpl.replace("__DATA__", data))
print("wrote output/us_city_well_being_index.html")
