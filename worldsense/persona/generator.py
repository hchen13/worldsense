"""
Layer 1: Persona generator.

Samples demographic combinations weighted by real-world population distributions,
then enriches with Layer 2 cognitive model.

v2: BLS 342+ occupations, income derived from occupation data.
"""

from __future__ import annotations

import json
import math
import random
import uuid
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Optional

from worldsense.persona.schema import HofstedeProfile, Persona
from worldsense.persona.cognitive import (
    assign_personality_type,
    derive_cognitive_profile,
    derive_mbti,
    generate_big_five,
)

DATA_DIR = Path(__file__).parent.parent.parent / "data"

# Market → list of country codes
MARKET_COUNTRIES: dict[str, list[str]] = {
    "global": None,  # None = all
    "us": ["US"],
    "cn": ["CN"],
    "asia": ["CN", "JP", "KR", "IN", "ID", "TH", "VN", "PH", "SG", "MY"],
    "europe": ["DE", "FR", "GB", "IT", "ES", "NL", "SE", "RU"],
    "latam": ["BR", "MX", "AR"],
    "africa": ["NG", "ZA", "EG"],
    "mena": ["SA", "EG", "TR"],
    "developed": ["US", "CA", "GB", "DE", "FR", "JP", "AU", "KR", "SG", "NL", "SE"],
    "emerging": ["CN", "IN", "BR", "MX", "ID", "TR", "RU", "ZA", "NG", "VN", "PH"],
}

# Age group → typical age range for sampling
AGE_GROUP_RANGES: dict[str, tuple[int, int]] = {
    "18-24": (18, 24),
    "25-34": (25, 34),
    "35-44": (35, 44),
    "45-54": (45, 54),
    "55-64": (55, 64),
    "65+": (65, 80),
}

# Category → urban_bias: probability that occupation is found in urban areas.
# Used to weight occupation sampling by location.
# Higher = more urban, lower = more rural-appropriate.
CATEGORY_URBAN_BIAS: dict[str, float] = {
    "computer-and-information-technology": 0.90,
    "legal": 0.90,
    "business-and-financial": 0.85,
    "architecture-and-engineering": 0.85,
    "media-and-communication": 0.85,
    "math": 0.85,
    "management": 0.80,
    "life-physical-and-social-science": 0.80,
    "arts-and-design": 0.80,
    "entertainment-and-sports": 0.75,
    "personal-care-and-service": 0.75,
    "office-and-administrative-support": 0.70,
    "healthcare": 0.65,
    "sales": 0.65,
    "food-preparation-and-serving": 0.65,
    "government": 0.60,
    "protective-service": 0.60,
    "community-and-social-service": 0.55,
    "education-training-and-library": 0.55,
    "military": 0.50,
    "building-and-grounds-cleaning": 0.50,
    "construction-and-extraction": 0.40,
    "installation-maintenance-and-repair": 0.40,
    "production": 0.40,
    "transportation-and-material-moving": 0.40,
    "farming-fishing-and-forestry": 0.10,
}

