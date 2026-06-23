"""
moteur_ma_scraper.py
────────────────────
Scrapes new-car data from moteur.ma:
  Brand → Models → Versions (name, fuel, gearbox, CV, HP, price, URL)

Outputs:
  - moteur_ma_cars_<D-M-YYYY>.json   (hierarchical: brand > model > versions[])
  - moteur_ma_cars_<D-M-YYYY>.csv    (flat, one row per version)

Usage:
  python3 moteur_ma_scraper.py                           # all brands
  python3 moteur_ma_scraper.py --brands dacia renault bmw  # subset
  python3 moteur_ma_scraper.py --delay 1.5               # custom delay (seconds)
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
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# ── Config ───────────────────────────────────────────────────────────────────

BASE_URL      = "https://www.moteur.ma"
NEW_CARS_URL  = f"{BASE_URL}/fr/neuf/voiture/"
HEADERS       = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}
DEFAULT_DELAY = 1.2   # seconds between requests


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Version:
    brand:        str
    model:        str
    version_name: str
    fuel:         str
    gearbox:      str
    fiscal_power: str
    horsepower:   str
    price_dhs:    Optional[int]
    is_promo:     bool
    url:          str


@dataclass
class Model:
    brand:      str
    model_name: str
    url:        str
    versions:   list = field(default_factory=list)


@dataclass
class Brand:
    brand_name: str
    slug:       str
    url:        str
    models:     list = field(default_factory=list)


# ── HTTP helper ───────────────────────────────────────────────────────────────

session = requests.Session()
session.headers.update(HEADERS)


def get(url: str, delay: float = DEFAULT_DELAY) -> Optional[BeautifulSoup]:
    try:
        time.sleep(delay)
        r = session.get(url, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.text, "lxml")
    except requests.RequestException as e:
        print(f"  [WARN] {url}: {e}", file=sys.stderr)
        return None


# ── URL helpers ───────────────────────────────────────────────────────────────

def path_parts(href: str) -> list:
    """Return non-empty path segments from any URL (relative or absolute)."""
    return [p for p in urlparse(href).path.split("/") if p]


def is_brand_url(href: str) -> bool:
    """True for /fr/neuf/voiture/{brand}/ — exactly 4 path segments."""
    parts = path_parts(href)
    return (
        len(parts) == 4
        and parts[:3] == ["fr", "neuf", "voiture"]
    )


def is_model_url(href: str, brand_slug: str = "") -> bool:
    """True for /fr/neuf/voiture/{brand}/{model}/ — exactly 5 path segments."""
    parts = path_parts(href)
    ok = (
        len(parts) == 5
        and parts[:3] == ["fr", "neuf", "voiture"]
    )
    if ok and brand_slug:
        ok = parts[3] == brand_slug
    return ok


def canonical(href: str) -> str:
    """Return absolute URL, ensuring trailing slash."""
    path = urlparse(href).path.rstrip("/") + "/"
    return BASE_URL + path


# ── Parsing helpers ───────────────────────────────────────────────────────────

def parse_price(text: str) -> Optional[int]:
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None


# ── Scraping logic ────────────────────────────────────────────────────────────

def scrape_brands(soup: BeautifulSoup) -> list:
    brands, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not is_brand_url(href):
            continue
        parts = path_parts(href)
        slug = parts[3]
        if slug in seen:
            continue
        seen.add(slug)
        name = a.get_text(strip=True)
        # Clean "Marque BMW BMW" or "BMW Maroc" → "BMW"
        name = re.sub(r"(?i)^marque\s+", "", name)
        name = re.sub(r"(?i)\s+maroc$", "", name).strip()
        if not name:
            name = slug.replace("-", " ").title()
        brands.append(Brand(brand_name=name, slug=slug, url=canonical(href)))
    return brands


def scrape_models(brand: Brand, soup: BeautifulSoup) -> list:
    models, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not is_model_url(href, brand.slug):
            continue
        url = canonical(href)
        if url in seen:
            continue
        seen.add(url)
        parts = path_parts(href)
        model_slug = parts[4]
        name = a.get_text(strip=True)
        # Clean "BMW Série 3" or "Série 3 Série 3" → take first meaningful chunk
        name = re.sub(r"(?i)^" + re.escape(brand.brand_name) + r"\s*", "", name).strip()
        if not name:
            name = model_slug.replace("-", " ").title()
        models.append(Model(brand=brand.brand_name, model_name=name, url=url))
    return models


def scrape_versions(brand_name: str, model: Model, soup: BeautifulSoup) -> list:
    versions, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        parsed_path = urlparse(href).path
        if not (parsed_path.endswith(".html") and parsed_path.startswith("/fr/neuf/voiture/")):
            continue
        url = BASE_URL + parsed_path
        if url in seen:
            continue
        seen.add(url)

        # Walk up to enclosing li/div/article
        parent = a
        for _ in range(6):
            parent = parent.parent
            if parent is None:
                break
            if parent.name in ("li", "div", "article"):
                break

        block = parent.get_text(" ", strip=True) if parent else a.get_text()

        # Version name: direct text nodes only (no nested span text)
        version_name = " ".join(
            t.strip() for t in a.find_all(string=True, recursive=False)
            if t.strip()
        ) or " ".join(a.get_text().split())

        price_m = re.search(r"([\d\s]+)\s*Dhs", block)
        cv_m    = re.search(r"(\d+)\s*CV", block)
        ch_m    = re.search(r"(\d+)\s*[Cc][Hh](?:\b|$)", block)

        fuel = next(
            (k for k in ("Diesel", "Essence", "Électrique", "Electrique",
                         "Hybride", "PHEV", "HEV", "GPL")
             if k.lower() in block.lower()), ""
        )
        gearbox = next(
            (k for k in ("Automatique", "Manuelle", "Semi-automatique")
             if k.lower() in block.lower()), ""
        )

        versions.append(Version(
            brand=brand_name,
            model=model.model_name,
            version_name=version_name,
            fuel=fuel,
            gearbox=gearbox,
            fiscal_power=cv_m.group(1) + " CV" if cv_m else "",
            horsepower=ch_m.group(1) + " CH" if ch_m else "",
            price_dhs=parse_price(price_m.group(1)) if price_m else None,
            is_promo="promo" in block.lower(),
            url=url,
        ))
    return versions


# ── Output ────────────────────────────────────────────────────────────────────

def to_hierarchical(brands: list) -> dict:
    out = {}
    for brand in brands:
        out[brand.brand_name] = {}
        for model in brand.models:
            out[brand.brand_name][model.model_name] = {
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
    return out


def save_json(data: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✓ JSON → {path}")


def save_csv(brands: list, path: str):
    fields = ["brand", "model", "version", "fuel", "gearbox",
              "fiscal_power_cv", "horsepower_ch", "price_dhs", "is_promo", "url"]
    rows = [
        {"brand": v.brand, "model": v.model, "version": v.version_name,
         "fuel": v.fuel, "gearbox": v.gearbox,
         "fiscal_power_cv": v.fiscal_power, "horsepower_ch": v.horsepower,
         "price_dhs": v.price_dhs, "is_promo": v.is_promo, "url": v.url}
        for brand in brands for model in brand.models for v in model.versions
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  ✓ CSV  → {path}  ({len(rows)} versions)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    _today = datetime.now().strftime("%-d-%-m-%Y")   # e.g. 23-6-2026

    parser = argparse.ArgumentParser(description="Scrape moteur.ma new cars")
    parser.add_argument("--brands", nargs="+", metavar="BRAND",
                        help="Brand slugs to scrape (e.g. dacia bmw renault)")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                        help=f"Seconds between requests (default {DEFAULT_DELAY})")
    parser.add_argument("--out-json", default=f"moteur_ma_cars_{_today}.json")
    parser.add_argument("--out-csv",  default=f"moteur_ma_cars_{_today}.csv")
    args = parser.parse_args()

    print(f"\n{'═'*55}")
    print(f"  moteur.ma scraper  —  {datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'═'*55}\n")

    # Step 1 — brand list
    print("⬇  Fetching brand list …")
    main_soup = get(NEW_CARS_URL, delay=0)
    if not main_soup:
        print("Fatal: could not load main page", file=sys.stderr)
        sys.exit(1)

    all_brands = scrape_brands(main_soup)
    print(f"   Found {len(all_brands)} brands")

    if args.brands:
        wanted = {b.lower() for b in args.brands}
        all_brands = [b for b in all_brands if b.slug in wanted]
        print(f"   Filtered to {len(all_brands)}: {[b.brand_name for b in all_brands]}")

    # Step 2 — models per brand
    for brand in all_brands:
        print(f"\n── {brand.brand_name}  ({brand.url})")
        brand_soup = get(brand.url, delay=args.delay)
        if not brand_soup:
            continue
        brand.models = scrape_models(brand, brand_soup)
        print(f"   {len(brand.models)} model(s)")

        # Step 3 — versions per model
        for model in brand.models:
            model_soup = get(model.url, delay=args.delay)
            if not model_soup:
                continue
            model.versions = scrape_versions(brand.brand_name, model, model_soup)
            prices = [v.price_dhs for v in model.versions if v.price_dhs]
            price_str = f"  [{min(prices):,}–{max(prices):,} Dhs]" if prices else ""
            print(f"   ├─ {model.model_name}: {len(model.versions)} version(s){price_str}")

    # Step 4 — save
    print(f"\n{'─'*55}")
    print("💾 Saving …")
    save_json(to_hierarchical(all_brands), args.out_json)
    save_csv(all_brands, args.out_csv)

    total_v = sum(len(m.versions) for b in all_brands for m in b.models)
    total_m = sum(len(b.models) for b in all_brands)
    print(f"\n✅ {len(all_brands)} brands, {total_m} models, {total_v} versions.")


if __name__ == "__main__":
    main()
