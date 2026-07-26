"""
Property manager site plugins.
-------------------------------
Unlike Craigslist, there's no universal format for property management
company listing pages — every company's site is structured differently,
and many are JS-rendered (listings load in after the page loads, so a
simple HTTP fetch never sees them) or actively block scrapers with bot
detection (Cloudflare, etc.). Because of that, this file is a PLUGIN
SYSTEM, not a magic "works on any site" scraper.

Each entry in SOURCES is one company, with a small function that knows
how to parse *that specific site*. Add new companies by writing a new
function following the ADD_A_NEW_SOURCE template at the bottom and
registering it in SOURCES.

IMPORTANT: sites change their HTML periodically, and some block scripted
requests outright. Test each source locally (`python -m sources.property_managers`)
after adding it, and expect occasional maintenance.
"""

import re
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (apartment search script)"}


def _parse_sqft(text):
    match = re.search(r"(\d+)\s*(?:sq\s*ft|sqft|ft2)", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _matches_neighborhood(text, neighborhoods):
    text_lower = text.lower()
    return any(n in text_lower for n in neighborhoods)


def _parse_price_to_int(price_text):
    digits = re.sub(r"[^\d]", "", price_text or "")
    return int(digits) if digits else None


# ---------------------------------------------------------------------------
# RENTALS IN SF (rentalsinsf.com) — real, working source
# ---------------------------------------------------------------------------
# WordPress site with predictable structure: category pages under /listings/
# by bedroom count, each listing links to /rentals/<id>-<slug>/, and listing
# images use alt text like "Photo of 419 Fulton B San Francisco CA-0" which
# gives us a clean address even without knowing the theme's CSS class names.
#
# Note: this was built from a text-rendered fetch of the live site rather
# than raw page source, so the address/price/neighborhood extraction uses
# structural patterns (URL shape, image alt text, "$X,XXX/mo" format) that
# should be stable across theme tweaks — but if it ever returns 0 results,
# that's the first thing to check against the live page source.
RENTALSINSF_CATEGORY_URLS = [
    "https://www.rentalsinsf.com/listings/jr-and-one-bedroom/",
    "https://www.rentalsinsf.com/listings/two-bedroom/",
    "https://www.rentalsinsf.com/listings/three-bedroom/",
    "https://www.rentalsinsf.com/listings/four-bedroom/",
]


def scrape_rentalsinsf(max_price, min_sqft, neighborhoods):
    results = []
    seen_hrefs = set()

    for url in RENTALSINSF_CATEGORY_URLS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[rentalsinsf] request failed for {url}: {e}")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        detail_links = [
            a for a in soup.select('a[href*="/rentals/"]')
            if re.search(r"/rentals/\d+-", a.get("href", ""))
        ]

        for a in detail_links:
            href = a.get("href")
            if not href or href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            container = a.find_parent(["div", "li", "article"]) or a
            block_text = container.get_text(" ", strip=True)

            # Address: prefer the image alt text ("Photo of 419 Fulton B
            # San Francisco CA-0"), fall back to the link's own text.
            img = container.find("img", alt=True)
            address = None
            if img and img.get("alt", "").lower().startswith("photo of"):
                address = re.sub(r"^photo of\s+", "", img["alt"], flags=re.IGNORECASE)
                address = re.sub(r"\s+san francisco.*$", "", address, flags=re.IGNORECASE)
            if not address:
                link_text = a.get_text(strip=True)
                address = link_text if link_text and "details" not in link_text.lower() else href

            price_match = re.search(r"\$([\d,]+)\s*/\s*mo", block_text, re.IGNORECASE)
            if not price_match:
                continue  # skip anything we can't confirm a price for
            price_val = int(price_match.group(1).replace(",", ""))
            if price_val > max_price:
                continue

            # If this container swept up the page's own "Neighborhoods"
            # sidebar (which lists every neighborhood the company serves,
            # joined by "·"), block_text isn't trustworthy for matching —
            # it would make every listing on the page falsely match. Fall
            # back to the address text only in that case.
            if block_text.count("·") > 2:
                hood = next((n for n in neighborhoods if n.lower() in address.lower()), None)
                if not hood:
                    continue
            else:
                hood = next((n for n in neighborhoods if n.lower() in block_text.lower()), None)
                if not hood and not any(n.lower() in address.lower() for n in neighborhoods):
                    continue

            results.append({
                "id": f"risf-{href}",
                "source": "Rentals in SF",
                "type": "standard rental",
                "title": address,
                "price": f"${price_val:,}/mo",
                "sqft": "n/a",  # not listed on category pages
                "neighborhood": hood or "San Francisco",
                "posted": "n/a",  # current-availability listing, not a dated post
                "url": href,
            })

    return results


