"""recipe YAML -> Cooking-for-Engineers table + timeline + nutrition.
usage: render_recipe.py recipe.yaml OUT [--widget|--page|--md|--png]
  --widget  inline fragment for the chat visualizer (default)
  --page    standalone HTML page
  --md      GitHub markdown (raw HTML table + mermaid gantt + nutrition table)
  --png     shareable image (needs wkhtmltoimage + a CJK font)
  --table-png  image with only title, summary line and the recipe table
  --en      (add to --table-png) English version, from the *_en fields in the YAML
"""
import html
import os
import subprocess
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal

import yaml

src, out = sys.argv[1], sys.argv[2]
flags = sys.argv[3:]
EN = "--en" in flags
mode = next((f for f in flags if f != "--en"), "--widget").lstrip("-")
r = yaml.safe_load(open(src, encoding="utf-8"))
ING, STEPS = r["ingredients"], r["steps"]
SERV = r.get("servings") or 1
E = html.escape

# ---------- language ----------
UNIT_EN = {"个": "", "撮": "pinch", "片": "slices", "勺": "scoop", "根": "", "瓣": "cloves"}
missing = []
def T(obj, key, where):
    """Chinese field, or its *_en twin in English mode (collects missing translations)."""
    if not EN:
        return obj.get(key, "")
    if obj.get(key) and not obj.get(key + "_en"):
        missing.append(f"{where}.{key}_en")
    return obj.get(key + "_en", "")
TITLE = T(r, "title", "recipe")
SNAME = r.get("serving_name_en", "serving") if EN else r.get("serving_name", "份")
for k, i in ING.items():
    i["_name"], i["_note"] = T(i, "name", k), T(i, "note", k)
    u = i.get("unit", "")
    i["_unit"] = (i.get("unit_en", UNIT_EN.get(u, u)) if EN else u)
for k, s in STEPS.items():
    s["_action"], s["_note"] = T(s, "action", k), T(s, "note", k)
assert not missing, "missing English: " + ", ".join(missing)
WAIT = "wait" if EN else "等待"

# ---------- checks ----------
for k, s in STEPS.items():
    s.setdefault("in", [])
    s.setdefault("after", [])
    for c in s["in"] + s["after"]:
        assert c in ING or c in STEPS, f"{k}: unknown input {c}"
    s["phase"] = s.get("phase") or ("wait" if s.get("passive") else "prep")
    assert s["phase"] in ("prep", "wait", "heat"), f"{k}: phase must be prep/wait/heat"
uses = [c for s in STEPS.values() for c in s["in"]]
dup = sorted({c for c in uses if uses.count(c) > 1})
assert not dup, f"used by more than one step (split them): {dup}"
used = set(uses)
# table = steps that consume something or are consumed; a step with neither only shows on the timeline
TREE = {k: s for k, s in STEPS.items() if s["in"] or k in used}
roots = [k for k in TREE if k not in used]
assert len(roots) == 1, f"need exactly one final step, got {roots}"
root = roots[0]
unused = [k for k in ING if k not in used]
assert not unused, f"ingredients never used: {unused}"
for k, i in ING.items():
    if "nut" in i:
        assert len(i["nut"]) == 6, f"{k}: nut needs 6 numbers [kcal,P,C,F,fiber,Na]"

# ---------- table layout ----------
# Steps sit as far right as possible (one column left of the step they feed), so a side branch
# like "heat the pan with butter" lines up under the step it runs alongside; ingredient cells and
# input-less steps start at column 0 and stretch right to meet their parent.
parent = {c: k for k, s in TREE.items() for c in s["in"]}
depth = {root: 0}
def walk(k):
    for c in TREE[k]["in"] if k in TREE else []:
        depth[c] = depth[k] + 1
        walk(c)
walk(root)
LAST = 1 + max(depth[k] for k in TREE)
col = {k: (0 if k in ING or not TREE[k]["in"] else LAST - depth[k]) for k in depth}
leaves = []
def dfs(k):
    if k in ING or not TREE[k]["in"]:
        leaves.append(k)
    else:
        for c in TREE[k]["in"]:
            dfs(c)