# --- Per-nationality first name pools (male, female, non-binary) ---
_NAMES: dict[str, tuple[list[str], list[str], list[str]]] = {
    "US": (["James","Michael","Robert","John","David","William","Richard","Thomas"],
           ["Mary","Patricia","Jennifer","Linda","Barbara","Susan","Jessica","Sarah"],
           ["Alex","Jordan","Taylor","Riley","Morgan"]),
    "CN": (["Wei","Ming","Jian","Lei","Hao","Peng","Tao","Jun","Yang"],
           ["Fang","Ying","Xiu","Hui","Mei","Lan","Yun","Xia","Qian"],
           ["Xin","Yu","Cheng"]),
    "JP": (["Kenji","Hiroshi","Takashi","Satoshi","Ryu","Kota","Daiki"],
           ["Yuki","Akiko","Haruko","Naoko","Miki","Emi","Hana"],
           ["Hiromi","Makoto"]),
    "KR": (["Minjun","Jiwoo","Hyunwoo","Sungmin","Jaehyun","Seojun"],
           ["Minji","Jiyeon","Soyeon","Hyejin","Yuna","Seoyeon"],
           ["Hyun","Jae"]),
    "IN": (["Rajesh","Arjun","Vikram","Rahul","Sanjay","Aditya","Ravi","Amit"],
           ["Priya","Ananya","Sunita","Meera","Kavita","Nisha","Deepa","Pooja"],
           ["Aryan","Dhruv"]),
    "DE": (["Klaus","Hans","Stefan","Thomas","Andreas","Markus","Lukas"],
           ["Anna","Maria","Sophie","Emma","Lena","Hannah","Laura"],
           ["Alex","Robin"]),
    "FR": (["Pierre","Jean","Michel","Philippe","Louis","François","Nicolas"],
           ["Marie","Sophie","Claire","Isabelle","Nathalie","Élise","Camille"],
           ["Claude","René"]),
    "GB": (["William","James","Oliver","Harry","George","Thomas","Jack"],
           ["Emma","Olivia","Amelia","Isabella","Charlotte","Mia","Sophia"],
           ["Charlie","Sam"]),
    "BR": (["João","Carlos","Paulo","Lucas","Gabriel","Rafael","Bruno"],
           ["Maria","Ana","Juliana","Fernanda","Camila","Beatriz","Amanda"],
           ["Alex","Mel"]),
    "MX": (["Carlos","José","Luis","Miguel","Juan","Antonio","Pedro"],
           ["María","Sofía","Isabella","Valentina","Camila","Fernanda"],
           ["Alex","Morgan"]),
    "RU": (["Aleksandr","Dmitri","Ivan","Sergei","Nikolai","Mikhail","Andrei"],
           ["Natasha","Olga","Tatyana","Irina","Elena","Svetlana","Nadia"],
           ["Sasha","Zhenya"]),
    "TR": (["Ahmet","Mehmet","Mustafa","Ali","Ibrahim","Hasan","Can"],
           ["Fatma","Ayşe","Hatice","Zeynep","Elif","Büşra","Selin"],
           ["Ömer","Emre"]),
    "SA": (["Mohammed","Abdullah","Ahmed","Ali","Omar","Ibrahim","Faisal"],
           ["Fatima","Nora","Layla","Maha","Sara","Hana","Reem"],
           ["Sami","Dana"]),
    "ZA": (["Sipho","Thabo","Bongani","Mandla","Nkosi","Lethiwe"],
           ["Thandiwe","Nandi","Zanele","Nokwanda","Siphiwe"],
           ["Lesedi","Phiri"]),
    "NG": (["Emeka","Chukwu","Yusuf","Ibrahim","Bola","Kunle","Seun"],
           ["Ngozi","Amaka","Fatima","Kemi","Adaeze","Bukola"],
           ["Tunde","Ife"]),
    "EG": (["Mohamed","Ahmed","Khaled","Omar","Youssef","Hassan"],
           ["Fatima","Nada","Sara","Hana","Mona","Rana"],
           ["Karim","Dina"]),
    "ID": (["Budi","Andi","Rizki","Dedi","Wahyu","Agus","Hendra"],
           ["Sari","Dewi","Rina","Fitri","Dian","Indah","Sri"],
           ["Reza","Putri"]),
    "TH": (["Somchai","Korn","Nui","Chai","Pong","Lek","Arthit"],
           ["Nong","Pim","Wan","Dao","Mint","Fon","Kanya"],
           ["Kai","Nat"]),
    "VN": (["Minh","Thanh","Tuấn","Hùng","Long","Phong"],
           ["Lan","Thảo","Mai","Nga","Hương","Linh"],
           ["Khải","Phương"]),
    "PH": (["Juan","Jose","Miguel","Carlos","Angelo","Rico"],
           ["Maria","Ana","Luz","Grace","Joy","Faith"],
           ["Alex","Sam"]),
    "AU": (["Jack","Liam","Noah","Oliver","William","Tom"],
           ["Olivia","Charlotte","Mia","Ava","Sophie","Grace"],
           ["Sam","Charlie"]),
    "SG": (["Wei","Rajan","Kumar","Ahmad","Jun","Kelvin"],
           ["Mei","Priya","Siti","Fatimah","Lin","Jasmine"],
           ["Sam","Alex"]),
    "MY": (["Ahmad","Razak","Wei Ming","Raj","Kumar","Aziz"],
           ["Siti","Nurul","Wei Ling","Priya","Ratha","Farah"],
           ["Sam","Alex"]),
    "PK": (["Mohammad","Ahmed","Ali","Hassan","Usman","Imran"],
           ["Fatima","Aisha","Zainab","Maryam","Hina","Sana"],
           ["Sana","Zara"]),
    "NL": (["Jan","Pieter","Henk","Dirk","Maarten","Sjoerd"],
           ["Anna","Maria","Emma","Lotte","Sophie","Fleur"],
           ["Sam","Robin"]),
    "SE": (["Lars","Erik","Johan","Magnus","Björn","Gustav"],
           ["Anna","Maria","Emma","Linnea","Astrid","Maja"],
           ["Alex","Robin"]),
    "IT": (["Marco","Luca","Giuseppe","Antonio","Giovanni","Matteo"],
           ["Sofia","Giulia","Valentina","Federica","Chiara","Francesca"],
           ["Andrea","Nico"]),
    "ES": (["Carlos","José","Juan","Miguel","Alejandro","Pablo"],
           ["María","Carmen","Ana","Isabel","Sofia","Elena"],
           ["Alex","Sasha"]),
    "AR": (["Juan","Carlos","Alejandro","Lucas","Matías","Diego"],
           ["María","Ana","Laura","Valentina","Sofía","Camila"],
           ["Alex","Morgan"]),
    "CA": (["Liam","Noah","William","James","Oliver","Ethan"],
           ["Emma","Olivia","Charlotte","Sophia","Ava","Isabella"],
           ["Alex","Jordan"]),
    "BD": (["Mohammad","Rahim","Karim","Hasan","Salim","Tariq"],
           ["Fatima","Ayesha","Nasrin","Rehana","Sumaiya"],
           ["Rana","Joya"]),
    "ET": (["Abebe","Girma","Tadesse","Bekele","Solomon"],
           ["Tigist","Selamawit","Almaz","Hiwot","Mimi"],
           ["Dawit","Yonas"]),
    "CD": (["Emile","Jean","Pierre","Joseph","François"],
           ["Marie","Josephine","Claire","Bernadette"],
           ["Alex","Claude"]),
}

