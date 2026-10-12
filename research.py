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
OUTPUT_CSV = ROOT / "yesstyle_square_neck_long_sleeve_top_autumn_natural_fibers.csv"
CANDIDATES_CSV = ROOT / "yesstyle_square_neck_long_sleeve_top_autumn_candidates.csv"
RAW_OUTPUT = ROOT / "yesstyle_top_autumn_research_raw.json"
FIELDS = [
    "product_name", "brand", "price", "currency", "product_url", "image_url",
    "neckline", "sleeve_length", "fiber_composition", "fiber_category",
    "natural_fiber", "natural_fiber_type", "natural_fiber_percentage",
    "synthetic_fiber", "color_options", "sizes", "rating", "review_count",
    "availability", "neckline_evidence", "sleeve_evidence", "fiber_evidence",
    "match_confidence", "notes",
]
CONVENTIONAL_NATURAL_FIBERS = ("cotton", "linen", "hemp", "wool", "cashmere", "silk")
AUTUMN_COLOR_TERMS = (
    "black", "white", "off white", "off-white", "ivory", "cream", "ecru",
    "beige", "camel", "khaki", "brown", "coffee", "mocha", "chocolate",
    "taupe", "sand", "sandy", "oatmeal", "natural", "bone", "olive",
    "army green", "forest green", "dark green", "moss", "sage", "green",
    "rust", "terracotta", "burnt orange", "mustard", "burgundy", "wine red",
    "maroon",
)


TASK = r'''Research women's clothing on YesStyle and return ONLY a JSON object.

Use plain, friendly, problem-focused language in all free-text fields. Prefer
short bullet-style facts in notes and exclusion reasons. Do not make up labels,
material categories, or explanations that YesStyle does not provide.

What to look for

- Search YesStyle for this exact query only: square neck long sleeve top.
- Review no more than 20 plausible products. A plausible product is one you open
  on its own YesStyle page to check it properly. Stop after the twentieth one.
- If you need another results page, click YesStyle's visible page number or Next
  button. Do not invent or edit page URLs.

For every product you open, check the product page for:

- A clearly square neckline.
- Long sleeves.
- The exact material composition.
- More than 50% conventional natural fiber: cotton, linen, hemp, wool, cashmere,
  or silk.
- At least one selected color option from this autumn-friendly list: Black, White,
  Off White, Off-White, Ivory, Cream, Ecru, Beige, Camel, Khaki, Brown, Coffee,
  Mocha, Chocolate, Taupe, Sand, Sandy, Oatmeal, Natural, Bone, Olive, Army Green,
  Forest Green, Dark Green, Moss, Sage, Green, Rust, Terracotta, Burnt Orange,
  Mustard, Burgundy, Wine Red, or Maroon.

Use the exact color label shown by YesStyle. Do not decide a color from a product
image. Do not guess a material from the title or image. Exclude 100% synthetic
items, items with missing composition, unclear necklines or sleeve lengths, and
items without a requested color option.

For `fiber_category`, leave the value null unless YesStyle itself provides a
matching category. The exact `fiber_composition` and natural-fiber percentage are
more useful than a made-up label.

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
  "candidates": [
    {
      "product_name": null, "brand": null, "price": null, "currency": null,
      "product_url": null, "image_url": null, "neckline": null,
      "sleeve_length": null, "fiber_composition": null,
      "fiber_category": null, "natural_fiber": null,
      "natural_fiber_type": null, "natural_fiber_percentage": null,
      "synthetic_fiber": null, "color_options": null, "sizes": null,
      "rating": null, "review_count": null, "availability": null,
      "neckline_evidence": null, "sleeve_evidence": null,
      "fiber_evidence": null, "match_confidence": null, "notes": null,
      "candidate_status": null, "exclusion_reason": null
    }
  ],
  "research_summary": {
    "queries": [], "result_pages_reviewed": 0, "candidates_reviewed": 0,
    "included": 0, "exclusions": {}, "limitations": [],
    "completion_reason": null
  }
}
`products` contains strict matches only. `candidates` contains one row for every
candidate opened during research, whether it qualifies or not; it must contain
exactly `research_summary.candidates_reviewed` rows and that number must not
exceed 20. Do not return a compact summary, a shortlist, or a count that exceeds
the number of candidate rows. For each candidate, use `candidate_status` of
`included` or `excluded` and give a concise `exclusion_reason`; use `included`
for strict matches. Use null when a field is not shown. Keep evidence concise,
record fiber composition verbatim, and use semicolons between multiple colors or
sizes.'''


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
    if not isinstance(parsed.get("candidates", []), list):
        raise ValueError("Browser Use result candidates field was not a list")
    summary = parsed.get("research_summary")
    if not isinstance(summary, dict):
        raise ValueError("Browser Use result did not include a research summary")
    reviewed = summary.get("candidates_reviewed")
    if not isinstance(reviewed, int) or reviewed != len(parsed["candidates"]):
        raise ValueError(
            "Browser Use did not itemize every reviewed candidate; no CSV was written"
        )
    if reviewed > 20:
        raise ValueError("Browser Use exceeded the 20-candidate research limit")
    return parsed