dfs(root)
memo = {}
def leafset(k):
    if k not in memo:
        memo[k] = [k] if (k in ING or not TREE[k]["in"]) else [l for c in TREE[k]["in"] for l in leafset(c)]
    return memo[k]

def qty(i):
    q = i.get("qty", "")
    q = int(q) if isinstance(q, float) and q.is_integer() else q
    return f"{q} {i['_unit']}".strip()

def dur(s):
    m = s.get("min")
    return "" if m is None else f"{m} min"

def textw(s, px):
    """Rough rendered width of a string: CJK glyphs are square, Latin about 0.56 em."""
    return sum(px if ord(ch) > 0x2E80 else px * 0.56 for ch in str(s))

def layout(scale, ing_px, font):
    """Physical table columns and each cell's left edge.

    Column 0 holds ingredients, sized to the longest name + quantity so names don't wrap.
    Every step column gets width scale(minutes) of its longest step. When a column holds a
    shorter step too (heat the pan 3 min under rest 7 min), the column is split into right-
    aligned sub-columns so the shorter step is drawn narrower and its input cell stretches
    to meet it, like a timeline.
    """
    lo_ing, hi_ing = ing_px
    single = [k for k in ING if col[parent[k]] == 1] or list(ING)
    need = max(textw(ING[k]["_name"], font) + textw(qty(ING[k]), font) for k in single) + 40
    widths, starts, groups = [max(lo_ing, min(hi_ing, round(need)))], {0: 0}, {}
    for c in range(1, LAST + 1):
        cum, idx = [], {}
        for d in sorted({STEPS[k].get("min") or 0 for k in TREE if col[k] == c}):
            w = scale(d)
            if cum and w - cum[-1] < 24:   # too close to be worth a separate sliver
                cum[-1] = max(cum[-1], w)
            else:
                cum.append(w)
            idx[d] = len(cum) - 1
        starts[c], groups[c] = len(widths), (len(cum), idx)
        widths += [cum[i] - cum[i - 1] for i in range(len(cum) - 1, 0, -1)] + [cum[0]]
    left = {}
    for k in depth:
        if k in ING or not TREE[k]["in"]:
            left[k] = 0
        else:
            n, idx = groups[col[k]]
            left[k] = starts[col[k]] + (n - 1 - idx[STEPS[k].get("min") or 0])
    return widths, left

IMG_SCALE = lambda d: max(96, min(200, 44 + 22 * d))
WIDGET_SCALE = lambda d: max(56, min(140, 28 + 14 * d))

def recipe_table(cls_on=True, scale=IMG_SCALE, ing_px=(150, 300), font=14, fixed=True):
    """Ingredient cell: name first, quantity right-aligned. Step cell: verb, then small note and time."""
    widths, left = layout(scale, ing_px, font)
    total_cols = len(widths)
    rows = []
    for l in leaves:
        cells, k = [], l
        while True:
            span = len(leafset(k))
            wid = (left[parent[k]] if k in parent else total_cols) - left[k]
            if k in ING:
                i = ING[k]
                note = (f'<span class="n">{E(i["_note"])}</span>' if cls_on else f'<br><sub>{E(i["_note"])}</sub>') if i["_note"] else ""
                if cls_on:
                    cells.append(f'<td class="i" colspan="{wid}"><span class="q">{E(qty(i))}</span>{E(i["_name"])}{note}</td>')
                else:
                    cells.append(f'<td colspan="{wid}">{E(i["_name"])} <b>{E(qty(i))}</b>{note}</td>')
            else:
                s = TREE[k]
                notes = [x.strip() for x in s["_note"].split("·") if x.strip()]  # one short note per line
                small = notes + [x for x in [" · ".join(x for x in [dur(s), WAIT if s.get("passive") else ""] if x)] if x]
                d = "".join((f'<span class="n">{E(x)}</span>' if cls_on else f'<br><sub>{E(x)}</sub>') for x in small)
                c = f' class="s {s["phase"]} c{col[k] % 2}"' if cls_on else ""
                cells.append(f'<td{c} rowspan="{span}" colspan="{wid}">{E(s["_action"])}{d}</td>')
            if k not in parent or leafset(parent[k])[0] != l:
                break
            k = parent[k]
        rows.append("<tr>" + "".join(cells) + "</tr>")
    cols = "".join(f'<col style="width:{w}px">' for w in widths)
    style = f' style="table-layout:fixed;width:{sum(widths)}px"' if fixed else ""
    return f'<table class="cfe"{style}><colgroup>{cols}</colgroup>' + "".join(rows) + "</table>"