# ---------------------------------------------------------------------------
# EXAMPLE / TEMPLATE — for adding more sources later
# ---------------------------------------------------------------------------
def scrape_example_generic_site(max_price, min_sqft, neighborhoods):
    """
    TEMPLATE IMPLEMENTATION — not a live company. This shows the pattern:
    fetch a listings page, parse each listing card, apply the same filters
    as the Craigslist scraper, and return dicts in the same shape.

    To wire up a real company:
      1. Open their public listings/availability page in a browser.
      2. View source (or use browser devtools) to find:
         - the CSS selector for each listing "card"
         - selectors within a card for: title/address, price, sqft,
           neighborhood/location, and the link
      3. Copy this function, rename it, and swap in those selectors.
      4. If the listings don't appear in "view source" at all, the page is
         JS-rendered and this simple approach won't work for it — that
         site would need a headless-browser tool (e.g. Playwright) instead,
         which is a bigger lift. Flag it and we can add that separately.
      5. Register your new function in SOURCES below.
    """
    results = []
    url = "https://example.com/apartments"  # replace with the real URL

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[example_site] request failed: {e}")
        return results

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select(".listing-card")  # <- replace with real selector

    for card in cards:
        title_tag = card.select_one(".listing-title")
        price_tag = card.select_one(".listing-price")
        sqft_tag = card.select_one(".listing-sqft")
        hood_tag = card.select_one(".listing-neighborhood")
        link_tag = card.select_one("a")

        if not title_tag or not link_tag:
            continue

        title = title_tag.get_text(strip=True)
        price_text = price_tag.get_text(strip=True) if price_tag else ""
        sqft_text = sqft_tag.get_text(strip=True) if sqft_tag else ""
        hood_text = hood_tag.get_text(strip=True) if hood_tag else title
        link = link_tag.get("href", "")

        price = _parse_price_to_int(price_text)
        if price is not None and price > max_price:
            continue

        sqft = _parse_sqft(sqft_text)
        if sqft is not None and sqft < min_sqft:
            continue

        if not _matches_neighborhood(hood_text, neighborhoods) and not _matches_neighborhood(title, neighborhoods):
            continue

        results.append({
            "id": f"example-{link}",
            "source": "Example Property Co.",
            "type": "standard rental",
            "title": title,
            "price": price_text,
            "sqft": sqft if sqft else "n/a",
            "neighborhood": hood_text,
            "url": link,
        })

    return results


# ---------------------------------------------------------------------------
# REGISTRY — add new sources here once you've written their function above
# ---------------------------------------------------------------------------
SOURCES = {
    "rentalsinsf": scrape_rentalsinsf,
    # "rentsfnow" intentionally omitted: listings are JS-rendered and the
    # search page has active bot detection — would need a headless-browser
    # scraper (Playwright), which is heavier and may still get blocked.
    # Ask if you want that built later.
}


def scrape_all(max_price, min_sqft, neighborhoods):
    results = []
    for name, fn in SOURCES.items():
        try:
            site_results = fn(max_price=max_price, min_sqft=min_sqft, neighborhoods=neighborhoods)
            print(f"[{name}] {len(site_results)} matching listings")
            results.extend(site_results)
        except Exception as e:
            print(f"[{name}] failed: {e}")
    return results


if __name__ == "__main__":
    # Quick local test: python -m sources.property_managers
    found = scrape_all(max_price=5000, min_sqft=700, neighborhoods=["potrero", "noe", "castro", "nob hill"])
    print(f"Total: {len(found)}")
    for r in found:
        print(r)
def _parse_price_to_int(price_text):
    digits = re.sub(r"[^\d]", "", price_text or "")
    return int(digits) if digits else None


# ---------------------------------------------------------------------------
# RENTALS IN SF (rentalsinsf.com) — real, working source
# ---------------------------------------------------------------------------
# WordPress site with predictable structure: category pages under /listings/
# by bedroom count, each listing links to /rentals/<id>-<slug>/, and listing
# images use alt text like "Photo of 419 Fulton B San Francisco CA-0" which
# gives us a clean address even without knowing the theme's CSS class names.
#
# Note: this was built from a text-rendered fetch of the live site rather
# than raw page source, so the address/price/neighborhood extraction uses
# structural patterns (URL shape, image alt text, "$X,XXX/mo" format) that
# should be stable across theme tweaks — but if it ever returns 0 results,
# that's the first thing to check against the live page source.
RENTALSINSF_CATEGORY_URLS = [
    "https://www.rentalsinsf.com/listings/jr-and-one-bedroom/",
    "https://www.rentalsinsf.com/listings/two-bedroom/",
    "https://www.rentalsinsf.com/listings/three-bedroom/",
    "https://www.rentalsinsf.com/listings/four-bedroom/",
]


