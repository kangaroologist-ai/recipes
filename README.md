# Recipes

自己做过、调过的菜谱，用 Cooking for Engineers 式配方表记录：材料在左，步骤向右合并，附时间线和营养成分。

## 菜谱

<!-- index:start -->
| 菜谱 | 分类 | 每份 |
|---|---|---|
| [高蛋白法式吐司](recipes/breakfast/protein-french-toast.md) | breakfast | 200.5 kcal · 19.8 g 蛋白质 / 片 |
| [乳清蛋白松饼(低筋粉版)](recipes/breakfast/protein-pancake-cake-flour.md) | breakfast | 347.8 kcal · 32.9 g 蛋白质 / 张 |
| [乳清蛋白松饼](recipes/breakfast/protein-pancake.md) | breakfast | 315.0 kcal · 34.6 g 蛋白质 / 份 |
<!-- index:end -->

## 目录结构

```
recipes/<分类>/<名字>.yaml   源文件，改配方只改这个
recipes/<分类>/<名字>.md     GitHub 上看的版本（自动生成）
recipes/<分类>/<名字>.png    完整图片：配方表 + 时间线 + 营养（自动生成）
recipes/<分类>/<名字>-table-zh.png / -table-en.png   只有配方表的中/英文图片（自动生成）
skills/recipe-table/         Claude skill：把食谱整理成上面的格式（示例打包时从 recipes/ 复制，见 build.py 的 EXAMPLES）
dist/recipe-table.skill      打包好的 skill（自动生成）
```

YAML 字段说明见 [skills/recipe-table/references/yaml-format.md](skills/recipe-table/references/yaml-format.md)。

## 生成

```bash
pip install pyyaml pillow      # 图片还需要 wkhtmltoimage 和 Noto Sans CJK 字体
python3 build.py               # 渲染全部菜谱、更新上面的索引、打包 skill
python3 build.py --no-png      # 没有 wkhtmltoimage 时只生成 .md
```

改了 YAML 或 skill 之后跑一次再提交，保证 .md、.png 和 .skill 跟源文件一致。