# ---------- schedule ----------
# One cook: hands-on steps never overlap, in the order they are listed. Passive steps (resting,
# preheating, soaking) run alongside whatever the cook is doing.
start, end = {}, {k: 0 for k in ING}
cook_free = 0
for k, s in STEPS.items():
    m = s.get("min") or 0
    for d in s["in"] + s["after"]:
        assert d in end, f"{k}: list it after {d}"
    ready = max((end[d] for d in s["in"] + s["after"]), default=0)
    if s.get("end_with") or s.get("start_with"):
        ref = s.get("end_with") or s.get("start_with")
        assert ref in end, f"{k}: list it after {ref}"
        assert s.get("passive"), f"{k}: end_with/start_with only for passive steps (preheat, soak...)"
        start[k] = end[ref] - m if s.get("end_with") else start[ref]
        assert start[k] >= ready, f"{k}: would start before its inputs are ready"
    else:
        start[k] = ready
        if not s.get("passive"):
            start[k] = max(start[k], cook_free)
    if not s.get("passive"):
        cook_free = start[k] + m
    end[k] = start[k] + m
total = max(end.values())
order = sorted(STEPS, key=lambda k: (start[k], col.get(k, 0)))
TICK = next(t for t in (1, 2, 5, 10, 15, 30, 60) if total / t <= 8)
ticks = list(range(0, total + 1, TICK))
if ticks[-1] != total:
    if total - ticks[-1] < TICK / 2 + 0.01 and len(ticks) > 1:  # keep the end label from colliding with the last tick
        ticks.pop()
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
    kcal, prot = (fmt(nut_total[0] / SERV, 1), fmt(nut_total[1] / SERV, 1)) if has_nut else (None, None)
    if EN:
        parts = [f"~{total} min", f"{SERV} {SNAME}" if SERV > 1 else f"1 {SNAME}"]
        if has_nut:
            parts.append(f"{kcal} kcal · {prot} g protein per {SNAME.rstrip('s')}")
        return " · ".join(parts)
    parts = [f"约 {total} 分钟", f"{SERV} {SNAME}" if SERV > 1 else "1 份"]
    if has_nut:
        parts.append(f"每{SNAME} {kcal} kcal · 蛋白质 {prot} g")
    return " · ".join(parts)

