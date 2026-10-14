"""recipe YAML -> Cooking-for-Engineers table + timeline + nutrition.
usage: render_recipe.py recipe.yaml OUT [--widget|--page|--md|--png]
  --widget  inline fragment for the chat visualizer (default)
  --page    standalone HTML page
  --md      GitHub markdown (raw HTML table + mermaid gantt + nutrition table)
  --png     shareable image (needs wkhtmltoimage + a CJK font)
"""
import html
import os
import subprocess
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal

import yaml

src, out = sys.argv[1], sys.argv[2]
mode = (sys.argv[3] if len(sys.argv) > 3 else "--widget").lstrip("-")
r = yaml.safe_load(open(src, encoding="utf-8"))
ING, STEPS = r["ingredients"], r["steps"]
SERV = r.get("servings") or 1
SNAME = r.get("serving_name", "份")
E = html.escape

# ---------- checks ----------
for k, s in STEPS.items():
    s.setdefault("in", [])
    s.setdefault("after", [])
    for c in s["in"] + s["after"]:
        assert c in ING or c in STEPS, f"{k}: unknown input {c}"
    s["phase"] = s.get("phase") or ("wait" if s.get("passive") else "prep")
    assert s["phase"] in ("prep", "wait", "heat"), f"{k}: phase must be prep/wait/heat"
TREE = {k: s for k, s in STEPS.items() if s["in"]}
uses = [c for s in TREE.values() for c in s["in"]]
dup = sorted({c for c in uses if uses.count(c) > 1})
assert not dup, f"used by more than one step (split them): {dup}"
used = set(uses)
roots = [k for k in TREE if k not in used]
assert len(roots) == 1, f"need exactly one final step, got {roots}"
root = roots[0]
unused = [k for k in ING if k not in used]
assert not unused, f"ingredients never used: {unused}"
for k, i in ING.items():
    if "nut" in i:
        assert len(i["nut"]) == 6, f"{k}: nut needs 6 numbers [kcal,P,C,F,fiber,Na]"

# ---------- table layout ----------
col = {k: 0 for k in ING}
def colof(k):
    if k not in col:
        col[k] = 1 + max(colof(c) for c in TREE[k]["in"])
    return col[k]
colof(root)
parent = {c: k for k, s in TREE.items() for c in s["in"]}
leaves = []
def dfs(k):
    if k in ING:
        leaves.append(k)
    else:
        for c in TREE[k]["in"]:
            dfs(c)
dfs(root)
memo = {}
def leafset(k):
    if k not in memo:
        memo[k] = [k] if k in ING else [l for c in TREE[k]["in"] for l in leafset(c)]
    return memo[k]

def qty(i):
    q = i.get("qty", "")
    q = int(q) if isinstance(q, float) and q.is_integer() else q
    return f"{q} {i.get('unit', '')}".strip()

def dur(s):
    m = s.get("min")
    return "" if m is None else f"{m} min"

def recipe_table(cls_on=True):
    """Ingredient cell: name first, quantity right-aligned. Step cell class = phase + column parity."""
    rows = []
    for l in leaves:
        cells, k = [], l
        while True:
            span, wid = len(leafset(k)), (col[parent[k]] - col[k]) if k in parent else 1
            if k in ING:
                i = ING[k]
                note = (f'<span class="n">{E(i["note"])}</span>' if cls_on else f'<br><sub>{E(i["note"])}</sub>') if i.get("note") else ""
                if cls_on:
                    cells.append(f'<td class="i" colspan="{wid}"><span class="q">{E(qty(i))}</span>{E(i["name"])}{note}</td>')
                else:
                    cells.append(f'<td colspan="{wid}">{E(i["name"])} <b>{E(qty(i))}</b>{note}</td>')
            else:
                s = TREE[k]
                d = " · ".join(x for x in [dur(s), "等待" if s.get("passive") else ""] if x)
                d = (f'<span class="n">{E(d)}</span>' if cls_on else f'<br><sub>{E(d)}</sub>') if d else ""
                c = f' class="s {s["phase"]} c{col[k] % 2}"' if cls_on else ""
                cells.append(f'<td{c} rowspan="{span}" colspan="{wid}">{E(s["action"])}{d}</td>')
            if k not in parent or leafset(parent[k])[0] != l:
                break
            k = parent[k]
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return '<table class="cfe">' + "".join(rows) + "</table>"

