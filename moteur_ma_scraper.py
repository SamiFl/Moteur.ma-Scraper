"""
moteur_ma_scraper.py
────────────────────
Scrapes new-car data from moteur.ma:
  Brand → Models → Versions (name, fuel, gearbox, CV, HP, price, URL)

Outputs:
  - moteur_ma_cars.json   (hierarchical: brand > model > versions[])
  - moteur_ma_cars.csv    (flat, one row per version)

Usage:
  python moteur_ma_scraper.py                      # all brands
  python moteur_ma_scraper.py --brands dacia renault bmw  # subset
  python moteur_ma_scraper.py --delay 1.5          # custom delay (seconds)
"""

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ── Config ──────────────────────────────────────────────────────────────────

BASE_URL   = "https://www.moteur.ma"
NEW_CARS   = f"{BASE_URL}/fr/neuf/voiture/"
HEADERS    = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
DEFAULT_DELAY = 1.2   # seconds between requests


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass
class Version:
    brand:        str
    model:        str
    version_name: str
    fuel:         str
    gearbox:      str
    fiscal_power: str        # CV
    horsepower:   str        # CH
    price_dhs:    Optional[int]
    is_promo:     bool
    url:          str


@dataclass
class Model:
    brand:      str
    model_name: str
    url:        str
    versions:   list[Version] = field(default_factory=list)


@dataclass
class Brand:
    brand_name: str
    url:        str
    models:     list[Model] = field(default_factory=list)


# ── HTTP helpers ─────────────────────────────────────────────────────────────

session = requests.Session()
session.headers.update(HEADERS)