# ---------- chat widget / page: borders only, no colour coding ----------
CSS = """.cfe{border-collapse:collapse;font-size:13px;line-height:1.35}
.cfe td{border:1px solid var(--line);padding:6px 10px;vertical-align:middle}
.cfe .i{word-break:break-word}
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
        cls = "bar wait" if s.get("passive") else "bar"
        out.append(f'<div class="lab">{E(s["_action"])}</div><div class="track">{grid}'
                   f'<div class="{cls}" style="left:{pct(start[k]):.2f}%;width:{max(pct(m), 1.5):.2f}%" '
                   f'title="{start[k]}–{end[k]} min"></div></div>')
    labels = "".join(f'<span class="{"first" if t == 0 else "last" if t == total else ""}" style="left:{pct(t):.2f}%">{t}</span>' for t in ticks)
    out.append(f'<div class="axl">分钟</div><div class="ax">{labels}</div>')
    return '<div class="gt">' + "".join(out) + "</div>"

# ---------- image: a warm paper card; phase colours (alternating shade per column), dark borders on every cell ----------
PH = {  # fill A, fill B (alternate columns), text, timeline bar
    "prep": ("#FAEEDA", "#F4DDB2", "#5C3A0C", "#D9952E"),
    "heat": ("#F9E6DE", "#F2CFC1", "#6B2A14", "#C9603A"),
    "wait": ("#EFEDE7", "#E2DED5", "#46423A", "#B5AFA3"),
}
INK, MUTED, LINE, HAIR = "#2B241D", "#7C7266", "#5E5448", "#EAE4D9"

def image_html(table_only=False):
    track_w = 300
    px = lambda v: round(track_w * v / total)
    grid = "".join(f'<div style="position:absolute;left:{px(t)}px;top:0;bottom:0;width:1px;background:{HAIR}"></div>' for t in ticks[1:-1])
    tl = []
    for k in order:
        s = STEPS[k]
        m = s.get("min") or 0
        bar = PH[s["phase"]][3]
        tl.append(f'<tr><td class="tl">{E(s["_action"])}</td><td class="tk"><div style="position:relative;height:30px;width:{track_w}px">{grid}'
                  f'<div style="position:absolute;left:{px(start[k])}px;width:{max(px(m), 5)}px;top:10px;height:10px;background:{bar};border-radius:2px"></div>'
                  f'</div></td></tr>')
    axis = "".join(f'<div style="position:absolute;left:{px(t) - 15}px;width:30px;text-align:center;top:4px">{t}</div>' for t in ticks)
    tl.append(f'<tr><td class="tl axl">{"min" if EN else "分钟"}</td><td><div style="position:relative;height:22px;width:{track_w}px;font-size:11px;color:{MUTED}">{axis}</div></td></tr>')
    step_css = "".join(f".cfe .{p}.c0{{background:{a};color:{t}}}.cfe .{p}.c1{{background:{b};color:{t}}}" for p, (a, b, t, _) in PH.items())
    css = f"""body{{margin:0;padding:18px;background:#EFE9DF;color:{INK};font-family:"Noto Sans CJK SC","Noto Sans SC",sans-serif;width:1200px}}
.card{{display:inline-block;background:#FFFCF6;border:1px solid #A89B88;border-radius:6px;padding:7px;-webkit-box-shadow:0 3px 14px rgba(60,42,20,.10)}}
.frame{{border:1px solid #DDD3C3;border-radius:3px;padding:26px 30px 30px}}
h1{{font-size:24px;font-weight:bold;margin:0 0 6px;letter-spacing:.5px}}
.sub{{color:{MUTED};font-size:13px;margin-bottom:20px}}
.sec{{font-size:12px;color:{MUTED};margin:28px 0 10px;letter-spacing:2px}}
.cfe{{border-collapse:collapse;font-size:14px;line-height:1.4}}
.cfe td{{border:1px solid {LINE};padding:9px 12px;vertical-align:middle}}
.cfe .i{{background:#FFFDF9;word-wrap:break-word}}
.cfe .q{{float:right;margin-left:12px;color:{MUTED};white-space:nowrap}}
.cfe .s{{text-align:center;font-weight:bold}}
{step_css}
.cfe .n{{display:block;font-size:11px;font-weight:normal;margin-top:2px;opacity:.8;white-space:nowrap}}
.cfe .i .n{{color:{MUTED};opacity:1}}
.tlt{{border-collapse:collapse;font-size:13px}}
.tlt td{{padding:0}}
.tlt .tk{{border-bottom:1px solid {HAIR}}}
.tl{{padding-right:14px !important;white-space:nowrap;border-bottom:1px solid {HAIR};color:{INK}}}
.axl{{border-bottom:none !important;font-size:11px;color:{MUTED} !important}}
.nt{{border-collapse:collapse;font-size:14px}}
.low{{border-collapse:collapse}}
.low .lo{{padding:0;vertical-align:top}}
.nt th,.nt td{{border:1px solid {LINE};padding:7px 16px;text-align:left}}
.nt th{{background:#F4EEE3;font-weight:bold}}
.nt .v{{text-align:right}}
.nt .u{{color:{MUTED};font-size:11px;margin-left:4px}}
"""
    table = recipe_table()
    head = f"<h1>{E(TITLE)}</h1><div class=\"sub\">{E(summary_line())}</div>"
    if table_only:
        body = f"{head}{table}"
    else:
        nut = f'<div class="sec">营养成分</div>{nutrition_html()}' if has_nut else ""
        lower = (f'<td class="lo"><div class="sec">时间线</div><table class="tlt">{"".join(tl)}</table></td>'
                 + (f'<td class="lo" style="padding-left:44px">{nut}</td>' if nut else ""))
        body = f'{head}{table}<table class="low"><tr>{lower}</tr></table>'
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body><div class="card"><div class="frame">{body}</div></div></body></html>'

# ---------- outputs ----------
if mode == "widget":
    vars_ = ":root{--line:var(--border-stronger);--line2:var(--border);--t2:var(--text-secondary);--t3:var(--text-muted);--fg2:var(--text-primary)}"
    summary = f'{E(TITLE)}：{len(ING)} 种材料，{len(TREE)} 个步骤，约 {total} 分钟'
    doc = (f"<style>{vars_}{CSS}</style><h2 class=\"sr-only\">{summary}</h2>"
           f'<div class="sum">{E(summary_line())}</div>'
           f'<div class="wrap">{recipe_table(scale=WIDGET_SCALE, ing_px=(110, 220), font=13)}</div>{timeline()}{nutrition_html()}')
elif mode == "page":
    vars_ = (":root{--bg:#fff;--fg:#222;--line:#555;--line2:#ddd;--t2:#666;--t3:#bbb;--fg2:#444}"
             "@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#1b1b1d;--fg:#eee;--line:#aaa;--line2:#3a3a3d;--t2:#aaa;--t3:#666;--fg2:#ddd}}")
    doc = (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f"<title>{E(TITLE)}</title><style>{vars_}body{{background:var(--bg);color:var(--fg);"
           f'font-family:-apple-system,"PingFang SC",sans-serif;margin:0;padding:16px}}{CSS}</style></head><body>'
           f"<h1 style=\"font-size:20px;margin:0 0 4px\">{E(TITLE)}</h1><div class=\"sum\">{E(summary_line())}</div>"
           f"<div class=\"wrap\">{recipe_table(scale=WIDGET_SCALE, ing_px=(110, 220), font=13)}</div>{timeline()}{nutrition_html()}</body></html>")
elif mode in ("png", "table-png"):
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(image_html(table_only=mode == "table-png"))
    subprocess.run(["wkhtmltoimage", "--quiet", "--enable-local-file-access", "--zoom", "2", "--width", "2560",
                    "--format", "png", f.name, out], check=True, stderr=subprocess.DEVNULL)
    os.unlink(f.name)
    try:  # trim unused canvas on the right/bottom, keep a margin
        from PIL import Image, ImageChops
        im = Image.open(out).convert("RGB")
        bg = Image.new("RGB", im.size, im.getpixel((0, 0)))
        box = ImageChops.difference(im, bg).getbbox()
        if box:
            im.crop((0, 0, min(im.width, box[2] + box[0]), min(im.height, box[3] + box[1]))).save(out)  # same margin all round
    except ImportError:
        pass
    doc = None
else:
    FENCE = "`" * 3
    g = [FENCE + "mermaid", "gantt", "dateFormat mm", "axisFormat %M", "todayMarker off"]
    for k in order:
        s = STEPS[k]
        g.append(f"  {s['_action']} :{'done, ' if s.get('passive') else ''}{k}, {start[k]:02d}, {s.get('min') or 0}m")
    g.append(FENCE)
    doc = (f"# {TITLE}\n\n{summary_line()}\n\n## 配方表\n\n{recipe_table(cls_on=False, fixed=False)}\n\n"
           f"## 时间线\n\n" + "\n".join(g) + "\n")
    if has_nut:
        head, rows = nutrition_rows()
        doc += "\n## 营养成分\n\n| 项目 | " + " | ".join(head) + " |\n|---|" + "---:|" * len(head) + "\n"
        doc += "".join(f"| {l}（{u}） | " + " | ".join(vals) + " |\n" for l, u, vals in rows)

if doc is not None:
    open(out, "w", encoding="utf-8").write(doc)
nut_s = f", {fmt(nut_total[0] / SERV, 1)} kcal/{SNAME}" if has_nut else ""
print(f"ok: {len(ING)} ingredients, {len(TREE)} table steps, {total} min{nut_s} -> {out}")