# ---------- schedule ----------
start, end = {}, {k: 0 for k in ING}
def endof(k):
    if k not in end:
        s = STEPS[k]
        deps = [endof(c) for c in s["in"] + s["after"]]
        if s.get("end_with"):
            start[k] = endof(s["end_with"]) - (s.get("min") or 0)
        elif s.get("start_with"):
            start[k] = endof(s["start_with"]) - (STEPS[s["start_with"]].get("min") or 0)
        else:
            start[k] = max(deps, default=0)
        end[k] = start[k] + (s.get("min") or 0)
    return end[k]
for k in STEPS:
    endof(k)
total = max(end.values())
order = sorted(STEPS, key=lambda k: (start[k], col.get(k, 0)))
TICK = next(t for t in (1, 2, 5, 10, 15, 30, 60) if total / t <= 8)
ticks = list(range(0, total + 1, TICK))
if ticks[-1] != total:
    ticks.append(total)

# ---------- nutrition ----------
NUT_LABELS = [("热量", "kcal", 1), ("蛋白质", "g", 1), ("碳水", "g", 1), ("脂肪", "g", 1), ("膳食纤维", "g", 1), ("钠", "mg", 1)]
has_nut = all("nut" in i for i in ING.values())
nut_total = [sum(i["nut"][j] for i in ING.values()) for j in range(6)] if has_nut else None

