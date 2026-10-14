---
name: recipe-table
description: 把食谱（文字、链接、YouTube 字幕、截图）整理成 Cooking for Engineers 式配方表、时间线和营养成分表，直接在对话里显示，也能导出图片分享。用户说“做成配方表”“画成表格/甘特图”“整理这个食谱”“导出图片”、贴来一份食谱，或想比较、记录、分享自己的做法时使用，即使没提“配方表”三个字。
---

# 配方表

把一份食谱整理成 YAML，再用 `scripts/render_recipe.py` 渲染成三部分：Cooking for Engineers 式配方表（材料在左，步骤是向右合并的格子）、按依赖关系排出的时间线、每份的营养成分表。YAML 是唯一的源文件，三种输出都从它生成，所以改配方只改 YAML。

## 流程

1. **拿到原文**
   - 文字或截图：直接读。网页链接：用 WebFetch。
   - YouTube：云端抓字幕会被 YouTube 拦。先看简介里有没有配方；需要字幕时，用户电脑已连接就用浏览器打开视频读文字稿，否则请用户把“显示文字稿”的内容复制过来。

2. **写 YAML**，存到 scratchpad 的 `recipes/<slug>.yaml`。字段和规则见 `references/yaml-format.md`，第一次写之前读一遍；`assets/examples/` 里有两个完整示例可以照着改。几条容易忽略的：
   - 材料用通用名，不写品牌或型号：配方是给人看、给人分享的，品牌只是用户自己买的那一款。品牌信息需要时写进 `src`。
   - 原文没写时长就按常识估，回复里说明哪些是估的。
   - 热锅、化黄油、预热烤箱这类准备工作也要进配方表，写进用它的那一步的 `in`；它们通常标 `passive: true` 并用 `end_with` 对齐到正在等的那一步。具体写法见 `references/yaml-format.md` 规则 5。
   - 开火的步骤写 `phase: heat`，不用一直动手的步骤写 `passive: true`。

3. **填营养数据**：每个材料一个 `nut`（这份用量对应的 6 个数）。有 nutrition-logger 工具时先用 `search_food` 查用户自己的食物库，因为用户实际用的产品最准；查不到再用 `lookup_nutrition` 按用量折算。盐、泡打粉也要算钠，代糖按 0 kcal。缺任何一个 `nut` 就不出营养表，回复里说明缺哪个。

4. **渲染**（需要 PyYAML，缺就 `pip install pyyaml --break-system-packages`）：

   ```bash
   python3 <本 skill 目录>/scripts/render_recipe.py recipes/<slug>.yaml recipes/<slug>.widget --widget
   ```

   脚本会检查结构（材料没用到、被用两次、终点不止一个、顺序不对等），报错就按提示改 YAML 再跑。

5. **自查**：结构通过不等于做得出来。显示之前按真实做菜的样子过一遍，任一条不对就改 YAML 重新渲染：
   - 配方表里每个实际要做的动作都有一格，尤其是热锅、化黄油、预热这类容易漏的准备工作。
   - 时间线默认只有一个人做：两件要动手的事不会同时出现。脚本按这个规则排，如果排出来不合理，多半是 `passive` 标错了。
   - 每一步的时长和名称对得上（化黄油本身半分钟，2 分钟的是“热锅化黄油”）；预热结束正好接上要用它的那一步。

6. **显示**：读取 `.widget` 文件，把内容原样作为 `widget_code` 传给 visualizer 的 `show_widget`（第一次用前先调 `read_me`，platform 按设备选）。不要手改 HTML，样式问题改脚本，否则下次又回到旧样子。

7. **回复**：widget 外用一两句话说总时长、哪些步骤可以趁等待时做、哪些时长或营养数据是估的。表格里已有的内容不要再用文字重复。

## 其他输出

同一个命令换最后的参数：

- `--png`：分享用图片（需要 `wkhtmltoimage` 和 Noto Sans CJK 字体）。生成后先用 Read 看一眼有没有错位，再用 SendUserFile 发出去。
- `--md`：GitHub Markdown（合并格表格 + Mermaid 甘特图 + 营养表），放进 repo 用。
- `--page`：独立 HTML 页面。

## 改样式时

用户已经逐条确认过现在的样式，记录在 `references/style.md`。改 `render_recipe.py` 之前先读它，改完用 `assets/examples/` 里两个示例把 `--widget` 和 `--png` 都跑一遍，确认没破坏已确认的部分。
