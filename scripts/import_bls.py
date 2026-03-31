#!/usr/bin/env python3
"""
Import BLS occupations CSV → worldsense/data/occupations.json

Usage:
    python scripts/import_bls.py \
        --input ~/research/repos/jobs/occupations.csv \
        --output data/occupations.json

BLS CSV columns:
    title, category, slug, soc_code, median_pay_annual, median_pay_hourly,
    entry_education, work_experience, training,
    num_jobs_2024, projected_employment_2034, outlook_pct, outlook_desc,
    employment_change, url
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# PPP multipliers: US salary × multiplier → estimated local purchasing power
# Values are rough approximations for persona generation purposes
# ---------------------------------------------------------------------------
PPP_MULTIPLIERS: dict[str, float] = {
    "US": 1.00,
    "CN": 0.23,
    "IN": 0.12,
    "JP": 0.70,
    "DE": 0.85,
    "BR": 0.20,
    "KR": 0.65,
    "GB": 0.90,
    "FR": 0.82,
    "CA": 0.92,
    "AU": 0.88,
    "SG": 0.75,
    "KR": 0.65,
    "RU": 0.22,
    "MX": 0.18,
    "TR": 0.15,
    "SA": 0.45,
    "ID": 0.13,
    "TH": 0.20,
    "VN": 0.15,
    "PH": 0.16,
    "AR": 0.17,
    "ZA": 0.18,
    "NG": 0.10,
    "EG": 0.14,
    "PK": 0.11,
    "BD": 0.10,
    "MY": 0.25,
    "NL": 0.86,
    "SE": 0.84,
    "IT": 0.70,
    "ES": 0.65,
    "RU": 0.22,
    "ET": 0.07,
    "CD": 0.06,
}
DEFAULT_PPP = 0.50  # for countries not in the table

# Currency codes per country
CURRENCIES: dict[str, str] = {
    "US": "USD", "CN": "CNY", "IN": "INR", "JP": "JPY", "DE": "EUR",
    "BR": "BRL", "KR": "KRW", "GB": "GBP", "FR": "EUR", "CA": "CAD",
    "AU": "AUD", "SG": "SGD", "RU": "RUB", "MX": "MXN", "TR": "TRY",
    "SA": "SAR", "ID": "IDR", "TH": "THB", "VN": "VND", "PH": "PHP",
    "AR": "ARS", "ZA": "ZAR", "NG": "NGN", "EG": "EGP", "PK": "PKR",
    "BD": "BDT", "MY": "MYR", "NL": "EUR", "SE": "SEK", "IT": "EUR",
    "ES": "EUR", "ET": "ETB", "CD": "CDF",
}
DEFAULT_CURRENCY = "USD"

# Local salary multipliers for CNY vs USD raw PPP value
# Chinese salary should be expressed in CNY units, not USD×0.23
# So we convert: pay_local = median_pay_usd × (CNY_per_USD) e.g. ~7.2 but PPP-adjusted
# Simpler: pay_local = round(median_pay_usd × multiplier_to_local_currency)
LOCAL_PAY_FACTOR: dict[str, float] = {
    # factor = PPP × FX_approx / 1 to get rough local currency amount
    # We use: pay_local ≈ usd_salary × ppp_multiplier * local_units_per_ppp_dollar
    # For simplicity, we store everything in local currency with rough FX
    # e.g., CN: 1 USD PPP ≈ 7.2 CNY, so factor = 0.23 * 7.2 * (some scale)
    # Actually simplest: pay_local = round(median_pay_usd * local_fx_per_usd * ppp_ratio)
    # We'll approximate by: pay_local (in local currency) = usd_pay * exchange_rate * ppp_multiplier
    # But for cleanliness, we store in a way that makes sense to local readers:
    # CN: 100k USD → CN weight 0.23 → ~$23k PPP → ~165k CNY at 7.2 FX
    # We'll use a simple combined factor:
    "US": 1.0,       # USD stays same
    "CN": 7.2 * 0.23,   # ≈ 1.656 → $100k USD → ~165k CNY (rough)
    "IN": 83 * 0.12,    # ≈ 9.96 → $100k USD → ~996k INR
    "JP": 150 * 0.70,   # ≈ 105 → $100k USD → ¥10.5M
    "DE": 0.85,         # EUR stays close to USD
    "BR": 5.0 * 0.20,   # ≈ 1.0 → just about same in BRL
    "KR": 1300 * 0.65,  # ≈ 845 → $100k → ₩84.5M
    "GB": 0.79 * 0.90,  # ≈ 0.71 GBP
    "FR": 0.82,         # EUR
    "CA": 1.36 * 0.92,  # CAD
    "AU": 1.52 * 0.88,  # AUD
    "SG": 1.34 * 0.75,  # SGD
    "RU": 90 * 0.22,    # ≈ 19.8 RUB
    "MX": 17 * 0.18,    # ≈ 3.06 MXN
    "TR": 30 * 0.15,    # TRY
    "SA": 3.75 * 0.45,  # SAR
    "ID": 15600 * 0.13, # IDR
    "TH": 35 * 0.20,    # THB
    "VN": 24000 * 0.15, # VND
    "PH": 56 * 0.16,    # PHP
    "AR": 350 * 0.17,   # ARS
    "ZA": 18 * 0.18,    # ZAR
    "NG": 1600 * 0.10,  # NGN
    "EG": 48 * 0.14,    # EGP
    "PK": 280 * 0.11,   # PKR
    "BD": 110 * 0.10,   # BDT
    "MY": 4.7 * 0.25,   # MYR
    "NL": 0.86,         # EUR
    "SE": 10 * 0.84,    # SEK
    "IT": 0.70,         # EUR
    "ES": 0.65,         # EUR
}
DEFAULT_LOCAL_FACTOR = 0.50  # fallback


def _make_id(title: str) -> str:
    """Convert title to slug id."""
    s = title.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"-+", "-", s)
    return s[:60]


def _build_countries(median_pay_usd: int, num_jobs_us: int) -> dict:
    """Build countries dict with PPP-adjusted salary and weights."""
    countries = {}
    for code in ["US", "CN", "IN", "JP", "DE", "BR", "KR", "GB", "FR", "CA",
                 "AU", "SG", "RU", "MX", "TR", "SA", "ID", "AR", "ZA", "NG",
                 "IN", "TH", "VN", "PH", "PK", "MY", "NL", "SE", "IT", "ES"]:
        ppp = PPP_MULTIPLIERS.get(code, DEFAULT_PPP)
        local_factor = LOCAL_PAY_FACTOR.get(code, DEFAULT_LOCAL_FACTOR)
        currency = CURRENCIES.get(code, DEFAULT_CURRENCY)

        pay_local = round(median_pay_usd * local_factor)

        # Weight: how common is this occupation in this country?
        # US weight derived from num_jobs_us (normalized within group, set to 1.0 here)
        # Other countries get a default 0.5 weight (typical global occupation)
        if code == "US":
            weight = 1.0
        else:
            weight = 0.5

        countries[code] = {
            "weight": weight,
            "pay_local": pay_local,
            "currency": currency,
        }
    return countries


def load_bls_csv(csv_path: Path) -> list[dict]:
    """Parse BLS CSV and return list of occupation dicts in new format."""
    occupations = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row["title"].strip()
            category = row["category"].strip()
            slug = row["slug"].strip() or _make_id(title)
            soc_code = row.get("soc_code", "").strip()

            # Parse numeric fields
            try:
                median_pay = int(float(row.get("median_pay_annual", "0") or "0"))
            except ValueError:
                median_pay = 0

            try:
                num_jobs = int(float(row.get("num_jobs_2024", "0") or "0"))
            except ValueError:
                num_jobs = 0

            entry_edu = row.get("entry_education", "").strip()
            if entry_edu == "None":
                entry_edu = ""

            occ = {
                "id": slug,
                "title": title,
                "title_local": {},
                "category": category,
                "soc_code": soc_code,
                "median_pay_annual_usd": median_pay,
                "entry_education": entry_edu,
                "num_jobs_us": num_jobs,
                "work_context": "",  # filled for CN-specific occupations
                "countries": _build_countries(median_pay, num_jobs),
            }
            occupations.append(occ)

    return occupations


# ---------------------------------------------------------------------------
# China-specific occupations (not in BLS or with very low weight)
# ---------------------------------------------------------------------------

CN_OCCUPATIONS = [
    {
        "id": "civil-servant-cn",
        "title": "Civil Servant",
        "title_local": {"CN": "公务员"},
        "category": "government",
        "soc_code": "",
        "median_pay_annual_usd": 12000,
        "entry_education": "Bachelor's degree",
        "num_jobs_us": 0,
        "work_context": "Works in government agencies at national, provincial, or local level. Job security and benefits are highly valued. Career path is predictable. Social status is high relative to salary.",
        "countries": {
            "CN": {"weight": 3.0, "pay_local": 80000, "currency": "CNY"}
        },
    },
    {
        "id": "food-delivery-driver",
        "title": "Food Delivery Driver",
        "title_local": {"CN": "外卖骑手"},
        "category": "transportation-and-material-moving",
        "soc_code": "",
        "median_pay_annual_usd": 10000,
        "entry_education": "High school diploma or equivalent",
        "num_jobs_us": 0,
        "work_context": "Gig economy platform worker. Daily income depends on order volume. High phone/app usage. Time pressure. Limited savings. Works through Meituan or Ele.me.",
        "countries": {
            "CN": {"weight": 2.5, "pay_local": 72000, "currency": "CNY"}
        },
    },
    {
        "id": "courier-express",
        "title": "Express Courier",
        "title_local": {"CN": "快递员"},
        "category": "transportation-and-material-moving",
        "soc_code": "",
        "median_pay_annual_usd": 9000,
        "entry_education": "High school diploma or equivalent",
        "num_jobs_us": 0,
        "work_context": "Works for major logistics companies (SF Express, JD Logistics, Cainiao). Fixed package delivery routes. Physical labor, early hours. Income tied to parcel volume and seasonal peaks.",
        "countries": {
            "CN": {"weight": 2.0, "pay_local": 60000, "currency": "CNY"}
        },
    },
    {
        "id": "ride-hailing-driver",
        "title": "Ride-Hailing Driver",
        "title_local": {"CN": "网约车司机"},
        "category": "transportation-and-material-moving",
        "soc_code": "",
        "median_pay_annual_usd": 11000,
        "entry_education": "High school diploma or equivalent",
        "num_jobs_us": 0,
        "work_context": "Platform worker on DiDi or similar apps. Owns or rents a car. Income is flexible but uncertain. High urban mobility. Knowledgeable about apps and navigation tech.",
        "countries": {
            "CN": {"weight": 2.0, "pay_local": 72000, "currency": "CNY"}
        },
    },
    {
        "id": "ecommerce-operator",
        "title": "E-commerce Operator",
        "title_local": {"CN": "电商运营"},
        "category": "sales",
        "soc_code": "",
        "median_pay_annual_usd": 15000,
        "entry_education": "Bachelor's degree",
        "num_jobs_us": 0,
        "work_context": "Manages product listings, promotions, and customer service on Taobao/Tmall/JD. Highly data-driven. Works irregular hours during shopping festivals. Understands consumer psychology deeply.",
        "countries": {
            "CN": {"weight": 2.0, "pay_local": 100000, "currency": "CNY"}
        },
    },
    {
        "id": "livestream-seller",
        "title": "Livestream Seller",
        "title_local": {"CN": "直播带货"},
        "category": "sales",
        "soc_code": "",
        "median_pay_annual_usd": 12000,
        "entry_education": "High school diploma or equivalent",
        "num_jobs_us": 0,
        "work_context": "Sells products via live streaming on Douyin or Taobao Live. Income varies wildly — top performers earn millions, most earn modest income. Heavy phone usage, brand deal negotiation, fan engagement.",
        "countries": {
            "CN": {"weight": 1.5, "pay_local": 80000, "currency": "CNY"}
        },
    },
    {
        "id": "small-business-owner",
        "title": "Small Business Owner",
        "title_local": {"CN": "个体工商户"},
        "category": "management",
        "soc_code": "",
        "median_pay_annual_usd": 14000,
        "entry_education": "High school diploma or equivalent",
        "num_jobs_us": 0,
        "work_context": "Runs a small shop, restaurant, or service business. Self-employed, family-operated. High work hours, direct customer relationships. Income volatile and seasonal. Strong local community ties.",
        "countries": {
            "CN": {"weight": 3.0, "pay_local": 96000, "currency": "CNY"}
        },
    },
    {
        "id": "soe-manager",
        "title": "State-Owned Enterprise Manager",
        "title_local": {"CN": "国企中层管理"},
        "category": "management",
        "soc_code": "",
        "median_pay_annual_usd": 20000,
        "entry_education": "Bachelor's degree",
        "num_jobs_us": 0,
        "work_context": "Mid-level manager at a state-owned enterprise. Strong job security and housing benefits. Bureaucratic work culture. Long tenure is typical. Social status tied to company prestige.",
        "countries": {
            "CN": {"weight": 1.5, "pay_local": 150000, "currency": "CNY"}
        },
    },
    {
        "id": "construction-worker-cn",
        "title": "Construction Worker",
        "title_local": {"CN": "建筑工人"},
        "category": "construction-and-extraction",
        "soc_code": "",
        "median_pay_annual_usd": 8000,
        "entry_education": "No formal educational credential",
        "num_jobs_us": 0,
        "work_context": "Migrant worker on construction sites. Away from home for months at a time. Paid by day or project. Limited social protections. Sends remittances back to rural family.",
        "countries": {
            "CN": {"weight": 2.5, "pay_local": 60000, "currency": "CNY"}
        },
    },
    {
        "id": "rural-teacher",
        "title": "Rural Teacher",
        "title_local": {"CN": "乡镇教师"},
        "category": "education-training-and-library",
        "soc_code": "",
        "median_pay_annual_usd": 7000,
        "entry_education": "Bachelor's degree",
        "num_jobs_us": 0,
        "work_context": "Teaches at a township or village school in China. Stable government salary but modest pay. Housing often provided. Strong community respect. Limited access to urban amenities.",
        "countries": {
            "CN": {"weight": 1.5, "pay_local": 48000, "currency": "CNY"}
        },
    },
    {
        "id": "public-institution-staff",
        "title": "Public Institution Staff",
        "title_local": {"CN": "事业单位职员"},
        "category": "government",
        "soc_code": "",
        "median_pay_annual_usd": 10000,
        "entry_education": "Bachelor's degree",
        "num_jobs_us": 0,
        "work_context": "Works at state-funded institutions like hospitals, universities, or research institutes. Hybrid status — not full civil servant but similar stability. Pension and healthcare benefits strong.",
        "countries": {
            "CN": {"weight": 2.0, "pay_local": 70000, "currency": "CNY"}
        },
    },
    {
        "id": "factory-line-worker",
        "title": "Factory Line Worker",
        "title_local": {"CN": "流水线工人"},
        "category": "production",
        "soc_code": "",
        "median_pay_annual_usd": 7000,
        "entry_education": "No formal educational credential",
        "num_jobs_us": 0,
        "work_context": "Assembly line worker at a manufacturing plant. Repetitive work, 8-12 hour shifts. Dormitory living common. High exposure to consumer electronics and basic goods. Price-sensitive consumer.",
        "countries": {
            "CN": {"weight": 3.0, "pay_local": 50000, "currency": "CNY"}
        },
    },
]


def main():
    parser = argparse.ArgumentParser(description="Import BLS occupations CSV to WorldSense format")
    parser.add_argument("--input", default=str(Path.home() / "research/repos/jobs/occupations.csv"))
    parser.add_argument("--output", default=str(Path(__file__).parent.parent / "data/occupations.json"))
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    output_path = Path(args.output).expanduser()

    print(f"Reading BLS CSV: {input_path}")
    occupations = load_bls_csv(input_path)
    print(f"  Loaded {len(occupations)} BLS occupations")

    # Add CN-specific occupations
    existing_ids = {o["id"] for o in occupations}
    added = 0
    for cn_occ in CN_OCCUPATIONS:
        if cn_occ["id"] not in existing_ids:
            occupations.append(cn_occ)
            added += 1
    print(f"  Added {added} China-specific occupations")
    print(f"  Total: {len(occupations)} occupations")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(occupations, f, ensure_ascii=False, indent=2)

    print(f"Written to: {output_path}")


if __name__ == "__main__":
    main()
