import json
import re
from tqdm import tqdm
from pathlib import Path


# =========================
# CONFIG
# =========================

INPUT_FILE = "input/recipes_data.json"
OUTPUT_FILE = "output/foodwizard_recipes.json"

STOP_WORDS = {
    "cups", "cup", "tablespoon", "tablespoons",
    "teaspoon", "teaspoons", "tsp", "tbsp",
    "fresh", "dried", "large", "small", "medium",
    "low-sodium", "extra-virgin",
    "peeled", "chopped", "thinly", "sliced",
    "ground", "to", "taste", "and",
    "optional"
}


# =========================
# UTILS
# =========================

def ensure_dirs():
    Path("input").mkdir(exist_ok=True)
    Path("output").mkdir(exist_ok=True)


def safe_get(obj, key, default=None):
    return obj.get(key) if obj.get(key) is not None else default


# =========================
# INGREDIENT PROCESSING
# =========================

def split_ingredients(text: str) -> list[str]:
    if not text:
        return []
    return [line.strip() for line in text.split("\n") if line.strip()]


def normalize_ingredient(line: str) -> list[str]:
    """
    Extract ingredient entities without quantities.
    Handles 'or' cases.
    """
    line = line.lower()

    # remove numbers + fractions + punctuation
    line = re.sub(r"[0-9/½¼¾.,()]", " ", line)

    # split alternatives
    parts = line.split(" or ")

    results = []

    for part in parts:
        words = [w for w in part.split() if w not in STOP_WORDS]
        candidate = " ".join(words).strip()

        # remove leftover units
        candidate = re.sub(r"\s+", " ", candidate)

        if len(candidate) > 2:
            results.append(candidate)

    return results


# =========================
# DIRECTIONS PROCESSING
# =========================

def process_directions(text: str) -> list[str]:
    if not text:
        return []

    steps = []

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # remove "1. ", "2. " etc.
        line = re.sub(r"^\d+\.\s*", "", line)

        steps.append(line)

    return steps


# =========================
# CATEGORY + TAGS
# =========================

def extract_category_and_tags(text: str):
    if not text:
        return "main_course", []

    tags = [t.strip().lower() for t in text.split("\n") if t.strip()]

    if "sandwich" in tags:
        category = "main_course"
    elif "soup" in tags:
        category = "soup"
    elif "dessert" in tags or "cookie" in tags:
        category = "dessert"
    elif "drink" in tags or "smoothie" in tags:
        category = "drinks"
    elif "breakfast" in tags:
        category = "breakfast"
    else:
        category = "main_course"

    return category, tags


# =========================
# DIFFICULTY ESTIMATION
# =========================

def estimate_difficulty(steps_count: int) -> str:
    if steps_count <= 4:
        return "Easy"
    if steps_count <= 8:
        return "Medium"
    return "Hard"


# =========================
# NUTRITION
# =========================

def build_nutrition(recipe):
    return {
        "calories": safe_get(recipe, "calories"),
        "protein": safe_get(recipe, "protein"),
        "fat": safe_get(recipe, "fat"),
        "sodium": safe_get(recipe, "sodium")
    }


# =========================
# SINGLE RECIPE PROCESS
# =========================

def process_recipe(r: dict) -> dict:
    ingredients_raw = split_ingredients(safe_get(r, "ingredients", ""))

    normalized = set()
    for line in ingredients_raw:
        for item in normalize_ingredient(line):
            normalized.add(item)

    steps = process_directions(safe_get(r, "directions", ""))

    category, tags = extract_category_and_tags(
        safe_get(r, "categories", "")
    )

    return {
        "id": r["id"],
        "title": safe_get(r, "title", ""),

        "category": category,
        "tags": tags,

        "ingredients_raw": ingredients_raw,
        "ingredients_normalized": sorted(normalized),

        "instructions_raw": steps,

        "nutrition": build_nutrition(r),

        "meta": {
            "difficulty": estimate_difficulty(len(steps)),
            "rating": safe_get(r, "rating")
        }
    }


# =========================
# MAIN PIPELINE
# =========================

def main():
    ensure_dirs()

    print("📥 Loading recipes...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_recipes = json.load(f)

    processed = []

    print("🧠 Processing recipes...")
    for r in tqdm(raw_recipes):
        try:
            processed.append(process_recipe(r))
        except Exception as e:
            print(f"⚠️ Failed recipe id={r.get('id')}: {e}")

    print("💾 Saving output...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)

    print(f"✅ Done! Exported {len(processed)} recipes → {OUTPUT_FILE}")


# =========================
# ENTRYPOINT
# =========================

if __name__ == "__main__":
    main()