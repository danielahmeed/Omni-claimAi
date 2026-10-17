#!/usr/bin/env python3
"""Render the sample repair invoices in samples/documents/ (PNG).

The invoices are fictional and exist so the demo presets have a real document
for Gemini to read. They are rendered from HTML with a local Chrome/Edge in
headless mode, then committed, so this script only needs to run when the
invoice content changes.

Usage:
    python tools/make_sample_documents.py            # auto-detects Chrome/Edge
    CHROME_PATH=/path/to/chrome python tools/make_sample_documents.py
"""

import html
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "samples" / "documents"

INVOICES = {
    "collision-invoice.png": {
        "shop": "Apex Prestige Collision & Frame",
        "address": "1450 Mandela Pkwy, Oakland, CA 94607",
        "contact": "(510) 555-0142 &middot; BAR Reg. ARD-284419",
        "title": "REPAIR INVOICE",
        "number": "APC-26-1014-07",
        "date": "2026-10-15",
        "customer": "Aaron Mitchell",
        "customer_extra": "Policy POL-AUTO-31877",
        "asset_label": "Vehicle",
        "asset": "2022 Mazda CX-5 Touring &middot; Black &middot; VIN JM3KFBCM2N0412207",
        "items": [
            ("Left rear wheel arch: repair and refinish (body labor 3.0 h)", "Labor", 650.00),
            ("Paint and materials (basecoat / clearcoat)", "Paint", 350.00),
            ("Clips, mouldings and hardware", "Parts", 250.00),
            ("Rear suspension assembly: replace (parts + 9.5 h labor)", "Parts", 3800.00),
            ("Exhaust system and heat shield: re-align, replace hangers", "Parts", 1150.00),
            ("Frame machine set-up and structural pull (rear)", "Labor", 2250.00),
        ],
        "tax_note": "Sales tax included",
        "notes": "Labor rate $145.00/hr. Customer reports low-speed contact with a parking garage pillar on 2026-10-14.",
    },
    "windshield-invoice.png": {
        "shop": "ClearView Auto Glass",
        "address": "8200 N Washington St, Thornton, CO 80229",
        "contact": "(303) 555-0187 &middot; Certified AGSC technician #4471",
        "title": "INVOICE",
        "number": "CV-48213",
        "date": "2026-10-12",
        "customer": "Sofia Martinez",
        "customer_extra": "Policy POL-AUTO-52044",
        "asset_label": "Vehicle",
        "asset": "2021 Ford Transit Connect XLT &middot; VIN NM0GE9F21M1490335",
        "items": [
            ("OEM laminated windshield (part)", "Parts", 520.00),
            ("ADAS forward camera recalibration (static + dynamic)", "Labor", 180.00),
            ("Urethane kit, moulding and installation labor", "Labor", 80.00),
        ],
        "tax_note": "Sales tax included",
        "notes": "Windshield shattered by a falling tree branch during the 2026-10-11 wind storm. Old glass disposed of.",
    },
    "water-damage-invoice.png": {
        "shop": "Beacon Hill Plumbing & Restoration",
        "address": "3021 Beacon Ave S, Seattle, WA 98144",
        "contact": "(206) 555-0119 &middot; WA Plumbing Lic. PLUM9921",
        "title": "EMERGENCY SERVICE INVOICE",
        "number": "BH-2026-3318",
        "date": "2026-10-13",
        "customer": "Hannah Lee",
        "customer_extra": "Policy POL-HOME-60218",
        "asset_label": "Property",
        "asset": "Single-family home &middot; 4412 Magnolia Blvd W, Seattle, WA 98199",
        "items": [
            ("Emergency call-out and 1/2\" copper supply line repair", "Labor", 750.00),
            ("Water extraction and dehumidification (48 hours)", "Equipment", 900.00),
            ("Ceiling drywall removal and replacement (12 sq ft)", "Labor", 1200.00),
            ("Texture match, stain-block primer and paint", "Paint", 600.00),
        ],
        "tax_note": "Sales tax included",
        "notes": "Supply pipe in the upstairs bathroom burst on 2026-10-12. Water stopped within 40 minutes; ceiling below saturated.",
    },
    "front-end-invoice.png": {
        "shop": "Midnight Auto Crafters & Custom Tuning",
        "address": "7900 NW 22nd Ave, Miami, FL 33147",
        "contact": "(305) 555-0166 &middot; Towing: Midnight Towing LLC",
        "title": "INVOICE",
        "number": "MAC-0915",
        "date": "2026-10-15",
        "customer": "Victor Hale",
        "customer_extra": "Policy POL-AUTO-90377",
        "asset_label": "Vehicle",
        "asset": "2024 BMW M4 Competition &middot; VIN WBS43AZ08RF882103",
        "items": [
            ("Engine block and M TwinPower turbo replacement", "Parts", 18500.00),
            ("Carbon-fibre front fascia and laser headlight assemblies", "Parts", 12000.00),
            ("Unibody laser measuring and subframe jig straightening", "Labor", 12000.00),
        ],
        "tax_note": "Tax exempt (cash account)",
        "notes": "Vehicle towed from warehouse lot at 2:40 AM on 2026-10-15. Payment due before release.",
    },
}

TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ width: 850px; height: 1100px; background: #fff; color: #1b1f24;
         font-family: Arial, Helvetica, sans-serif; font-size: 14px; padding: 56px 60px; }}
  .top {{ display: flex; justify-content: space-between; align-items: flex-start;
          border-bottom: 3px solid #1b1f24; padding-bottom: 18px; }}
  .shop {{ font-size: 24px; font-weight: 700; }}
  .muted {{ color: #555c66; font-size: 13px; line-height: 1.6; }}
  .doc {{ text-align: right; }}
  .doc h1 {{ font-size: 20px; letter-spacing: 0.06em; }}
  .grid {{ display: flex; gap: 40px; margin: 26px 0 22px; }}
  .grid div {{ flex: 1; }}
  .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: #555c66; margin-bottom: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 6px; }}
  th {{ text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
        color: #555c66; border-bottom: 1.5px solid #1b1f24; padding: 8px 6px; }}
  td {{ padding: 11px 6px; border-bottom: 1px solid #d9dde3; vertical-align: top; }}
  td.num, th.num {{ text-align: right; white-space: nowrap; }}
  .totals {{ margin-left: auto; width: 320px; margin-top: 18px; }}
  .totals div {{ display: flex; justify-content: space-between; padding: 6px 6px; }}
  .totals .grand {{ border-top: 2px solid #1b1f24; font-weight: 700; font-size: 17px; margin-top: 4px; padding-top: 10px; }}
  .notes {{ margin-top: 34px; padding: 14px 16px; background: #f4f5f7; border-radius: 4px; }}
  .sign {{ margin-top: 54px; display: flex; justify-content: space-between; color: #555c66; font-size: 12px; }}
  .sign span {{ border-top: 1px solid #8a919b; padding-top: 6px; width: 260px; }}
  .footer {{ position: absolute; bottom: 40px; left: 60px; right: 60px; text-align: center; color: #8a919b; font-size: 11px; }}
</style></head><body>
  <div class="top">
    <div><div class="shop">{shop}</div><div class="muted">{address}<br>{contact}</div></div>
    <div class="doc"><h1>{title}</h1><div class="muted">No. {number}<br>Date: {date}</div></div>
  </div>
  <div class="grid">
    <div><div class="label">Bill to</div><strong>{customer}</strong><div class="muted">{customer_extra}</div></div>
    <div><div class="label">{asset_label}</div><div>{asset}</div></div>
  </div>
  <table>
    <thead><tr><th style="width:36px">#</th><th>Description</th><th style="width:90px">Type</th><th class="num" style="width:120px">Amount (USD)</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <div class="totals">
    <div><span>Subtotal</span><span>{subtotal}</span></div>
    <div class="muted"><span>{tax_note}</span><span>0.00</span></div>
    <div class="grand"><span>Total due</span><span>${total}</span></div>
  </div>
  <div class="notes"><div class="label">Notes</div>{notes}</div>
  <div class="sign"><span>Authorized by</span><span>Customer signature</span></div>
  <div class="footer">Sample document generated for the OmniClaim AI demo. Fictional business and customer.</div>
</body></html>"""


def money(value: float) -> str:
    return f"{value:,.2f}"


def render_html(spec: dict) -> str:
    rows = "".join(
        f"<tr><td>{i}</td><td>{html.escape(desc)}</td><td>{kind}</td><td class=\"num\">{money(amount)}</td></tr>"
        for i, (desc, kind, amount) in enumerate(spec["items"], start=1)
    )
    total = sum(amount for _, _, amount in spec["items"])
    fields = {k: v for k, v in spec.items() if k != "items"}
    return TEMPLATE.format(rows=rows, subtotal=money(total), total=money(total), **fields)


def find_browser() -> str:
    candidates = [
        os.environ.get("CHROME_PATH", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
        shutil.which("chromium-browser") or "",
    ]
    for path in candidates:
        if path and Path(path).exists():
            return path
    sys.exit("Chrome/Edge not found. Set CHROME_PATH to a Chromium-based browser.")


def main():
    browser = find_browser()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, spec in INVOICES.items():
            page = Path(tmp) / (name + ".html")
            page.write_text(render_html(spec), encoding="utf-8")
            target = OUT_DIR / name
            subprocess.run([
                browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                f"--user-data-dir={Path(tmp) / 'profile'}",
                "--force-device-scale-factor=1.6", "--window-size=850,1100",
                f"--screenshot={target}", page.as_uri(),
            ], check=True, capture_output=True)
            print(f"Rendered {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