_DEFAULT_NAMES = (
    ["Alex","Chris","Jamie","Taylor","Morgan","Sam"],
    ["Alex","Chris","Jamie","Taylor","Morgan","Sam"],
    ["Alex","Chris","Jamie"],
)


def _generate_name(nationality: str, gender: str, rng: random.Random) -> str:
    """Pick a culturally resonant first name for a persona."""
    male_names, female_names, nb_names = _NAMES.get(nationality, _DEFAULT_NAMES)
    if gender == "male":
        return rng.choice(male_names)
    elif gender == "female":
        return rng.choice(female_names)
    else:
        return rng.choice(nb_names)


def _country_flag(code: str) -> str:
    """Convert ISO country code to flag emoji."""
    if len(code) != 2:
        return "🌐"
    return chr(0x1F1E6 + ord(code[0]) - ord('A')) + chr(0x1F1E6 + ord(code[1]) - ord('A'))


@dataclass
class DimensionConfig:
    """Custom sampling weights for persona generation."""
    # country_code -> relative weight (e.g. {"US": 0.5, "CN": 0.3, "JP": 0.2})
    nationality_weights: Optional[dict[str, float]] = None
    # age_group -> relative weight (e.g. {"18-24": 0.3, "25-34": 0.7})
    age_weights: Optional[dict[str, float]] = None
    # gender -> relative weight (e.g. {"male": 0.5, "female": 0.5, "non-binary": 0.0})
    gender_weights: Optional[dict[str, float]] = None
    # income_weights: kept for backward compat but no longer used for sampling
    # (income is derived from occupation)
    income_weights: Optional[dict[str, float]] = None
    # restrict occupation sampling to these ids (empty = all)
    occupation_ids: Optional[list[str]] = None
    # restrict personality types (empty = all)
    personality_traits: Optional[list[str]] = None
    # location -> relative weight (e.g. {"urban": 0.6, "suburban": 0.3, "rural": 0.1})
    location_weights: Optional[dict[str, float]] = None

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> Optional["DimensionConfig"]:
        if not d:
            return None
        return cls(
            nationality_weights=d.get("nationality_weights"),
            age_weights=d.get("age_weights"),
            gender_weights=d.get("gender_weights"),
            income_weights=d.get("income_weights"),
            occupation_ids=d.get("occupation_ids"),
            personality_traits=d.get("personality_traits"),
            location_weights=d.get("location_weights"),
        )


