"""
match_screenshots.py
Sends each screenshot to Claude, gets a one-line description,
prints filename + description so we can remap local_asset_path in DB.
"""
import os, base64, json, urllib.request, urllib.error, sqlite3
from pathlib import Path

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DB_PATH = Path(r"C:\AI\Platform\MediaVault\core\mediavault.sqlite")

SCREENSHOTS = [
    Path(r"C:\Users\macun\OneDrive\Pictures\Screenshots") / f
    for f in [
        "Screenshot 2026-03-31 131037.png",
        "Screenshot 2026-03-31 131103.png",
        "Screenshot 2026-03-31 131121.png",
        "Screenshot 2026-03-31 131144.png",
        "Screenshot 2026-03-31 131209.png",
        "Screenshot 2026-03-31 131217.png",
        "Screenshot 2026-03-31 131236.png",
        "Screenshot 2026-03-31 131246.png",
        "Screenshot 2026-03-31 131258.png",
        "Screenshot 2026-03-31 131316.png",
        "Screenshot 2026-03-31 131332.png",
        "Screenshot 2026-03-31 131344.png",
        "Screenshot 2026-03-31 131356.png",
        "Screenshot 2026-03-31 131413.png",
        "Screenshot 2026-03-31 131425.png",
        "Screenshot 2026-03-31 131435.png",
        "Screenshot 2026-03-31 131444.png",
        "Screenshot 2026-03-31 131454.png",
        "Screenshot 2026-03-31 131501.png",
        "Screenshot 2026-03-31 131509.png",
        "Screenshot 2026-03-31 131522.png",
        "Screenshot 2026-03-31 131537.png",
        "Screenshot 2026-03-31 131556.png",
        "Screenshot 2026-03-31 131617.png",
        "Screenshot 2026-03-31 131634.png",
        "Screenshot 2026-03-31 131653.png",
        "Screenshot 2026-03-31 131706.png",
        "Screenshot 2026-03-31 131715.png",
    ]
] + [Path(r"C:\AI\Platform\MediaVault\intake\drop\Screenshot 2026-03-31 131715.png")]

PROMPT = "Describe this screenshot in one sentence. Focus on: who is shown, what is happening, any visible text (post title, song name, date, URL). Be specific."

def describe(path):
    data = base64.b64encode(path.read_bytes()).decode()
    body = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 200,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
            {"type": "text", "text": PROMPT}
        ]}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body,
        headers={"Content-Type": "application/json", "anthropic-version": "2023-06-01", "x-api-key": API_KEY},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["content"][0]["text"].strip()

def main():
    conn = sqlite3.connect(DB_PATH)
    records = conn.execute("SELECT id, description_short FROM artifacts ORDER BY id").fetchall()
    conn.close()

    print("\n=== SCREENSHOT DESCRIPTIONS ===\n")
    results = []
    for p in SCREENSHOTS:
        if not p.exists():
            print(f"MISSING: {p.name}")
            continue
        try:
            desc = describe(p)
            print(f"{p.name}: {desc}")
            results.append({"file": str(p), "desc": desc})
        except Exception as e:
            print(f"ERROR {p.name}: {e}")

    print("\n=== DB RECORDS ===\n")
    for r in records:
        print(f"{r[0]}: {r[1]}")

    # Save results for next step
    Path(r"C:\AI\Platform\MediaVault\core\screenshot_match.json").write_text(json.dumps(results, indent=2))
    print("\nSaved to core/screenshot_match.json")

if __name__ == "__main__":
    main()
