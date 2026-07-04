"""Step 5: notifications per truck_search_config.json's "notifications" block.

Runs the full search -> filter -> score pipeline (steps 1-4) across every
target vehicle, merges everything into one global ranking, and renders a PDF
digest: the top max_listings_per_digest listings by score_desc, with anything
scoring at or above immediate_alert_threshold_score called out separately.

This produces the PDF only -- there's no real email/SMS send wired up (no
provider credentials or API for that in this environment). Delivery is
whatever the caller does with the returned path.
"""
import os
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from fetch_truck_listings import fetch_listings, load_config
from filter_listings import filter_vehicle_listings
from score_listings import score_vehicle_listings
import state_db

DIGEST_DIR = os.path.join(os.path.dirname(__file__), "digests")


def collect_all_scored(api_key, config, conn):
    search_cfg = config["search"]
    exclusions_cfg = config["exclusions"]
    weights = config["scoring"]["weights"]

    all_scored = []
    for vehicle in config["target_vehicles"]:
        data = fetch_listings(api_key, search_cfg, vehicle)
        passed, _ = filter_vehicle_listings(data.get("listings", []), vehicle, search_cfg, exclusions_cfg)
        scored = score_vehicle_listings(passed, weights, conn, vehicle)
        for item in scored:
            item["vehicle_label"] = f"{vehicle['make']} {vehicle['model']}"
        all_scored.extend(scored)

    all_scored.sort(key=lambda x: x["score"]["total_score"], reverse=True)
    return all_scored


def _table(items):
    header = ["Vehicle", "VIN", "Price", "Score", "Coverage", "Status", "4x4"]
    rows = [header]
    for item in items:
        listing, score, state = item["listing"], item["score"], item["state"] or {}
        status = "NEW" if state.get("is_new") else "seen"
        if state.get("price_changed"):
            status += " (price drop)"
        price = listing.get("price")
        rows.append([
            item.get("vehicle_label", ""),
            listing.get("vin", ""),
            f"${price:,.0f}" if price is not None else "?",
            f"{score['total_score']:.2f}",
            f"{score['data_coverage']:.0%}",
            status,
            score["drivetrain_badge"],
        ])
    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f7")]),
    ]))
    return table


def build_pdf(scored_items, notif_cfg, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Truck Search Daily Digest", styles["Title"]),
        Paragraph(date.today().isoformat(), styles["Normal"]),
        Spacer(1, 12),
    ]

    top_n = scored_items[: notif_cfg["max_listings_per_digest"]]
    threshold = notif_cfg["immediate_alert_threshold_score"]
    immediate = [i for i in top_n if i["score"]["total_score"] >= threshold]

    if immediate:
        story.append(Paragraph(f"Immediate alerts (score &gt;= {threshold})", styles["Heading2"]))
        story.append(_table(immediate))
        story.append(Spacer(1, 16))

    story.append(Paragraph(f"Top {len(top_n)} by score", styles["Heading2"]))
    story.append(_table(top_n) if top_n else Paragraph("No listings passed filtering today.", styles["Normal"]))

    SimpleDocTemplate(out_path, pagesize=letter).build(story)
    return out_path


def run_digest():
    import sys

    api_key = os.environ.get("MARKETCHECK_API_KEY")
    if not api_key:
        sys.exit("Set MARKETCHECK_API_KEY in your environment before running this script.")

    config = load_config()
    conn = state_db.connect(state_db.db_path_from_config(config))
    scored_items = collect_all_scored(api_key, config, conn)
    conn.close()

    out_path = os.path.join(DIGEST_DIR, f"truck_digest_{date.today().isoformat()}.pdf")
    build_pdf(scored_items, config["notifications"], out_path)
    print(f"Digest written to {out_path}")
    return out_path


if __name__ == "__main__":
    run_digest()