def _tier_to_urban_rural(tier_id: str) -> str:
    """Map a city_tier id to a best-fit urban/suburban/rural label."""
    if tier_id in ("rural",):
        return "rural"
    if tier_id in ("suburban", "small-town", "small-city", "t4-5", "t3"):
        return "suburban"
    return "urban"


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    """Normalize weights to sum to 1."""
    total = sum(weights.values())
    if total <= 0:
        return {k: 1.0 / len(weights) for k in weights}
    return {k: v / total for k, v in weights.items()}


# ---------------------------------------------------------------------------
# Income quantile → price_sensitivity mapping
# ---------------------------------------------------------------------------

# All occupation USD salaries for quantile computation (loaded lazily)
_INCOME_QUANTILES: Optional[list[float]] = None

def _compute_income_quantiles(occupations: list[dict]) -> list[float]:
    """Get sorted list of median_pay_annual_usd values for quantile computation."""
    pays = [o["median_pay_annual_usd"] for o in occupations if o["median_pay_annual_usd"] > 0]
    pays.sort()
    return pays

def _income_to_price_sensitivity(income_usd: int, quantiles: list[float]) -> float:
    """
    Convert annual USD income to price_sensitivity 0-1.
    Low income → high price sensitivity (close to 1).
    High income → low price sensitivity (close to 0).
    """
    if not quantiles or income_usd <= 0:
        return 0.6  # default moderate-high

    # Find percentile of this income in the distribution
    n = len(quantiles)
    rank = sum(1 for q in quantiles if q <= income_usd)
    percentile = rank / n  # 0=lowest, 1=highest

    # Invert: high percentile (high earner) → low price sensitivity
    # Apply mild nonlinearity so the middle is more spread out
    sensitivity = 1.0 - percentile
    # Scale to [0.05, 0.95] range
    sensitivity = 0.05 + sensitivity * 0.90
    return round(sensitivity, 3)

def _income_to_wtp_multiplier(income_usd: int, quantiles: list[float]) -> float:
    """Convert income to WTP multiplier (1.0 = average)."""
    if not quantiles or income_usd <= 0:
        return 0.8

    n = len(quantiles)
    rank = sum(1 for q in quantiles if q <= income_usd)
    percentile = rank / n

    # Map percentile to WTP: bottom 20% → 0.4x, top 10% → 2.5x
    if percentile < 0.20:
        wtp = 0.35 + percentile * 1.75  # 0.35 to 0.70
    elif percentile < 0.50:
        wtp = 0.70 + (percentile - 0.20) * 1.0  # 0.70 to 1.0
    elif percentile < 0.80:
        wtp = 1.0 + (percentile - 0.50) * 2.5  # 1.0 to 1.75
    else:
        wtp = 1.75 + (percentile - 0.80) * 3.75  # 1.75 to 2.5

    return round(wtp, 3)