def fmt(v, d):  # round half up (Python's round() would turn 200.5 into 200)
    q = Decimal(str(v)).quantize(Decimal(1) if d == 0 else Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{q}"

def nutrition_rows():
    head = [f"每{SNAME}"] + ([f"整份（{SERV}{SNAME}）"] if SERV > 1 else [])
    rows = []
    for j, (lab, unit, d) in enumerate(NUT_LABELS):
        per = fmt(nut_total[j] / SERV, d)  # whole = shown per-serving x servings, so the columns always multiply out
        vals = [per] + ([fmt(Decimal(per) * SERV, d)] if SERV > 1 else [])
        rows.append((lab, unit, vals))
    return head, rows

def nutrition_html():
    if not has_nut:
        return ""
    head, rows = nutrition_rows()
    th = "".join(f'<th class="v">{E(h)}</th>' for h in head)
    body = "".join(f'<tr><td>{E(l)}<span class="u">{E(u)}</span></td>' + "".join(f'<td class="v">{v}</td>' for v in vals) + "</tr>"
                   for l, u, vals in rows)
    return f'<table class="nt"><tr><th></th>{th}</tr>{body}</table>'

def summary_line():
    parts = [f"约 {total} 分钟", f"{SERV} {SNAME}" if SERV > 1 else "1 份"]
    if has_nut:
        parts.append(f"每{SNAME} {fmt(nut_total[0] / SERV, 1)} kcal · 蛋白质 {fmt(nut_total[1] / SERV, 1)} g")
    return " · ".join(parts)

# ---------- chat widget / page: borders only, no colour coding ----------
CSS = """.cfe{border-collapse:collapse;font-size:13px;line-height:1.35}
.cfe td{border:1px solid var(--line);padding:6px 10px;vertical-align:middle}
.cfe .i{white-space:nowrap}
.cfe .q{float:right;margin-left:14px;color:var(--t2);font-variant-numeric:tabular-nums}
.cfe .s{text-align:center;min-width:56px}
.cfe .n{display:block;font-size:11px;color:var(--t2)}
.sum{font-size:13px;color:var(--t2);margin:0 0 10px}
.gt{display:grid;grid-template-columns:auto 1fr;font-size:13px;margin-top:20px}
.gt .lab{white-space:nowrap;color:var(--t2);padding:5px 12px 5px 0;border-bottom:0.5px solid var(--line2)}
.gt .track{position:relative;border-bottom:0.5px solid var(--line2);min-height:26px}
.gt .tick{position:absolute;top:0;bottom:0;width:0;border-left:0.5px solid var(--line2)}
.gt .bar{position:absolute;top:8px;bottom:8px;border-radius:3px;background:var(--fg2)}
.gt .bar.wait{background:var(--t3)}
.gt .axl{font-size:11px;color:var(--t2);padding-top:4px}
.gt .ax{position:relative;height:18px;font-size:11px;color:var(--t2)}
.gt .ax span{position:absolute;top:3px;transform:translateX(-50%)}
.gt .ax span.last{transform:translateX(-100%)}
.gt .ax span.first{transform:none}
.nt{border-collapse:collapse;font-size:13px;margin-top:20px}
.nt th,.nt td{border:1px solid var(--line);padding:5px 12px;text-align:left}
.nt th{font-weight:500}
.nt .v{text-align:right;font-variant-numeric:tabular-nums}
.nt .u{color:var(--t2);font-size:11px;margin-left:4px}
.wrap{overflow-x:auto}"""

def timeline():
    pct = lambda v: 100 * v / total
    grid = "".join(f'<div class="tick" style="left:{pct(t):.2f}%"></div>' for t in ticks[1:-1])
    out = []
    for k in order:
        s = STEPS[k]
        m = s.get("min") or 0
        cls = "bar wait" if s["phase"] == "wait" else "bar"
        out.append(f'<div class="lab">{E(s["action"])}</div><div class="track">{grid}'
                   f'<div class="{cls}" style="left:{pct(start[k]):.2f}%;width:{max(pct(m), 1.5):.2f}%" '
                   f'title="{start[k]}–{end[k]} min"></div></div>')
    labels = "".join(f'<span class="{"first" if t == 0 else "last" if t == total else ""}" style="left:{pct(t):.2f}%">{t}</span>' for t in ticks)
    out.append(f'<div class="axl">分钟</div><div class="ax">{labels}</div>')
    return '<div class="gt">' + "".join(out) + "</div>"

# ---------- image: phase colours (alternating shade per column), dark borders on every cell ----------
PH = {  # light fill A, light fill B (alternate columns), text, bar
    "prep": ("#FAEEDA", "#F4DDB2", "#633806", "#EF9F27"),
    "heat": ("#FAECE7", "#F3CFC2", "#712B13", "#D85A30"),
    "wait": ("#EFEEE9", "#E0DED6", "#444441", "#B4B2A9"),
}

def image_html():
    track_w, lab_w = 420, 112
    px = lambda v: round(track_w * v / total)
    grid = "".join(f'<div style="position:absolute;left:{px(t)}px;top:0;bottom:0;width:1px;background:#e3e0d6"></div>' for t in ticks[1:-1])
    tl = []
    for k in order:
        s = STEPS[k]
        m = s.get("min") or 0
        bar = PH[s["phase"]][3]
        tl.append(f'<tr><td class="tl">{E(s["action"])}</td><td class="tk"><div style="position:relative;height:30px;width:{track_w}px">{grid}'
                  f'<div style="position:absolute;left:{px(start[k])}px;width:{max(px(m), 5)}px;top:9px;height:12px;background:{bar};border-radius:3px"></div>'
                  f'</div></td></tr>')
    axis = "".join(f'<div style="position:absolute;left:{px(t) - 15}px;width:30px;text-align:center;top:4px">{t}</div>' for t in ticks)
    tl.append(f'<tr><td class="tl axl">分钟</td><td><div style="position:relative;height:22px;width:{track_w}px;font-size:11px;color:#6b6a64">{axis}</div></td></tr>')
    step_css = "".join(f".cfe .{p}.c0{{background:{a};color:{t}}}.cfe .{p}.c1{{background:{b};color:{t}}}" for p, (a, b, t, _) in PH.items())
    css = f"""body{{margin:0;padding:36px 40px;background:#fbfaf7;color:#1f1e1d;font-family:"Noto Sans CJK SC","Noto Sans SC",sans-serif;width:680px}}
h1{{font-size:26px;font-weight:bold;margin:0 0 6px;letter-spacing:1px}}
.sub{{color:#6b6a64;font-size:13px;margin-bottom:6px}}
.sec{{font-size:12px;color:#6b6a64;margin:28px 0 10px;letter-spacing:2px;border-bottom:1px solid #d9d6cc;padding-bottom:6px}}
.cfe{{border-collapse:collapse;font-size:14px}}
.cfe td{{border:1.5px solid #3d3d3a;padding:8px 12px;vertical-align:middle}}
.cfe .i{{background:#fff;white-space:nowrap}}
.cfe .q{{float:right;margin-left:18px;color:#5f5e5a}}
.cfe .s{{text-align:center;font-weight:bold}}
{step_css}
.cfe .n{{display:block;font-size:11px;font-weight:normal;margin-top:2px}}
.cfe .i .n{{color:#888780}}
.tlt{{border-collapse:collapse;font-size:13px}}
.tlt td{{padding:0}}
.tlt .tk{{border-bottom:1px solid #e3e0d6}}
.tl{{width:{lab_w}px;padding-right:12px !important;white-space:nowrap;border-bottom:1px solid #e3e0d6}}
.axl{{border-bottom:none !important;font-size:11px;color:#6b6a64}}
.nt{{border-collapse:collapse;font-size:14px}}
.nt th,.nt td{{border:1.5px solid #3d3d3a;padding:7px 16px;text-align:left}}
.nt th{{background:#F1EFE8;font-weight:bold}}
.nt .v{{text-align:right}}
.nt .u{{color:#888780;font-size:11px;margin-left:4px}}
"""
    nut = f'<div class="sec">营养成分</div>{nutrition_html()}' if has_nut else ""
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body>'
            f"<h1>{E(r['title'])}</h1><div class=\"sub\">{E(summary_line())}</div>"
            f'<div class="sec">配方</div>{recipe_table()}'
            f'<div class="sec">时间线</div><table class="tlt">{"".join(tl)}</table>'
            f'{nut}</body></html>')

