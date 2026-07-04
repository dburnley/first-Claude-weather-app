"""Step 2: apply truck_search_config.json's exclusion rules to raw MarketCheck listings.

Splits each vehicle's listings into "passed" (with unverifiable items flagged for manual
inspection) and "excluded" (with reasons). No scoring yet -- that's step 3.

MarketCheck's free-tier listing payload only gives us a couple of Carfax-derived booleans
(carfax_clean_title, carfax_1_owner) -- it has no owner *count*, no flood-history field, and
no tow-package/equipment data at all. Anything the config asks us to check that isn't in the
payload gets flagged rather than silently assumed, same spirit as the config's own
"unverified_action": "flag_inspect_before_drive" for tow packages.
"""
import json

from fetch_truck_listings import fetch_listings, load_config


def get_year(listing):
    return listing.get("build", {}).get("year")


def get_drivetrain(listing):
    return listing.get("build", {}).get("drivetrain")


def exclusions_for(listing, vehicle, search_cfg, exclusions_cfg):
    reasons = []

    model = listing.get("build", {}).get("model", vehicle["model"])
    if model in exclusions_cfg["models"]:
        reasons.append(f"model '{model}' is in excluded models list")

    year = get_year(listing)
    if year is not None and year < search_cfg["min_year"]:
        reasons.append(f"year {year} below min_year {search_cfg['min_year']}")

    price = listing.get("price")
    if price is not None and price > search_cfg["max_price_usd"]:
        reasons.append(f"price {price} above max_price_usd {search_cfg['max_price_usd']}")

    miles = listing.get("miles")
    if miles is not None and miles > search_cfg["max_mileage"]:
        reasons.append(f"miles {miles} above max_mileage {search_cfg['max_mileage']}")

    clean_title = listing.get("carfax_clean_title")
    if clean_title is False:
        reasons.append("carfax_clean_title is False (likely salvage/rebuilt)")

    return reasons


def flags_for(listing):
    flags = []

    if listing.get("carfax_clean_title") is None:
        flags.append("title status not reported by source; verify before driving")

    if listing.get("carfax_1_owner") is not True:
        flags.append("owner count not confirmable from listing data (config caps at 2)")

    flags.append("tow package not verifiable from listing data: flag_inspect_before_drive")

    return flags


def filter_vehicle_listings(listings, vehicle, search_cfg, exclusions_cfg):
    passed, excluded = [], []
    for listing in listings:
        reasons = exclusions_for(listing, vehicle, search_cfg, exclusions_cfg)
        if reasons:
            excluded.append({"listing": listing, "reasons": reasons})
        else:
            passed.append({"listing": listing, "flags": flags_for(listing)})
    return passed, excluded


def main():
    import os
    import sys

    api_key = os.environ.get("MARKETCHECK_API_KEY")
    if not api_key:
        sys.exit("Set MARKETCHECK_API_KEY in your environment before running this script.")

    config = load_config()
    search_cfg = config["search"]
    exclusions_cfg = config["exclusions"]

    for vehicle in config["target_vehicles"]:
        label = f"{vehicle['make']} {vehicle['model']} ({vehicle['years'][0]}-{vehicle['years'][1]})"
        print(f"\n=== {label} ===")
        data = fetch_listings(api_key, search_cfg, vehicle)
        listings = data.get("listings", [])

        passed, excluded = filter_vehicle_listings(listings, vehicle, search_cfg, exclusions_cfg)
        print(f"passed: {len(passed)}, excluded: {len(excluded)}")

        for item in passed:
            vin = item["listing"].get("vin")
            print(f"\nPASSED vin={vin}")
            for flag in item["flags"]:
                print(f"  FLAG: {flag}")

        for item in excluded:
            vin = item["listing"].get("vin")
            print(f"\nEXCLUDED vin={vin}")
            for reason in item["reasons"]:
                print(f"  REASON: {reason}")


if __name__ == "__main__":
    main()
