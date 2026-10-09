"""Run a verified YesStyle natural-fiber clothing research pass via Browser Use.

The script reads BROWSER_USE_API_KEY from .env, sends the approved research
brief to Browser Use Cloud, validates the returned JSON, and saves a reviewable
CSV plus the raw response. It never prints the API key.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
API_URL = "https://api.browser-use.com/api/v4/runs"
OUTPUT_CSV = ROOT / "yesstyle_square_neck_long_sleeve_natural_fibers.csv"
RAW_OUTPUT = ROOT / "yesstyle_research_raw.json"
FIELDS = [
    "product_name", "brand", "price", "currency", "product_url", "image_url",
    "neckline", "sleeve_length", "fiber_composition", "fiber_category",
    "natural_fiber", "natural_fiber_type", "natural_fiber_percentage",
    "synthetic_fiber", "color_options", "sizes", "rating", "review_count",
    "availability", "neckline_evidence", "sleeve_evidence", "fiber_evidence",
    "match_confidence", "notes",
]


TASK = r'''Research women's clothing on YesStyle and return ONLY a JSON object.

Search this exact query, reviewing the first 20 results
1. square neck long sleeve

For every plausible candidate, open the YesStyle product page. Include a product
only if the product page verifies all of: (a) square neckline from its images or
description; (b) long sleeves from its images or description; (c) exact material
composition; and (d) conventional natural fibers are more than 50% of composition.
Exclude 100% synthetic products, products with unverified composition, unclear
neckline or sleeve length, and duplicates. Do not infer any facts from titles.

Material categories: NATURAL is 100% cotton, linen, hemp, wool, cashmere, silk,
or another conventional natural fiber; NATURAL_BLEND has more than 50% conventional
natural fiber plus other fiber; REGENERATED_CELLULOSE covers rayon, viscose, modal,
lyocell, and Tencel (include only if it satisfies the primarily-natural rule and
state the caveat); SYNTHETIC is polyester, nylon, acrylic, polyurethane, spandex,
or similar; UNKNOWN is unavailable composition and must be excluded.

Return valid JSON with exactly this shape, no Markdown or commentary:
{
  "products": [
    {
      "product_name": null, "brand": null, "price": null, "currency": null,
      "product_url": null, "image_url": null, "neckline": "Square",
      "sleeve_length": "Long", "fiber_composition": null,
      "fiber_category": null, "natural_fiber": null,
      "natural_fiber_type": null, "natural_fiber_percentage": null,
      "synthetic_fiber": null, "color_options": null, "sizes": null,
      "rating": null, "review_count": null, "availability": null,
      "neckline_evidence": null, "sleeve_evidence": null,
      "fiber_evidence": null, "match_confidence": null, "notes": null
    }
  ],
  "research_summary": {
    "queries": [], "candidates_reviewed": 0, "included": 0,
    "exclusions": {}, "limitations": []
  }
}
Use null when a field is not shown on the product page. Keep evidence concise and
record fiber composition verbatim. Use semicolons between multiple colors or sizes.'''


def load_env() -> None:
    """Load simple KEY=VALUE pairs without needing a dependency."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def request(url: str, method: str = "GET", body: dict | None = None) -> dict:
    api_key = os.environ["BROWSER_USE_API_KEY"]
    encoded = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=encoded, method=method)
    req.add_header("X-Browser-Use-API-Key", api_key)
    if encoded:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Browser Use API returned HTTP {exc.code}: {detail}") from exc


def parse_result(result: str) -> dict:
    """Accept a pure JSON response, tolerating accidental fenced JSON."""
    text = result.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("products"), list):
        raise ValueError("Browser Use result did not include a products list")
    return parsed


def write_csv(products: list[dict]) -> None:
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for product in products:
            writer.writerow({field: product.get(field) for field in FIELDS})


def main() -> int:
    load_env()
    if not os.environ.get("BROWSER_USE_API_KEY"):
        raise RuntimeError("BROWSER_USE_API_KEY is not configured in .env or the environment")

    # Passing a run ID resumes retrieval after a local terminal timeout without
    # creating duplicate paid research work.
    if len(sys.argv) == 3 and sys.argv[1] in {"--run-id", "--status"}:
        run_id = sys.argv[2]
        if sys.argv[1] == "--status":
            status = request(f"{API_URL}/{run_id}/status")
            print(f"Run status: {status.get('status')}")
            return 0
        print(f"Resuming research run {run_id}.", flush=True)
    elif len(sys.argv) == 1:
        # This cap contains one broad, verification-heavy research pass.
        created = request(API_URL, "POST", {"task": TASK, "maxCostUsd": 3.00})
        run_id = created["id"]
        print(f"Research started (run {run_id}).", flush=True)
    else:
        raise ValueError("Usage: python3 research.py [--run-id RUN_ID | --status RUN_ID]")

    deadline = time.monotonic() + 1800
    last_state = None
    while time.monotonic() < deadline:
        status = request(f"{API_URL}/{run_id}/status")
        state = status.get("status")
        if state != last_state:
            print(f"Run status: {state}", flush=True)
            last_state = state
        if state in {"completed", "failed", "cancelled"}:
            break
        time.sleep(10)
    else:
        raise TimeoutError(f"Run {run_id} did not finish within 30 minutes; it remains active remotely.")

    run = request(f"{API_URL}/{run_id}")
    if run.get("status") != "completed":
        raise RuntimeError(f"Run {run_id} ended with status {run.get('status')}: {run.get('error', '')}")
    result = parse_result(run["result"])
    RAW_OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(result["products"])
    print(f"Saved {len(result['products'])} verified products to {OUTPUT_CSV.name}.")
    print(json.dumps(result.get("research_summary", {}), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Research failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
