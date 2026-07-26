"""
SF Apartment Search
--------------------
Scrapes Craigslist San Francisco apartment + sublet listings, and any
configured property-manager sites, filters them against your criteria,
appends new matches to a Google Sheet, writes a listings.json for the
website, and texts you a summary via Twilio.

Designed to run on a schedule (or on-demand) via GitHub Actions.
"""

import os
import re
import json
import base64
import datetime
import requests
from bs4 import BeautifulSoup

from sources import property_managers

# ---------------------------------------------------------------------------
# SEARCH CRITERIA — edit these to tune your search
# ---------------------------------------------------------------------------
MAX_PRICE = 5000
MIN_BEDROOMS = 1
MIN_BATHROOMS = 1
MIN_SQFT = 700          # listings with NO sqft listed are kept, not eliminated
REQUIRE_CATS = True
REQUIRE_PARKING = True

# Only keep listings whose neighborhood text matches one of these
# (case-insensitive substring match against the "(neighborhood)" Craigslist shows)
NEIGHBORHOODS = [
    "potrero",
    "noe valley",
    "castro",
    "nob hill",
]

# Listings mentioning any of these are tagged as lease takeovers/sublets
# in the "type" field so the site can flag them distinctly.
LEASE_TAKEOVER_KEYWORDS = [
    "lease takeover",
    "sublease",
    "sublet",
    "assume my lease",
    "assume lease",
    "transfer my lease",
    "transfer lease",
]

# ---------------------------------------------------------------------------
# CRAIGSLIST SEARCH CONFIG
# ---------------------------------------------------------------------------
# sfbay.craigslist.org covers the whole Bay Area; "sfc" restricts to SF proper.
# "apa" = apartments/housing for rent. "sub" = sublets & temporary (lease
# takeovers usually get posted here, though they show up in "apa" too).
CRAIGSLIST_CATEGORIES = {
    "apa": "https://sfbay.craigslist.org/search/sfc/apa",
    "sub": "https://sfbay.craigslist.org/search/sfc/sub",
}
BASE_URL = CRAIGSLIST_CATEGORIES["apa"]

# Craigslist parking_type checkbox values (can pass multiple):
# 1=carport 2=attached garage 3=detached garage 4=off-street parking
# 5=street parking 6=valet parking
PARKING_TYPES = [1, 2, 3, 4, 6] if REQUIRE_PARKING else []

SEEN_FILE = os.path.join(os.path.dirname(__file__), "data", "seen_listings.json")


def build_search_url(category_url, offset=0, relaxed=False):
    """relaxed=True skips bed/bath/parking filters — used for the sublets
    category, where lease-takeover posts often don't tag those fields
    correctly and would otherwise get filtered out."""
    params = {
        "hasPic": 1,
        "bundleDuplicates": 1,
        "max_price": MAX_PRICE,
        "s": offset,
    }
    if not relaxed:
        params["min_bedrooms"] = MIN_BEDROOMS
        params["min_bathrooms"] = MIN_BATHROOMS
    if REQUIRE_CATS and not relaxed:
        params["pets_cat"] = 1

    query = "&".join(f"{k}={v}" for k, v in params.items())
    if not relaxed:
        for p in PARKING_TYPES:
            query += f"&parking_type={p}"
    return f"{category_url}?{query}"


def tag_listing_type(title, meta_text):
    text = f"{title} {meta_text}".lower()
    if any(k in text for k in LEASE_TAKEOVER_KEYWORDS):
        return "lease takeover / sublet"
    return "standard rental"


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen_ids):
    os.makedirs(os.path.dirname(SEEN_FILE), exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen_ids), f, indent=2)


def matches_neighborhood(text):
    text_lower = text.lower()
    return any(n in text_lower for n in NEIGHBORHOODS)


def parse_sqft(housing_text):
    """Craigslist shows something like '1br - 750ft2 -' in the result meta."""
    match = re.search(r"(\d+)\s*ft2", housing_text)
    return int(match.group(1)) if match else None


