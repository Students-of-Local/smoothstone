import json

from smoothstone import find


def _page(title, lic, idx, w=1200, h=1600, mime="image/jpeg"):
    return {"title": title, "index": idx, "imageinfo": [{
        "width": w, "height": h, "mime": mime, "thumburl": f"https://x/{idx}.jpg",
        "descriptionurl": f"https://c/{idx}", "extmetadata": {
            "LicenseShortName": {"value": lic}, "Artist": {"value": "<a>Someone</a>"}}}]}


def _fake(pages, lead=None):
    def get(url, timeout=30):
        if "wbsearchentities" in url:
            return json.dumps({"search": [{"id": "Q1"}] if lead else []}).encode()
        if "wbgetclaims" in url:
            return json.dumps({"claims": {"P18": [{"mainsnak": {"datavalue": {"value": lead}}}]}}).encode()
        if "titles=" in url:
            return json.dumps({"query": {"pages": {"9": _page("File:" + lead, "Public domain", 5)}}}).encode()
        if url.startswith("https://x/"):
            return b"\xff\xd8jpeg"
        return json.dumps({"query": {"pages": {str(i): p for i, p in enumerate(pages)}}}).encode()
    return get


def test_license_and_size_filter(monkeypatch):
    pages = [_page("File:Ada Lovelace.jpg", "CC BY-SA 4.0", 1),
             _page("File:Ada Lovelace 2.jpg", "All rights reserved", 2),
             _page("File:Ada Lovelace tiny.jpg", "CC0", 3, w=200, h=200),
             _page("File:Ada Lovelace.svg", "CC0", 4, mime="image/svg+xml")]
    monkeypatch.setattr(find, "_get", _fake(pages))
    got = find.search("Ada Lovelace")
    assert [c["title"] for c in got] == ["File:Ada Lovelace.jpg"]
    assert got[0]["author"] == "Someone"


def test_wikidata_main_image_leads(monkeypatch):
    pages = [_page("File:USS Abraham Lincoln at sea.jpg", "Public domain", 1),
             _page("File:Abraham Lincoln statue.jpg", "CC BY 4.0", 2)]
    monkeypatch.setattr(find, "_get", _fake(pages, lead="Abraham Lincoln portrait.jpg"))
    assert find.search("Abraham Lincoln")[0]["title"] == "File:Abraham Lincoln portrait.jpg"


def test_fetch_writes_credits(monkeypatch, tmp_path):
    pages = [_page("File:Grace Hopper.jpg", "Public domain", 1), _page("File:Grace Hopper 2.jpg", "CC BY 4.0", 2)]
    monkeypatch.setattr(find, "_get", _fake(pages))
    got = find.fetch("Grace Hopper", tmp_path, n=2)
    assert len(got) == 2 and (tmp_path / "photo_1.jpg").exists()
    credits = (tmp_path / "credits.txt").read_text()
    assert "Grace Hopper.jpg by Someone, Public domain" in credits


def test_subject_from_request():
    assert find.subject_from_request("A mini figure of Jensen Huang, 80 mm tall") == "Jensen Huang"
    assert find.subject_from_request("make a small statue of Abraham Lincoln.") == "Abraham Lincoln"
    assert find.subject_from_request("a figure of my dog") is None


def test_lead_is_not_downloaded_twice(monkeypatch):
    pages = [_page("File:Grace Hopper portrait.jpg", "Public domain", 1), _page("File:Grace Hopper 2.jpg", "CC BY 4.0", 2)]
    monkeypatch.setattr(find, "_get", _fake(pages, lead="Grace Hopper portrait.jpg"))
    titles = [c["title"] for c in find.search("Grace Hopper")]
    assert titles == ["File:Grace Hopper portrait.jpg", "File:Grace Hopper 2.jpg"]
