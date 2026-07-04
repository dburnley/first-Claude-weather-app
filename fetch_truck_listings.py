"""Step 1: fetch raw truck listings from the MarketCheck API per truck_search_config.json.

No filtering or scoring here -- just confirm the fetch works and print what comes back.
"""
import json
import os
import sys

import requests

API_URL = "https://api.marketcheck.com/v2/search/car/active"
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "truck_search_config.json")


def load_config(path=CONFIG_PATH):
    with open(path) as f:
        return json.load(f)


def build_params(api_key, search_cfg, vehicle):
    year_min, year_max = vehicle["years"]
    return {
        "api_key": api_key,
        "make": vehicle["make"],
        "model": vehicle["model"],
        "zip": search_cfg["zip"],
        "radius": search_cfg["radius_miles"],
        "year_range": f"{max(year_min, search_cfg['min_year'])}-{year_max}",
        "price_range": f"0-{search_cfg['max_price_usd']}",
        "miles_range": f"0-{search_cfg['max_mileage']}",
        "car_type": "used",
        "rows": 20,
    }


def fetch_listings(api_key, search_cfg, vehicle):
    params = build_params(api_key, search_cfg, vehicle)
    resp = requests.get(API_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def main():
    api_key = os.environ.get("MARKETCHECK_API_KEY")
    if not api_key:
        sys.exit("Set MARKETCHECK_API_KEY in your environment before running this script.")

    config = load_config()
    search_cfg = config["search"]

    for vehicle in config["target_vehicles"]:
        label = f"{vehicle['make']} {vehicle['model']} ({vehicle['years'][0]}-{vehicle['years'][1]})"
        print(f"\n=== {label} ===")
        try:
            data = fetch_listings(api_key, search_cfg, vehicle)
        except requests.RequestException as e:
            print(f"Request failed: {e}")
            continue

        listings = data.get("listings", [])
        print(f"num_found: {data.get('num_found')}, returned: {len(listings)}")
        for listing in listings:
            print(json.dumps(listing, indent=2))


if __name__ == "__main__":
    main()