def write_csv(products: list[dict], destination: Path, fields: list[str] = FIELDS) -> None:
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for product in products:
            writer.writerow({field: product.get(field) for field in fields})


def qualifies_as_primarily_conventional_natural_fiber(product: dict) -> bool:
    """Enforce the brief rather than trusting an agent material label alone."""
    fiber_type = str(product.get("natural_fiber_type") or "").lower()
    category = str(product.get("fiber_category") or "").upper()
    percentage = str(product.get("natural_fiber_percentage") or "").replace("%", "").strip()
    try:
        amount = float(percentage)
    except ValueError:
        return False
    return (
        amount > 50
        and category != "REGENERATED_CELLULOSE"
        and any(fiber in fiber_type for fiber in CONVENTIONAL_NATURAL_FIBERS)
    )


def has_requested_color_option(product: dict) -> bool:
    colors = str(product.get("color_options") or "").lower()
    return any(term in colors for term in AUTUMN_COLOR_TERMS)


def main() -> int:
    load_env()
    if not os.environ.get("BROWSER_USE_API_KEY"):
        raise RuntimeError("BROWSER_USE_API_KEY is not configured in .env or the environment")

    # Passing a run ID resumes retrieval after a local terminal timeout without
    # creating duplicate paid research work.
    if len(sys.argv) == 3 and sys.argv[1] in {"--run-id", "--status", "--cancel"}:
        run_id = sys.argv[2]
        if sys.argv[1] == "--status":
            status = request(f"{API_URL}/{run_id}/status")
            print(f"Run status: {status.get('status')}")
            return 0
        if sys.argv[1] == "--cancel":
            cancelled = request(f"{API_URL}/{run_id}/cancel", "POST")
            print(f"Run cancellation requested: {cancelled.get('status', 'accepted')}")
            return 0
        print(f"Resuming research run {run_id}.", flush=True)
    elif len(sys.argv) == 1:
        # The user requested no artificial spend cap: stop when results end or
        # the Browser Use account has no remaining credit.
        created = request(API_URL, "POST", {"task": TASK})
        run_id = created["id"]
        print(f"Research started (run {run_id}).", flush=True)
    else:
        raise ValueError("Usage: python3 research.py [--run-id RUN_ID | --status RUN_ID | --cancel RUN_ID]")

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
    qualifying_products = [
        product for product in result["products"]
        if (
            qualifies_as_primarily_conventional_natural_fiber(product)
            and has_requested_color_option(product)
        )
    ]
    all_candidates = result.get("candidates") or result["products"]
    write_csv(qualifying_products, OUTPUT_CSV)
    write_csv(
        all_candidates,
        CANDIDATES_CSV,
        FIELDS + ["candidate_status", "exclusion_reason"],
    )
    summary = result.get("research_summary", {})
    summary["included_after_validation"] = len(qualifying_products)
    summary["post_validation_exclusions"] = len(result["products"]) - len(qualifying_products)
    print(f"Saved {len(qualifying_products)} verified products to {OUTPUT_CSV.name}.")
    print(f"Saved {len(all_candidates)} potential candidates to {CANDIDATES_CSV.name}.")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Research failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