def scrape_craigslist_category(category_name, category_url):
    """Returns a list of dicts for listings in one Craigslist category."""
    results = []
    headers = {"User-Agent": "Mozilla/5.0 (apartment search script)"}
    relaxed = category_name == "sub"

    offset = 0
    max_pages = 5  # ~120 listings per run is plenty; raise if needed
    for page in range(max_pages):
        url = build_search_url(category_url, offset=offset, relaxed=relaxed)
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            print(f"Warning: got status {resp.status_code} for {url}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select("li.cl-static-search-result, div.cl-search-result")
        if not rows:
            # Craigslist changes markup periodically — fall back to older selector
            rows = soup.select("li.result-row")
        if not rows:
            break

        for row in rows:
            link_tag = row.select_one("a")
            title_tag = row.select_one(".title, .result-title")
            price_tag = row.select_one(".price, .result-price")
            meta_tag = row.select_one(".meta, .housing")
            hood_tag = row.select_one(".location, .result-hood")

            if not link_tag or not title_tag:
                continue

            url_link = link_tag.get("href", "")
            listing_id = re.search(r"/(\d+)\.html", url_link)
            listing_id = listing_id.group(1) if listing_id else url_link

            title = title_tag.get_text(strip=True)
            price_text = price_tag.get_text(strip=True) if price_tag else ""
            meta_text = meta_tag.get_text(" ", strip=True) if meta_tag else ""
            hood_text = hood_tag.get_text(strip=True) if hood_tag else title
            listing_type = tag_listing_type(title, meta_text)

            sqft = parse_sqft(meta_text)
            # Relaxed (sublet) category: only enforce price/sqft, not bed/bath/
            # parking/neighborhood, since those posts are often loosely tagged
            # and takeover posts are worth seeing regardless of neighborhood.
            if sqft is not None and sqft < MIN_SQFT:
                continue
            if not relaxed:
                if not matches_neighborhood(hood_text) and not matches_neighborhood(title):
                    continue

            results.append({
                "id": f"cl-{listing_id}",
                "source": "Craigslist",
                "type": listing_type,
                "title": title,
                "price": price_text,
                "sqft": sqft if sqft else "n/a",
                "neighborhood": hood_text,
                "url": url_link,
            })

        offset += 120  # Craigslist paginates in chunks of 120

    return results


def scrape_craigslist():
    """Scrapes all configured Craigslist categories (rentals + sublets)."""
    results = []
    for name, url in CRAIGSLIST_CATEGORIES.items():
        results.extend(scrape_craigslist_category(name, url))
    return results


def filter_new(listings, seen_ids):
    return [l for l in listings if l["id"] not in seen_ids]


# ---------------------------------------------------------------------------
# GOOGLE SHEETS
# ---------------------------------------------------------------------------
def append_to_google_sheet(new_listings):
    if not new_listings:
        return

    import gspread
    from google.oauth2.service_account import Credentials

    creds_b64 = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON_B64"]
    creds_dict = json.loads(base64.b64decode(creds_b64))
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(creds)

    sheet_id = os.environ["GOOGLE_SHEET_ID"]
    sh = gc.open_by_key(sheet_id)
    ws = sh.sheet1

    if ws.row_count == 0 or not ws.acell("A1").value:
        ws.append_row(["Source", "Type", "Title", "Price", "Sqft", "Neighborhood", "URL", "Found"])

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    for l in new_listings:
        ws.append_row([
            l.get("source", ""), l.get("type", ""), l["title"], l["price"],
            l["sqft"], l["neighborhood"], l["url"], now,
        ])


# ---------------------------------------------------------------------------
# TWILIO SMS
# ---------------------------------------------------------------------------
def send_text_summary(new_listings):
    if not new_listings:
        return

    from twilio.rest import Client

    sid = os.environ["TWILIO_ACCOUNT_SID"]
    token = os.environ["TWILIO_AUTH_TOKEN"]
    from_number = os.environ["TWILIO_FROM_NUMBER"]
    to_number = os.environ["TWILIO_TO_NUMBER"]
    sheet_url = os.environ.get("GOOGLE_SHEET_URL", "your Google Sheet")

    client = Client(sid, token)

    count = len(new_listings)
    top = new_listings[:3]
    lines = [f"{count} new SF apartment match{'es' if count != 1 else ''}:"]
    for l in top:
        lines.append(f"- {l['price']} {l['neighborhood']}: {l['title'][:40]}")
    if count > 3:
        lines.append(f"...and {count - 3} more.")
    lines.append(f"Full list: {sheet_url}")

    body = "\n".join(lines)
    client.messages.create(body=body, from_=from_number, to=to_number)


# ---------------------------------------------------------------------------
# WEBSITE DATA FILE
# ---------------------------------------------------------------------------
SITE_DATA_FILE = os.path.join(os.path.dirname(__file__), "docs", "listings.json")


def write_site_data(all_listings):
    os.makedirs(os.path.dirname(SITE_DATA_FILE), exist_ok=True)
    payload = {
        "last_updated": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "count": len(all_listings),
        "listings": sorted(all_listings, key=lambda l: l.get("price", "")),
    }
    with open(SITE_DATA_FILE, "w") as f:
        json.dump(payload, f, indent=2)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    print("Scraping Craigslist (rentals + sublets)...")
    listings = scrape_craigslist()

    print("Scraping configured property manager sites...")
    listings += property_managers.scrape_all(
        max_price=MAX_PRICE,
        min_sqft=MIN_SQFT,
        neighborhoods=NEIGHBORHOODS,
    )

    print(f"Found {len(listings)} listings matching filters.")

    seen_ids = load_seen()
    new_listings = filter_new(listings, seen_ids)
    print(f"{len(new_listings)} are new since last run.")

    if new_listings:
        append_to_google_sheet(new_listings)
        send_text_summary(new_listings)

    # The website always shows the full current set, not just new ones,
    # so it stays useful even between "new listing" events.
    write_site_data(listings)

    seen_ids.update(l["id"] for l in listings)
    save_seen(seen_ids)
    print("Done.")


if __name__ == "__main__":
    main()
