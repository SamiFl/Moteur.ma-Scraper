# moteur.ma Scraper

Scrapes **new car listings** from [moteur.ma](https://www.moteur.ma) and
exports them as **JSON** (hierarchical) and **CSV** (flat, one row per version).

---

## What it collects

| Field | Example |
|---|---|
| Brand | Dacia |
| Model | Duster |
| Version name | 1.5 dCi 115 Extreme |
| Fuel type | Diesel / Essence / Électrique / Hybride |
| Gearbox | Manuelle / Automatique |
| Fiscal power | 6 CV |
| Horsepower | 115 CH |
| Price (DHS) | 260500 |
| On promotion | false |
| Detail URL | https://www.moteur.ma/… |

---

## Setup

```bash
pip install requests beautifulsoup4 lxml
```

Python 3.10+ required (uses `list[X]` type hints).

---

## Usage

```bash
# Scrape ALL brands (~70 brands, may take 15–30 min with polite delay)
python moteur_ma_scraper.py

# Scrape specific brands only
python moteur_ma_scraper.py --brands dacia renault bmw toyota

# Custom delay between requests (default 1.2s — be polite!)
python moteur_ma_scraper.py --delay 2.0

# Custom output file names
python moteur_ma_scraper.py --out-json cars.json --out-csv cars.csv

# Combine flags
python moteur_ma_scraper.py --brands dacia renault --delay 1.5 --out-json dacia_renault.json
```

---

## Output formats

### JSON — hierarchical

```json
{
  "Dacia": {
    "Duster": {
      "url": "https://www.moteur.ma/fr/neuf/voiture/dacia/duster/",
      "versions": [
        {
          "version": "1.5 dCi 115 Essential",
          "fuel": "Diesel",
          "gearbox": "Manuelle",
          "fiscal_power_cv": "6 CV",
          "horsepower_ch": "115 CH",
          "price_dhs": 226900,
          "is_promo": false,
          "url": "https://www.moteur.ma/…"
        }
      ]
    }
  }
}
```

### CSV — flat (one row per version)

```
brand,model,version,fuel,gearbox,fiscal_power_cv,horsepower_ch,price_dhs,is_promo,url
Dacia,Duster,1.5 dCi 115 Essential,Diesel,Manuelle,6 CV,115 CH,226900,False,https://…
Dacia,Duster,1.5 dCi 115 Expression,Diesel,Manuelle,6 CV,115 CH,243900,False,https://…
```

---

## URL structure scraped

```
moteur.ma
└── /fr/neuf/voiture/                         ← Brand index
    └── /fr/neuf/voiture/{brand}/             ← Brand page (models list)
        └── /fr/neuf/voiture/{brand}/{model}/ ← Model page (versions + prices)
```

---

## Notes & ethics

- The default delay of **1.2 s** between requests is intentional — don't lower it significantly.
- The site serves **~70 brands**, scraped at 1.2 s/request that's roughly 20–40 min for
  a full run (varies by brand size).
- Prices reflect the last update on moteur.ma and may not include metallic paint or
  registration fees. Always cross-check with the dealer.
- Do not re-distribute the scraped data commercially.
