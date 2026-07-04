"""Step 3: score passed listings using truck_search_config.json's scoring.weights.

Honesty over completeness: two weighted components still need data MarketCheck's free
tier doesn't provide (service records and verified tow packages aren't in the payload
at all -- see filter_listings.py). Those score 0 and are marked "unavailable" rather
than faked, and each listing reports a data_coverage fraction so low scores caused by
missing data aren't confused with low scores caused by a bad truck.

price_drop_history is now backed by state_db.py (step 4): a listing needs at least two
runs' worth of price sightings before it counts as "available".

flags_not_scored (four_wheel_drive, flood_region_history) are informational only,
per the config: they must never factor into the ranking.
"""
import statistics

from filter_listings import filter_vehicle_listings, get_drivetrain, get_year
from fetch_truck_listings import fetch_listings, load_config
import state_db


def price_vs_comps(price, comp_prices, weight):
    if price is None or len(comp_prices) < 2:
        return 0.0, weight, False
    avg = statistics.mean(comp_prices)
    if avg <= 0:
        return 0.0, weight, False
    pct_below_avg = (avg - price) / avg
    return weight * max(0.0, min(1.0, pct_below_avg)), weight, True


def days_on_lot(listing, weight):
    dom = listing.get("dom")
    if dom is None:
        return 0.0, weight, False
    return (weight if dom > 45 else 0.0), weight, True


def single_owner(listing, weight):
    if listing.get("carfax_1_owner") is True:
        return weight, weight, True
    if listing.get("carfax_1_owner") is False:
        return 0.0, weight, True
    return 0.0, weight, False


def unavailable(weight):
    """verified_tow_package, service_records_available: no data source wired up yet."""
    return 0.0, weight, False


def price_drop_history(listing, weight, conn):
    vin = listing.get("vin")
    if conn is None or vin is None:
        return 0.0, weight, False
    pct = state_db.price_drop_pct(conn, vin)
    if pct is None:
        return 0.0, weight, False
    return weight * pct, weight, True


def score_listing(listing, comp_prices, weights, conn=None):
    breakdown = {}
    earned_total = 0.0
    covered_weight = 0.0

    checks = {
        "price_vs_market_comps": lambda w: price_vs_comps(listing.get("price"), comp_prices, w),
        "days_on_lot_over_45": lambda w: days_on_lot(listing, w),
        "price_drop_history": lambda w: price_drop_history(listing, w, conn),
        "single_owner": lambda w: single_owner(listing, w),
        "verified_tow_package": lambda w: unavailable(w),
        "service_records_available": lambda w: unavailable(w),
    }

    for name, weight in weights.items():
        earned, weight, available = checks[name](weight)
        breakdown[name] = {"earned": round(earned, 4), "weight": weight, "available": available}
        earned_total += earned
        if available:
            covered_weight += weight

    return {
        "total_score": round(earned_total, 4),
        "data_coverage": round(covered_weight / sum(weights.values()), 2),
        "breakdown": breakdown,
        "drivetrain_badge": get_drivetrain(listing) or "unknown",
        "flood_region_history": "unknown (no Carfax history feed configured)",
    }


def score_vehicle_listings(passed, weights, conn=None, vehicle=None):
    comp_prices = [p["listing"]["price"] for p in passed if p["listing"].get("price") is not None]
    scored = []
    for item in passed:
        listing = item["listing"]
        state = None
        if conn is not None:
            vin = listing.get("vin")
            build = listing.get("build", {})
            state = state_db.upsert_listing(
                conn, vin,
                build.get("make", vehicle["make"] if vehicle else None),
                build.get("model", vehicle["model"] if vehicle else None),
                get_year(listing),
                listing.get("price"),
            )
        result = score_listing(listing, comp_prices, weights, conn)
        scored.append({**item, "score": result, "state": state})
    scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)
    return scored


def main():
    import os
    import sys

    api_key = os.environ.get("MARKETCHECK_API_KEY")
    if not api_key:
        sys.exit("Set MARKETCHECK_API_KEY in your environment before running this script.")

    config = load_config()
    search_cfg = config["search"]
    exclusions_cfg = config["exclusions"]
    weights = config["scoring"]["weights"]
    conn = state_db.connect(state_db.db_path_from_config(config))

    for vehicle in config["target_vehicles"]:
        label = f"{vehicle['make']} {vehicle['model']} ({vehicle['years'][0]}-{vehicle['years'][1]})"
        print(f"\n=== {label} ===")
        data = fetch_listings(api_key, search_cfg, vehicle)
        listings = data.get("listings", [])

        passed, _ = filter_vehicle_listings(listings, vehicle, search_cfg, exclusions_cfg)
        scored = score_vehicle_listings(passed, weights, conn, vehicle)

        for item in scored:
            vin = item["listing"].get("vin")
            score = item["score"]
            state = item["state"] or {}
            status = "NEW" if state.get("is_new") else "seen before"
            if state.get("price_changed"):
                status += f" (price changed from {state['previous_price']})"
            print(f"\nvin={vin} [{status}] score={score['total_score']} coverage={score['data_coverage']}")
            print(f"  4x4 badge: {score['drivetrain_badge']}  flood history: {score['flood_region_history']}")
            for name, detail in score["breakdown"].items():
                tag = "" if detail["available"] else " (unavailable)"
                print(f"  {name}: {detail['earned']}/{detail['weight']}{tag}")

    conn.close()


if __name__ == "__main__":
    main()