def get(url: str, delay: float = DEFAULT_DELAY) -> Optional[BeautifulSoup]:
    """Fetch a URL and return a BeautifulSoup, or None on error."""
    try:
        time.sleep(delay)
        r = session.get(url, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")
    except requests.RequestException as e:
        print(f"  [WARN] Could not fetch {url}: {e}", file=sys.stderr)
        return None


def parse_price(text: str) -> Optional[int]:
    """'226 900 Dhs' → 226900"""
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


# ── Scraping logic ────────────────────────────────────────────────────────────

def scrape_brands(soup: BeautifulSoup) -> list[Brand]:
    """Extract all brand names + URLs from the main new-cars page."""
    brands = []
    # Brand links appear as  /fr/neuf/voiture/{brand}/
    pattern = re.compile(r"^/fr/neuf/voiture/([^/]+)/$")
    seen = set()

    for a in soup.find_all("a", href=pattern):
        slug = pattern.match(a["href"]).group(1)
        if slug in seen:
            continue
        seen.add(slug)
        name = a.get_text(strip=True) or slug.replace("-", " ").title()
        brands.append(Brand(
            brand_name=name,
            url=BASE_URL + a["href"],
        ))
    return brands


def scrape_models(brand: Brand, soup: BeautifulSoup) -> list[Model]:
    """Extract all model URLs from a brand page."""
    models = []
    pattern = re.compile(
        rf"^/fr/neuf/voiture/{re.escape(brand.url.split('/')[-2])}/([^/]+)/$"
    )
    # Also accept any sub-path one level deeper
    generic = re.compile(r"^/fr/neuf/voiture/[^/]+/([^/]+)/$")
    seen = set()

    for a in soup.find_all("a", href=generic):
        href = a["href"]
        # skip brand-level URL itself
        if href.rstrip("/") == brand.url.rstrip("/").replace(BASE_URL, ""):
            continue
        # must be exactly  /fr/neuf/voiture/{brand}/{model}/
        parts = href.strip("/").split("/")
        if len(parts) != 5:   # fr/neuf/voiture/{brand}/{model}
            continue
        if href in seen:
            continue
        seen.add(href)
        model_name = a.get_text(strip=True) or parts[-1].replace("-", " ").title()
        models.append(Model(
            brand=brand.brand_name,
            model_name=model_name,
            url=BASE_URL + href,
        ))
    return models


def scrape_versions(brand_name: str, model: Model, soup: BeautifulSoup) -> list[Version]:
    """Extract all versions + prices from a model page."""
    versions = []
    # Each version is an <li> inside the versions list
    # Pattern in the HTML: each version block has the version name, specs, and price

    # Find the versions section — they're in a <ul> or repeated <li> blocks
    # with links like /fr/neuf/voiture/{brand}/{model}/{brand}-{model}-{slug}.html
    version_pattern = re.compile(r"\.html$")

    seen_urls = set()
    for a in soup.find_all("a", href=version_pattern):
        href = a["href"]
        if href in seen_urls:
            continue
        seen_urls.add(href)

        full_url = BASE_URL + href if href.startswith("/") else href

        # The <li> containing this link holds name + spec tags
        parent = a
        # Walk up to find an enclosing container
        for _ in range(6):
            parent = parent.parent
            if parent is None:
                break
            if parent.name in ("li", "div", "article"):
                break

        text_block = parent.get_text(" ", strip=True) if parent else a.get_text(strip=True)

        # Version name: direct text nodes only (skip child <span> tags)
        version_name = " ".join(
            t.strip() for t in a.find_all(string=True, recursive=False)
            if t.strip()
        )
        if not version_name:
            version_name = " ".join(a.get_text().split())

        # Price: look for "xxx xxx Dhs" pattern
        price_match = re.search(r"([\d\s]+)\s*Dhs", text_block)
        price = parse_price(price_match.group(1)) if price_match else None

        # Fuel
        fuel = ""
        for kw in ("Diesel", "Essence", "Électrique", "Electrique", "Hybride", "GPL", "PHEV", "HEV"):
            if kw.lower() in text_block.lower():
                fuel = kw
                break

        # Gearbox
        gearbox = ""
        for kw in ("Automatique", "Manuelle", "Semi-automatique"):
            if kw.lower() in text_block.lower():
                gearbox = kw
                break

        # Fiscal power (CV)
        cv_match = re.search(r"(\d+)\s*CV", text_block)
        fiscal_power = cv_match.group(1) + " CV" if cv_match else ""

        # Horsepower (CH)
        ch_match = re.search(r"(\d+)\s*CH", text_block)
        horsepower = ch_match.group(1) + " CH" if ch_match else ""

        # Is promo?
        is_promo = "promo" in text_block.lower()

        versions.append(Version(
            brand=brand_name,
            model=model.model_name,
            version_name=version_name,
            fuel=fuel,
            gearbox=gearbox,
            fiscal_power=fiscal_power,
            horsepower=horsepower,
            price_dhs=price,
            is_promo=is_promo,
            url=full_url,
        ))

    return versions


# ── Output helpers ────────────────────────────────────────────────────────────

def to_hierarchical(brands: list[Brand]) -> dict:
    """Build a clean nested dict for JSON output."""
    result = {}
    for brand in brands:
        result[brand.brand_name] = {}
        for model in brand.models:
            result[brand.brand_name][model.model_name] = {
                "url": model.url,
                "versions": [
                    {
                        "version": v.version_name,
                        "fuel": v.fuel,
                        "gearbox": v.gearbox,
                        "fiscal_power_cv": v.fiscal_power,
                        "horsepower_ch": v.horsepower,
                        "price_dhs": v.price_dhs,
                        "is_promo": v.is_promo,
                        "url": v.url,
                    }
                    for v in model.versions
                ],
            }
    return result


def save_json(data: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✓ JSON saved → {path}")


def save_csv(brands: list[Brand], path: str):
    fieldnames = [
        "brand", "model", "version", "fuel", "gearbox",
        "fiscal_power_cv", "horsepower_ch", "price_dhs", "is_promo", "url",
    ]
    rows = []
    for brand in brands:
        for model in brand.models:
            for v in model.versions:
                rows.append({
                    "brand": v.brand,
                    "model": v.model,
                    "version": v.version_name,
                    "fuel": v.fuel,
                    "gearbox": v.gearbox,
                    "fiscal_power_cv": v.fiscal_power,
                    "horsepower_ch": v.horsepower,
                    "price_dhs": v.price_dhs,
                    "is_promo": v.is_promo,
                    "url": v.url,
                })
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ CSV saved → {path}  ({len(rows)} versions total)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Scrape moteur.ma new cars")
    parser.add_argument(
        "--brands", nargs="+", metavar="BRAND",
        help="Limit scraping to specific brand slugs (e.g. dacia bmw renault)"
    )
    parser.add_argument(
        "--delay", type=float, default=DEFAULT_DELAY,
        help=f"Seconds between requests (default {DEFAULT_DELAY})"
    )
    _today = datetime.now().strftime("%-d-%-m-%Y")   # e.g. 23-6-2026
    parser.add_argument(
        "--out-json",
        default=f"moteur_ma_cars_{_today}.json",
        help="Output JSON file path (default includes today's date)",
    )
    parser.add_argument(
        "--out-csv",
        default=f"moteur_ma_cars_{_today}.csv",
        help="Output CSV file path (default includes today's date)",
    )
    args = parser.parse_args()

    print(f"\n{'═'*55}")
    print(f"  moteur.ma scraper  —  {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'═'*55}\n")

    # ── Step 1: main page → brands ────────────────────────────────────────
    print("⬇  Fetching brand list …")
    main_soup = get(NEW_CARS, delay=0)
    if not main_soup:
        print("Fatal: could not load main page", file=sys.stderr)
        sys.exit(1)

    all_brands = scrape_brands(main_soup)
    print(f"   Found {len(all_brands)} brands")

    # Filter if --brands flag given
    if args.brands:
        wanted = {b.lower() for b in args.brands}
        all_brands = [
            b for b in all_brands
            if any(slug in b.url.lower() for slug in wanted)
        ]
        print(f"   Filtered to {len(all_brands)} brand(s): "
              f"{[b.brand_name for b in all_brands]}")

    # ── Step 2: brand page → models ──────────────────────────────────────
    for brand in all_brands:
        print(f"\n── {brand.brand_name}")
        brand_soup = get(brand.url, delay=args.delay)
        if not brand_soup:
            continue

        brand.models = scrape_models(brand, brand_soup)
        print(f"   {len(brand.models)} model(s) found")

        # ── Step 3: model page → versions ────────────────────────────────
        for model in brand.models:
            model_soup = get(model.url, delay=args.delay)
            if not model_soup:
                continue

            model.versions = scrape_versions(brand.brand_name, model, model_soup)
            version_count = len(model.versions)
            price_str = ""
            if model.versions:
                prices = [v.price_dhs for v in model.versions if v.price_dhs]
                if prices:
                    price_str = f"  [{min(prices):,} – {max(prices):,} Dhs]"

            print(f"   ├─ {model.model_name}: {version_count} version(s){price_str}")

    # ── Step 4: output ───────────────────────────────────────────────────
    print(f"\n{'─'*55}")
    print("💾 Saving output …")
    hierarchical = to_hierarchical(all_brands)
    save_json(hierarchical, args.out_json)
    save_csv(all_brands, args.out_csv)

    total_versions = sum(
        len(m.versions)
        for b in all_brands
        for m in b.models
    )
    total_models = sum(len(b.models) for b in all_brands)
    print(f"\n✅ Done — {len(all_brands)} brands, "
          f"{total_models} models, {total_versions} versions scraped.")


if __name__ == "__main__":
    main()