# ---------- outputs ----------
if mode == "widget":
    vars_ = ":root{--line:var(--border-stronger);--line2:var(--border);--t2:var(--text-secondary);--t3:var(--text-muted);--fg2:var(--text-primary)}"
    summary = f'{E(r["title"])}：{len(ING)} 种材料，{len(TREE)} 个步骤，约 {total} 分钟'
    doc = (f"<style>{vars_}{CSS}</style><h2 class=\"sr-only\">{summary}</h2>"
           f'<div class="sum">{E(summary_line())}</div>'
           f'<div class="wrap">{recipe_table()}</div>{timeline()}{nutrition_html()}')
elif mode == "page":
    vars_ = (":root{--bg:#fff;--fg:#222;--line:#555;--line2:#ddd;--t2:#666;--t3:#bbb;--fg2:#444}"
             "@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#1b1b1d;--fg:#eee;--line:#aaa;--line2:#3a3a3d;--t2:#aaa;--t3:#666;--fg2:#ddd}}")
    doc = (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f"<title>{E(r['title'])}</title><style>{vars_}body{{background:var(--bg);color:var(--fg);"
           f'font-family:-apple-system,"PingFang SC",sans-serif;margin:0;padding:16px}}{CSS}</style></head><body>'
           f"<h1 style=\"font-size:20px;margin:0 0 4px\">{E(r['title'])}</h1><div class=\"sum\">{E(summary_line())}</div>"
           f"<div class=\"wrap\">{recipe_table()}</div>{timeline()}{nutrition_html()}</body></html>")
elif mode == "png":
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(image_html())
    subprocess.run(["wkhtmltoimage", "--quiet", "--enable-local-file-access", "--zoom", "2", "--width", "1520",
                    "--format", "png", f.name, out], check=True, stderr=subprocess.DEVNULL)
    os.unlink(f.name)
    try:  # trim unused canvas on the right/bottom, keep a margin
        from PIL import Image, ImageChops
        im = Image.open(out).convert("RGB")
        bg = Image.new("RGB", im.size, im.getpixel((0, 0)))
        box = ImageChops.difference(im, bg).getbbox()
        if box:
            im.crop((0, 0, min(im.width, box[2] + 80), min(im.height, box[3] + 72))).save(out)
    except ImportError:
        pass
    doc = None
else:
    FENCE = "`" * 3
    g = [FENCE + "mermaid", "gantt", "dateFormat mm", "axisFormat %M", "todayMarker off"]
    for k in order:
        s = STEPS[k]
        g.append(f"  {s['action']} :{'done, ' if s['phase'] == 'wait' else ''}{k}, {start[k]:02d}, {s.get('min') or 0}m")
    g.append(FENCE)
    doc = (f"# {r['title']}\n\n{summary_line()}\n\n## 配方表\n\n{recipe_table(cls_on=False)}\n\n"
           f"## 时间线\n\n" + "\n".join(g) + "\n")
    if has_nut:
        head, rows = nutrition_rows()
        doc += "\n## 营养成分\n\n| 项目 | " + " | ".join(head) + " |\n|---|" + "---:|" * len(head) + "\n"
        doc += "".join(f"| {l}（{u}） | " + " | ".join(vals) + " |\n" for l, u, vals in rows)

if doc is not None:
    open(out, "w", encoding="utf-8").write(doc)
nut_s = f", {fmt(nut_total[0] / SERV, 1)} kcal/{SNAME}" if has_nut else ""
print(f"ok: {len(ING)} ingredients, {len(TREE)} table steps, {total} min{nut_s} -> {out}")
