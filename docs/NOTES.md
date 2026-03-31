
## 2026-03-29 Slider 样式修复

- CSS: input[type=range] 加 background gradient (默认全灰) + height:4px + border-radius
- CSS: webkit-slider-thumb 加 margin-top:-6px（thumb 16px，track 4px，偏移量=(4-16)/2=-6）
- CSS: webkit-slider-runnable-track 和 moz-range-track 改 background:transparent
- JS: 新增 updateSliderFill(el) 函数，动态设 linear-gradient 左青右灰
- JS: renderNationalityWeights + renderWeightSliders 在 init 和 input 事件调 updateSliderFill
- JS: 百分比精度修复：最后一个 active bin = 100 - sum(前面所有)，确保严格 sum=100%
echo "done"
## 2026-03-29 Slider 样式修复

- CSS: input[type=range] 加 background gradient (默认全灰) + height:4px + border-radius
- CSS: webkit-slider-thumb 加 margin-top:-6px（thumb 16px，track 4px，偏移量=(4-16)/2=-6）
- CSS: webkit-slider-runnable-track 和 moz-range-track 改 background:transparent
- JS: 新增 updateSliderFill(el) 函数，动态设 linear-gradient 左青右灰
- JS: renderNationalityWeights + renderWeightSliders 在 init 和 input 事件调 updateSliderFill
- JS: 百分比精度修复：最后一个 active bin = 100 - sum(前面所有)，确保严格 sum=100%

## 2026-03-30 模式B集成 + 语言设置

**模式B胜出，已统一采用：**
- 去掉 pipeline/worker.py 中的 Stage 1（独立 epsilon call）
- 改为单次合并 call：build_merged_prompt() 两段式（Phase 1 构想人设 → Phase 2 以该人设评估）
- merged prompt 返回 JSON 含 `epsilon` 字段 + 所有评估字段
- epsilon.py 保留，仅用于 WebUI preview（轻量展示）

**语言设置：**
- core/task.py 新增 `language` 字段（默认 English）
- api/app.py POST /api/run 接收 `language` form 参数，存入 task.metadata + task.language
- worker.py 从 task.metadata 读取 language 传入 build_merged_prompt()
- output.py _build_language_instruction(): English=全英，其他=epsilon+key字段用目标语，verbatim 用母语+附翻译
- static/index.html 语言选择器（English 默认，8种语言）
- static/app.js 表单提交时附带 language 字段

**测试通过：** 4/4 pipeline tests pass，mock simulation 正常完成，preview endpoint 正常