def scrape_rentalsinsf(max_price, min_sqft, neighborhoods):
    results = []
    seen_hrefs = set()

    for url in RENTALSINSF_CATEGORY_URLS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[rentalsinsf] request failed for {url}: {e}")
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        detail_links = [
            a for a in soup.select('a[href*="/rentals/"]')
            if re.search(r"/rentals/\d+-", a.get("href", ""))
        ]

        for a in detail_links:
            href = a.get("href")
            if not href or href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            container = a.find_parent(["div", "li", "article"]) or a
            block_text = container.get_text(" ", strip=True)

            # Address: prefer the image alt text ("Photo of 419 Fulton B
            # San Francisco CA-0"), fall back to the link's own text.
            img = container.find("img", alt=True)
            address = None
            if img and img.get("alt", "").lower().startswith("photo of"):
                address = re.sub(r"^photo of\s+", "", img["alt"], flags=re.IGNORECASE)
                address = re.sub(r"\s+san francisco.*$", "", address, flags=re.IGNORECASE)
            if not address:
                link_text = a.get_text(strip=True)
                address = link_text if link_text and "details" not in link_text.lower() else href

            price_match = re.search(r"\$([\d,]+)\s*/\s*mo", block_text, re.IGNORECASE)
            if not price_match:
                continue  # skip anything we can't confirm a price for
            price_val = int(price_match.group(1).replace(",", ""))
            if price_val > max_price:
                continue

            hood = next((n for n in neighborhoods if n.lower() in block_text.lower()), None)
            if not hood and not any(n.lower() in address.lower() for n in neighborhoods):
                continue

            results.append({
                "id": f"risf-{href}",
                "source": "Rentals in SF",
                "type": "standard rental",
                "title": address,
                "price": f"${price_val:,}/mo",
                "sqft": "n/a",  # not listed on category pages
                "neighborhood": hood or "San Francisco",
                "url": href,
            })

    return results


# ---------------------------------------------------------------------------
# EXAMPLE / TEMPLATE — for adding more sources later
# ---------------------------------------------------------------------------
def scrape_example_generic_site(max_price, min_sqft, neighborhoods):
    """
    TEMPLATE IMPLEMENTATION — not a live company. This shows the pattern:
    fetch a listings page, parse each listing card, apply the same filters
    as the Craigslist scraper, and return dicts in the same shape.

    To wire up a real company:
      1. Open their public listings/availability page in a browser.
      2. View source (or use browser devtools) to find:
         - the CSS selector for each listing "card"
         - selectors within a card for: title/address, price, sqft,
           neighborhood/location, and the link
      3. Copy this function, rename it, and swap in those selectors.
      4. If the listings don't appear in "view source" at all, the page is
         JS-rendered and this simple approach won't work for it — that
         site would need a headless-browser tool (e.g. Playwright) instead,
         which is a bigger lift. Flag it and we can add that separately.
      5. Register your new function in SOURCES below.
    """
    results = []
    url = "https://example.com/apartments"  # replace with the real URL

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[example_site] request failed: {e}")
        return results

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.select(".listing-card")  # <- replace with real selector

    for card in cards:
        title_tag = card.select_one(".listing-title")
        price_tag = card.select_one(".listing-price")
        sqft_tag = card.select_one(".listing-sqft")
        hood_tag = card.select_one(".listing-neighborhood")
        link_tag = card.select_one("a")

        if not title_tag or not link_tag:
            continue

        title = title_tag.get_text(strip=True)
        price_text = price_tag.get_text(strip=True) if price_tag else ""
        sqft_text = sqft_tag.get_text(strip=True) if sqft_tag else ""
        hood_text = hood_tag.get_text(strip=True) if hood_tag else title
        link = link_tag.get("href", "")

        price = _parse_price_to_int(price_text)
        if price is not None and price > max_price:
            continue

        sqft = _parse_sqft(sqft_text)
        if sqft is not None and sqft < min_sqft:
            continue

        if not _matches_neighborhood(hood_text, neighborhoods) and not _matches_neighborhood(title, neighborhoods):
            continue

        results.append({
            "id": f"example-{link}",
            "source": "Example Property Co.",
            "type": "standard rental",
            "title": title,
            "price": price_text,
            "sqft": sqft if sqft else "n/a",
            "neighborhood": hood_text,
            "url": link,
        })

    return results


# ---------------------------------------------------------------------------
# REGISTRY — add new sources here once you've written their function above
# ---------------------------------------------------------------------------
SOURCES = {
    "rentalsinsf": scrape_rentalsinsf,
    # "rentsfnow" intentionally omitted: listings are JS-rendered and the
    # search page has active bot detection — would need a headless-browser
    # scraper (Playwright), which is heavier and may still get blocked.
    # Ask if you want that built later.
}


def scrape_all(max_price, min_sqft, neighborhoods):
    results = []
    for name, fn in SOURCES.items():
        try:
            site_results = fn(max_price=max_price, min_sqft=min_sqft, neighborhoods=neighborhoods)
            print(f"[{name}] {len(site_results)} matching listings")
            results.extend(site_results)
        except Exception as e:
            print(f"[{name}] failed: {e}")
    return results


if __name__ == "__main__":
    # Quick local test: python -m sources.property_managers
    found = scrape_all(max_price=5000, min_sqft=700, neighborhoods=["potrero", "noe", "castro", "nob hill"])
    print(f"Total: {len(found)}")
    for r in found:
        print(r)
