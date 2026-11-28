"""Verify the public atlas can be served without private files or a private repository."""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from investment_os.notes import PRIVATE_REPOS

ATLAS = Path(__file__).resolve().parents[1] / "site/method-atlas"


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {"src", "href"}:
                self.targets.append(value)


def test_public_method_snapshot():
    catalog = json.loads((ATLAS / "catalog.json").read_text())
    cards = catalog["cards"]
    ids = {c["id"] for c in cards}
    assert ids and len(ids) == len(cards)
    index = Links()
    index.feed((ATLAS / "results/index.html").read_text())
    assert {s.removeprefix("../#method=") for s in index.targets if s.startswith("../#method=")} == ids
    results = {t for t in index.targets if re.fullmatch(r"[a-z0-9-]+\.html", t)}
    allowed = {"app.js", "app.css", "index.html", "catalog.json", "results/index.html"}
    allowed.update(f"results/{name}" for name in results)
    assert not any(p.is_symlink() for p in ATLAS.rglob("*"))
    assert {p.relative_to(ATLAS).as_posix() for p in ATLAS.rglob("*") if p.is_file()} == allowed
    assert {r["id"] + ".html" for r in catalog["records"]} <= results
    for card in cards:
        assert set(card["related"]) <= ids
        assert all(e["source_path"] in allowed for e in card["evidence"])
        assert all(run["test"] + ".html" in results for run in card["ui"].get("executions", []))
        for report in card["reports"]:
            assert report["url"].startswith("../notes/companies/")
            assert (ATLAS.parents[1] / report["url"][3:].rstrip("/")).with_suffix(".md").is_file()
    for name in allowed:
        text = (ATLAS / name).read_text()
        assert not any(repo in text.lower() for repo in PRIVATE_REPOS), name
        assert not re.search(r"(?i)\bfile:|~/|/(?:Users|home)/|\b[A-Z]:\\\\", text), name
        if name.startswith("results/"):
            links = Links()
            links.feed(text)
            assert all(target in {"../../", "../", "./", "../app.css"} or target in results
                       or target.removeprefix("../#method=") in ids for target in links.targets), name
