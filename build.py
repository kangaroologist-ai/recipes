"""Render every recipe YAML into a GitHub page (.md) and a shareable image (.png),
regenerate the index in README.md, and package the skill.

usage: python3 build.py            # all recipes + skill package
       python3 build.py --no-png   # skip images (no wkhtmltoimage available)
"""
import re
import subprocess
import sys
import zipfile
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
RENDER = ROOT / "skills/recipe-table/scripts/render_recipe.py"
RECIPES = ROOT / "recipes"
README = ROOT / "README.md"
SKILL_DIR = ROOT / "skills/recipe-table"
DIST = ROOT / "dist"


def render(src: Path, fmt: str) -> None:
    out = src.with_suffix("." + fmt)
    subprocess.run([sys.executable, str(RENDER), str(src), str(out), "--" + fmt], check=True,
                   stdout=subprocess.DEVNULL)


def one(v):  # same rounding as render_recipe.py
    return Decimal(str(v)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def index_rows():
    rows = []
    for src in sorted(RECIPES.rglob("*.yaml")):
        r = yaml.safe_load(src.read_text(encoding="utf-8"))
        serv = r.get("servings") or 1
        sname = r.get("serving_name", "份")
        ings = r["ingredients"].values()
        if all("nut" in i for i in ings):
            kcal = sum(i["nut"][0] for i in ings) / serv
            prot = sum(i["nut"][1] for i in ings) / serv
            nut = f"{one(kcal)} kcal · {one(prot)} g 蛋白质 / {sname}"
        else:
            nut = "—"
        rel = src.relative_to(ROOT).with_suffix(".md").as_posix()
        rows.append(f"| [{r['title']}]({rel}) | {src.parent.name} | {nut} |")
    return rows


def update_readme():
    text = README.read_text(encoding="utf-8")
    table = "| 菜谱 | 分类 | 每份 |\n|---|---|---|\n" + "\n".join(index_rows())
    new = re.sub(r"(<!-- index:start -->\n).*?(<!-- index:end -->)", lambda m: m.group(1) + table + "\n" + m.group(2),
                 text, flags=re.S)
    README.write_text(new, encoding="utf-8")


def package_skill():
    DIST.mkdir(exist_ok=True)
    out = DIST / "recipe-table.skill"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(SKILL_DIR.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, f.relative_to(SKILL_DIR.parent))
    return out


if __name__ == "__main__":
    fmts = ["md"] + ([] if "--no-png" in sys.argv else ["png"])
    for src in sorted(RECIPES.rglob("*.yaml")):
        for fmt in fmts:
            render(src, fmt)
        print("rendered", src.relative_to(ROOT))
    update_readme()
    print("packaged", package_skill().relative_to(ROOT))
