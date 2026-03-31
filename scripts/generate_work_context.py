#!/usr/bin/env python3
"""
Generate work_context for 342 BLS occupations using GLM-5.1.
Usage: .venv/bin/python3 scripts/generate_work_context.py
"""

import json
import os
import time
import re
import shutil
import csv
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# Load env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

API_KEY = os.getenv("WS_API_KEY") or os.getenv("LLM_API_KEY")
BASE_URL = os.getenv("WS_API_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4")
MODEL = os.getenv("WS_MODEL", "glm-5.1")

print(f"API_KEY: {API_KEY[:8]}... BASE_URL: {BASE_URL} MODEL: {MODEL}")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

DATA_PATH = Path(__file__).parent.parent / "data" / "occupations.json"
CSV_OUTPUT = Path("/tmp/worldsense_occupations_v4.csv")
OUTBOX = Path.home() / ".openclaw/media/outbox/worldsense_occupations_v4.csv"

BATCH_SIZE = 30
SLEEP_BETWEEN_BATCHES = 2

SYSTEM_PROMPT = """You generate concise, specific work context descriptions for occupations.
Each description should be 2-3 sentences. Focus on:
- Daily work reality and environment  
- Income stability (stable salary vs gig/commission-based)
- Technology exposure level
- Social circle and information sources
- Consumer psychology implications (spending habits, risk tolerance)

Be specific and realistic. Avoid generic platitudes.

IMPORTANT: Use the exact occupation ID as the key (e.g. "accountants-and-auditors"), NOT a number.
Return ONLY a valid JSON object. No markdown code blocks. No extra text."""


def build_user_prompt(batch):
    lines = ["For each occupation, write a 2-3 sentence work context description.\n",
             "Return a JSON object where keys are the exact occupation IDs shown below.\n",
             "Occupations:"]
    for i, occ in enumerate(batch, 1):
        title = occ["title"]
        local_title = occ.get("title_local", {}).get("CN", "")
        pay = occ.get("median_pay_annual_usd", 0)
        edu = occ.get("entry_education", "N/A")
        occ_id = occ["id"]
        local_str = f" ({local_title})" if local_title else ""
        pay_str = f"${pay:,}/yr" if pay else "N/A"
        lines.append(f'{i}. ID="{occ_id}" | {title}{local_str} | {pay_str}, {edu}')

    lines.append("\nExample output format:")
    lines.append('{"accountants-and-auditors": "Works in corporate offices...", "actors": "Freelance..."}\n')
    lines.append("Now generate for ALL occupations listed above:")
    return "\n".join(lines)


def extract_json_from_response(text, batch):
    """Extract JSON object from model response. Falls back to numeric key mapping."""
    text = text.strip()

    # Strip markdown code block if present
    code_match = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', text)
    candidate = code_match.group(1) if code_match else text

    # Also try just finding the outermost {...}
    brace_match = re.search(r'\{[\s\S]+\}', candidate, re.DOTALL)
    json_str = brace_match.group(0) if brace_match else candidate

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError:
        # Try the full text with brace extraction
        brace_match2 = re.search(r'\{[\s\S]+\}', text, re.DOTALL)
        if brace_match2:
            try:
                parsed = json.loads(brace_match2.group(0))
            except json.JSONDecodeError:
                return None
        else:
            return None

    # Check if keys are numeric (1, 2, ...) - map back to IDs
    if parsed and all(k.isdigit() for k in list(parsed.keys())[:3]):
        remapped = {}
        for num_key, value in parsed.items():
            idx = int(num_key) - 1
            if 0 <= idx < len(batch):
                remapped[batch[idx]["id"]] = value
        return remapped

    return parsed


def generate_batch(batch, batch_num, total_batches):
    user_prompt = build_user_prompt(batch)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=4096,
            temperature=0.7,
            extra_body={"enable_thinking": False},
        )

        content = response.choices[0].message.content
        result = extract_json_from_response(content, batch)

        if result is None:
            print(f"  [WARN] Batch {batch_num}/{total_batches}: Failed to parse JSON response")
            print(f"  [DEBUG] Response preview: {content[:300]}")
            return {}

        return result

    except Exception as e:
        print(f"  [ERROR] Batch {batch_num}/{total_batches}: API error: {e}")
        return {}


def main():
    # Load data
    with open(DATA_PATH) as f:
        occupations = json.load(f)

    # Filter missing work_context
    missing = [o for o in occupations if not o.get("work_context")]
    total = len(missing)
    print(f"Found {total} occupations missing work_context")

    # Build ID -> index map for fast update
    id_to_idx = {o["id"]: i for i, o in enumerate(occupations)}

    # Split into batches
    batches = [missing[i:i+BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    total_batches = len(batches)
    print(f"Processing {total} occupations in {total_batches} batches of {BATCH_SIZE}")

    done = 0
    failed_batches = []

    for batch_num, batch in enumerate(batches, 1):
        print(f"Batch {batch_num}/{total_batches}: {done}/{total} done", flush=True)

        results = generate_batch(batch, batch_num, total_batches)

        if not results:
            failed_batches.append(batch_num)
            print(f"  [SKIP] Batch {batch_num} skipped (no results)")
        else:
            # Update occupations in-place
            updated = 0
            for occ in batch:
                occ_id = occ["id"]
                if occ_id in results:
                    ctx = results[occ_id]
                    if ctx and isinstance(ctx, str):
                        occupations[id_to_idx[occ_id]]["work_context"] = ctx.strip()
                        updated += 1
            print(f"  [OK] Updated {updated}/{len(batch)} occupations")
            done += updated

        # Sleep between batches (except last)
        if batch_num < total_batches:
            time.sleep(SLEEP_BETWEEN_BATCHES)

    print(f"\nCompleted: {done}/{total} work_contexts generated")
    if failed_batches:
        print(f"Failed batches: {failed_batches}")

    # Write back to occupations.json
    with open(DATA_PATH, "w") as f:
        json.dump(occupations, f, ensure_ascii=False, indent=2)
    print(f"Saved to {DATA_PATH}")

    # Export CSV
    simple_fields = ["id", "title", "category", "soc_code", "median_pay_annual_usd",
                     "entry_education", "num_jobs_us", "work_context"]

    with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=simple_fields, extrasaction="ignore")
        writer.writeheader()
        for occ in occupations:
            writer.writerow({k: occ.get(k, "") for k in simple_fields})

    print(f"CSV exported to {CSV_OUTPUT}")

    # Copy to outbox
    OUTBOX.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CSV_OUTPUT, OUTBOX)
    print(f"Copied to {OUTBOX}")

    # Verify samples
    print("\n--- Sample work_contexts ---")
    sample_ids = ["accountants-and-auditors", "actors", "software-developers",
                  "registered-nurses", "construction-laborers"]
    for occ in occupations:
        if occ["id"] in sample_ids:
            print(f"\n[{occ['id']}]")
            print(f"  {occ.get('work_context', '(empty)')}")

    # Final stats
    final_with_ctx = sum(1 for o in occupations if o.get("work_context"))
    print(f"\nFinal: {final_with_ctx}/{len(occupations)} occupations have work_context")


if __name__ == "__main__":
    main()