class PersonaGenerator:
    """Generates weighted persona samples for a given market."""

    def __init__(
        self,
        market: str = "global",
        seed: Optional[int] = None,
        dimensions: Optional[DimensionConfig] = None,
    ):
        self.market = market
        self.rng = random.Random(seed)
        self.dimensions = dimensions

        # Load data
        self._hofstede = self._load_hofstede()
        self._populations = self._load_populations()
        self._occupations = self._load_occupations()
        self._country_profiles = self._load_country_profiles()

        # Precompute income quantiles for price sensitivity derivation
        all_occs = list(self._occupations["map"].values())
        self._income_quantiles = _compute_income_quantiles(all_occs)

        # Resolve country list for market
        market_key = market.lower()
        if market_key not in MARKET_COUNTRIES:
            raise ValueError(
                f"Unknown market '{market}'. Available: {', '.join(sorted(MARKET_COUNTRIES.keys()))}"
            )
        allowed = MARKET_COUNTRIES[market_key]
        if allowed is None:
            self._country_codes = list(self._hofstede.keys())
        else:
            self._country_codes = [c for c in allowed if c in self._hofstede]

        if not self._country_codes:
            raise ValueError(f"No Hofstede data for market '{market}'. Available: {list(self._hofstede.keys())}")

        # Store market key for occupation weighting
        self._market_key = market_key

    # --- Data loaders ---

    def _load_hofstede(self) -> dict:
        path = DATA_DIR / "hofstede.json"
        data = json.loads(path.read_text())
        return {k: v for k, v in data.items() if not k.startswith("_")}

    def _load_populations(self) -> dict:
        path = DATA_DIR / "populations.json"
        return json.loads(path.read_text())

    def _load_occupations(self) -> dict:
        """Load multi-file occupation data and join into a unified map.

        Files:
          - occupations.json        : slim records (id, title, category, pay, education, jobs, country_only)
          - work_contexts.json      : { occ_id: "context text" }
          - title_translations.json : { occ_id: {"CN": "...", "JP": "..."} }
          - country_profiles.json   : stored separately, loaded by _load_country_profiles()
        """
        data_dir = DATA_DIR

        # --- occupations.json ---
        raw = json.loads((data_dir / "occupations.json").read_text())
        if isinstance(raw, list):
            occ_list = raw
        elif isinstance(raw, dict) and "occupations" in raw:
            occ_list = raw["occupations"]
        else:
            occ_list = []

        # --- work_contexts.json (optional) ---
        wc_path = data_dir / "work_contexts.json"
        work_contexts: dict = json.loads(wc_path.read_text()) if wc_path.exists() else {}

        # --- title_translations.json (optional) ---
        tt_path = data_dir / "title_translations.json"
        title_translations: dict = json.loads(tt_path.read_text()) if tt_path.exists() else {}

        # Join all data by id
        occ_map = {}
        for occ in occ_list:
            occ_id = occ["id"]
            enriched = dict(occ)
            enriched["work_context"] = work_contexts.get(occ_id, "")
            enriched["title_local"] = title_translations.get(occ_id, {})
            occ_map[occ_id] = enriched

        return {"map": occ_map}

    def _load_country_profiles(self) -> dict:
        """Load country_profiles.json for pay/weight calculations."""
        cp_path = DATA_DIR / "country_profiles.json"
        if cp_path.exists():
            return json.loads(cp_path.read_text())
        return {}

    # --- Sampling helpers ---

    def _sample_country(self) -> str:
        # Custom nationality weights override defaults
        if self.dimensions and self.dimensions.nationality_weights:
            custom = {
                c: w for c, w in self.dimensions.nationality_weights.items()
                if c in self._country_codes and w > 0
            }
            if custom:
                normalized = _normalize(custom)
                codes = list(normalized.keys())
                weights = [normalized[c] for c in codes]
                return self.rng.choices(codes, weights=weights, k=1)[0]

        pop_weights = self._populations["country_weights"]
        relevant = {c: pop_weights.get(c, 0.001) for c in self._country_codes}
        total = sum(relevant.values())
        normalized = {c: w / total for c, w in relevant.items()}
        codes = list(normalized.keys())
        weights = [normalized[c] for c in codes]
        return self.rng.choices(codes, weights=weights, k=1)[0]

    def _sample_age_group(self) -> str:
        if self.dimensions and self.dimensions.age_weights:
            custom = {k: v for k, v in self.dimensions.age_weights.items() if v > 0}
            if custom:
                normalized = _normalize(custom)
                groups = list(normalized.keys())
                weights = [normalized[g] for g in groups]
                return self.rng.choices(groups, weights=weights, k=1)[0]

        dist = self._populations["age_distribution"]
        groups = list(dist.keys())
        weights = [dist[g] for g in groups]
        return self.rng.choices(groups, weights=weights, k=1)[0]

    def _sample_gender(self) -> str:
        if self.dimensions and self.dimensions.gender_weights:
            custom = {k: v for k, v in self.dimensions.gender_weights.items() if v > 0}
            if custom:
                normalized = _normalize(custom)
                genders = list(normalized.keys())
                weights = [normalized[g] for g in genders]
                return self.rng.choices(genders, weights=weights, k=1)[0]

        dist = self._populations["gender_distribution"]
        genders = list(dist.keys())
        weights = [dist[g] for g in genders]
        return self.rng.choices(genders, weights=weights, k=1)[0]

    def _get_occupation_weight(self, occ: dict, nationality: str) -> float:
        """
        Determine sampling weight for an occupation given the market/country.

        Uses country_profiles weight_overrides and default_weight.
        CN-specific occupations (country_only=["CN"]) get boosted weight in CN,
        zero weight in other countries.
        """
        num_jobs_us = occ.get("num_jobs_us", 0) or 0
        country_only = occ.get("country_only")

        # country_only filter: occupation must not appear in other markets
        if country_only and nationality not in country_only:
            return 0.0

        cp = self._country_profiles.get(nationality, {})

        if nationality == "US":
            # Use actual BLS employment numbers; fallback to 1
            return max(1.0, float(num_jobs_us))

        # Get weight from country_profiles
        weight_overrides = cp.get("weight_overrides", {})
        default_weight = cp.get("default_weight", 0.5)
        occ_weight = weight_overrides.get(occ["id"], default_weight)

        if nationality == "CN":
            # CN-specific occupations (num_jobs_us == 0) → use explicit weight × 5
            # to ensure they appear prominently in CN market (≈40-50% of samples)
            if num_jobs_us == 0:
                return occ_weight * 5.0
            # BLS occupations: log-normalized US employment scaled down
            log_weight = max(0.05, math.log10(num_jobs_us + 1) / 14.0)
            return log_weight

        else:
            # Other countries: blend profile weight with log-normalized US employment
            if num_jobs_us > 0:
                log_weight = max(0.15, math.log10(num_jobs_us + 1) / 10.0)
                return (occ_weight + log_weight) / 2.0
            return occ_weight

    def _get_income_for_nationality(self, occ: dict, nationality: str) -> tuple[int, str]:
        """
        Get annual income (local currency) and currency code for a persona.
        Returns (pay_local, currency).

        Calculation: local_pay = us_pay * ppp_multiplier * bracket_scale
        where bracket_scale is looked up from country_profiles pay_brackets.
        """
        us_pay = occ.get("median_pay_annual_usd", 30000) or 30000
        cp = self._country_profiles.get(nationality, {})
        currency = cp.get("currency", "USD")
        ppp = cp.get("ppp_multiplier", 1.0)

        # Determine bracket scale based on us_pay
        bracket_scale = 1.0
        pay_brackets = cp.get("pay_brackets", [])
        # Brackets are ordered highest first (above_usd descending)
        for bracket in pay_brackets:
            if us_pay >= bracket["above_usd"]:
                bracket_scale = bracket["scale"]
                break

        pay_local = int(us_pay * ppp * bracket_scale)
        return pay_local, currency

    def _sample_occupation(self, nationality: str, urban_rural: str = "") -> dict:
        """Sample an occupation weighted by market-appropriate weights.

        When *urban_rural* is provided, occupation weights are adjusted so that
        urban-oriented jobs are less likely in rural areas and vice-versa.
        """
        occ_map = self._occupations["map"]

        if not occ_map:
            # Fallback stub if data not loaded
            return {"id": "unknown", "title": "Unknown", "median_pay_annual_usd": 30000,
                    "entry_education": "", "num_jobs_us": 0, "countries": {}, "work_context": "",
                    "title_local": {}, "category": "other", "soc_code": ""}

        # Filter to allowed occupations if specified
        candidates = dict(occ_map)
        if self.dimensions and self.dimensions.occupation_ids:
            allowed_ids = set(self.dimensions.occupation_ids)
            filtered = {k: v for k, v in candidates.items() if k in allowed_ids}
            if filtered:
                candidates = filtered

        ids = list(candidates.keys())
        weights = [self._get_occupation_weight(candidates[oid], nationality) for oid in ids]

        # Apply location-based modifier
        if urban_rural:
            for i, oid in enumerate(ids):
                cat = candidates[oid].get("category", "")
                ub = CATEGORY_URBAN_BIAS.get(cat, 0.6)
                if urban_rural == "rural":
                    # Strongly penalise urban-only occupations in rural areas
                    weights[i] *= (1.0 - ub) ** 1.5
                elif urban_rural == "urban":
                    # Mildly penalise rural-only occupations in urban areas
                    weights[i] *= ub ** 0.5

        chosen_id = self.rng.choices(ids, weights=weights, k=1)[0]
        return candidates[chosen_id]

    def _sample_location(self, nationality: str) -> tuple[str, str, str]:
        """
        Sample location for a persona (independent of occupation).

        Returns (urban_rural, city_tier, city_tier_label).
        - If country has city_tiers in country_profiles:
          - If DimensionConfig.location_weights keys match city_tier ids → user-weighted sampling
          - Otherwise → sample by city_tier weights
          - Sets urban_rural to "urban"/"suburban"/"rural" as best-fit fallback
        - Otherwise → fallback to urban/suburban/rural logic using nationality defaults
        """
        cp = self._country_profiles.get(nationality, {})
        city_tiers = cp.get("city_tiers", [])

        if city_tiers:
            tier_ids = [t["id"] for t in city_tiers]

            # Check if user-provided location_weights match tier ids
            if self.dimensions and self.dimensions.location_weights:
                lw = self.dimensions.location_weights
                matching_keys = [k for k in lw if k in tier_ids]
                if matching_keys:
                    # User configured tier-specific weights
                    options = matching_keys
                    weights = [lw[k] for k in options]
                    total = sum(weights)
                    if total > 0:
                        chosen_id = self.rng.choices(options, weights=weights, k=1)[0]
                        tier = next(t for t in city_tiers if t["id"] == chosen_id)
                        label = tier.get("label_en", tier.get("label", chosen_id))
                        urban_rural = _tier_to_urban_rural(chosen_id)
                        return urban_rural, chosen_id, label

            # Default: sample by city_tier weights
            weights = [t["weight"] for t in city_tiers]
            chosen = self.rng.choices(city_tiers, weights=weights, k=1)[0]
            chosen_id = chosen["id"]
            label = chosen.get("label_en", chosen.get("label", chosen_id))
            urban_rural = _tier_to_urban_rural(chosen_id)
            return urban_rural, chosen_id, label

        # Fallback: original urban/suburban/rural logic
        # If user provided location_weights with old-style keys, use them
        if self.dimensions and self.dimensions.location_weights:
            lw = self.dimensions.location_weights
            old_keys = [k for k in lw if k in ("urban", "suburban", "rural")]
            if old_keys:
                options = list(lw.keys())
                weights = [lw[k] for k in options]
                total = sum(weights)
                if total > 0:
                    chosen = self.rng.choices(options, weights=weights, k=1)[0]
                    return chosen, "", ""

        # Nationality-based default urban bias (no occupation info yet)
        urban_bias = 0.6
        if nationality in ("US", "GB", "DE", "FR", "JP", "AU", "SG", "KR", "CN"):
            urban_bias = 0.70
        elif nationality in ("IN", "NG", "PK", "VN", "PH", "ET", "BD"):
            urban_bias = 0.45

        roll = self.rng.random()
        if roll < urban_bias * 0.6:
            return "urban", "", ""
        elif roll < urban_bias:
            return "suburban", "", ""
        else:
            return "rural", "", ""

    # Keep old name for backward compat (callers outside this module)
    def _sample_urban_rural(self, nationality: str) -> str:
        urban_rural, _, _ = self._sample_location(nationality)
        return urban_rural

    # --- Main generator ---

    def generate(self, count: int) -> list[Persona]:
        """Generate `count` personas with full cognitive profiles."""
        personas = []
        for _ in range(count):
            p = self._generate_one()
            personas.append(p)
        return personas

    def _generate_one(self) -> Persona:
        # Layer 1: Sample demographics
        nationality = self._sample_country()
        hof_data = self._hofstede[nationality]
        country_name = hof_data["name"]

        age_group = self._sample_age_group()
        age_range = AGE_GROUP_RANGES[age_group]
        age = self.rng.randint(*age_range)

        gender = self._sample_gender()
        urban_rural, city_tier, city_tier_label = self._sample_location(nationality)
        occ = self._sample_occupation(nationality, urban_rural)

        # Derive income from occupation data
        base_income_local, income_currency = self._get_income_for_nationality(occ, nationality)
        # Add normal-distributed offset for realistic within-occupation variance
        # σ=0.10 gives ~68% of personas within ±10%, clipped to ±50%
        income_offset = max(-0.50, min(0.50, self.rng.gauss(0, 0.10)))
        income_local = max(1000, round(base_income_local * (1 + income_offset)))

        # Apply city tier income scaling
        if city_tier:
            cp = self._country_profiles.get(nationality, {})
            city_tiers = cp.get("city_tiers", [])
            tier_data = next((t for t in city_tiers if t["id"] == city_tier), None)
            if tier_data:
                income_scale = tier_data.get("income_scale", 1.0)
                income_local = max(1000, round(income_local * income_scale))

        # Also compute income in USD for quantile comparison
        # (use median_pay_annual_usd as the USD reference)
        base_income_usd = occ.get("median_pay_annual_usd", 30000) or 30000
        income_usd = max(1000, round(base_income_usd * (1 + income_offset)))

        # Derive income bracket from USD percentile (for backward compat in any displays)
        price_sens = _income_to_price_sensitivity(income_usd, self._income_quantiles)
        if price_sens >= 0.75:
            income_bracket = "low"
        elif price_sens >= 0.55:
            income_bracket = "lower-middle"
        elif price_sens >= 0.35:
            income_bracket = "middle"
        elif price_sens >= 0.20:
            income_bracket = "upper-middle"
        else:
            income_bracket = "high"

        # Generate display name
        name = _generate_name(nationality, gender, self.rng)
        flag = _country_flag(nationality)

        # Build Hofstede profile
        hofstede = HofstedeProfile(
            pdi=min(100, max(0, hof_data["pdi"] + self.rng.gauss(0, 5))),
            idv=min(100, max(0, hof_data["idv"] + self.rng.gauss(0, 5))),
            mas=min(100, max(0, hof_data["mas"] + self.rng.gauss(0, 5))),
            uai=min(100, max(0, hof_data["uai"] + self.rng.gauss(0, 5))),
            lto=min(100, max(0, hof_data["lto"] + self.rng.gauss(0, 5))),
            ivr=min(100, max(0, hof_data["ivr"] + self.rng.gauss(0, 5))),
        )

        # Layer 2: Big Five + cognitive model
        big_five = generate_big_five(self.rng, nationality, age_group)
        personality_type = assign_personality_type(big_five)
        mbti = derive_mbti(big_five)

        # Compute income-derived price sensitivity and WTP multiplier
        derived_price_sensitivity = _income_to_price_sensitivity(income_usd, self._income_quantiles)
        derived_wtp = _income_to_wtp_multiplier(income_usd, self._income_quantiles)
        # Add small individual noise
        derived_price_sensitivity = max(0.0, min(1.0, derived_price_sensitivity + self.rng.gauss(0, 0.04)))
        derived_wtp = max(0.1, derived_wtp * (1 + self.rng.gauss(0, 0.1)))

        cognitive = derive_cognitive_profile(
            hofstede=hofstede,
            big_five=big_five,
            income_usd=income_usd,
            income_quantiles=self._income_quantiles,
            age_group=age_group,
            rng=self.rng,
            derived_price_sensitivity=derived_price_sensitivity,
            derived_wtp=derived_wtp,
        )

        # Apply city tier cognitive adjustments
        if city_tier:
            cp = self._country_profiles.get(nationality, {})
            city_tiers_data = cp.get("city_tiers", [])
            tier_data = next((t for t in city_tiers_data if t["id"] == city_tier), None)
            if tier_data:
                novelty_adj = tier_data.get("novelty_adj", 0.0)
                price_adj = tier_data.get("price_sensitivity_adj", 0.0)
                cognitive.novelty_seeking = max(0.0, min(1.0, cognitive.novelty_seeking + novelty_adj))
                cognitive.price_sensitivity = max(0.0, min(1.0, cognitive.price_sensitivity + price_adj))

        persona_id = f"p_{uuid.uuid4().hex[:8]}"

        return Persona(
            persona_id=persona_id,
            name=name,
            flag=flag,
            nationality=nationality,
            country_name=country_name,
            age_group=age_group,
            age=age,
            gender=gender,
            income_bracket=income_bracket,
            income_local=income_local,
            income_currency=income_currency,
            income_usd=income_usd,
            occupation_id=occ["id"],
            occupation_title=occ.get("title", occ["id"]),
            occupation_title_local=occ.get("title_local", {}),
            occupation_category=occ.get("category", ""),
            occupation_education=occ.get("entry_education", ""),
            occupation_work_context=occ.get("work_context", ""),
            urban_rural=urban_rural,
            city_tier=city_tier,
            city_tier_label=city_tier_label,
            personality_type=personality_type,
            mbti=mbti,
            hofstede=hofstede,
            big_five=big_five,
            cognitive=cognitive,
        )
