# Custom Research Type — LLM Slot 自动生成方案

> **版本：** v1.0 | **日期：** 2026-03-31  
> **状态：** 待开发  
> **背景：** Ethan 确认采用路线 A —— 用户填完 purpose 后，调一次 LLM 自动生成 2-3 个 intent slot（label + description + question），展示给用户确认/微调，再提交任务。

---

## 1. 当前流程 vs 新流程

### 当前流程（Custom type 的实现）

```
用户选 Custom
    ↓
填写 Research Purpose（自由文本）
    ↓
点击 "Auto-generate Dimensions"（规则匹配，非 LLM）
    ↓
_inferDimensionsFromPurpose() 按关键词硬匹配预设 dimension ID
    ↓
提交时 research_type 强制写死为 "product_purchase"
    ↓
后端用 product_purchase 的 intent preset（buy/hesitate/pass）
后端用 custom_instructions 拼接 purpose + dimension 标签注入 EVALUATION FOCUS
```

**核心问题：**
- custom type 提交后 `research_type = "product_purchase"`，intent slots 固定为 buy/hesitate/pass，与用户的实际 purpose 无关
- "Auto-generate Dimensions" 是纯关键词匹配，质量差，无 LLM 推理
- intent values 无法自定义（没有 `INTENT_PRESETS` 的 custom 分支）
- 结果报告页的 breakdown title、rate label 等都硬绑到 product_purchase

### 新流程（路线 A）

```
用户选 Custom
    ↓
填写 Research Purpose（自由文本）
    ↓
点击 "Generate Slots" → 调后端 /api/generate-slots
    ↓
LLM 生成 2-3 个 intent slot（label + description + question）
    ↓
前端渲染 slot 确认/编辑界面
    ↓
用户确认（或微调 slot 文本）
    ↓
提交时 research_type = "custom"，slots 随 task 一起传入
    ↓
后端用生成的 slots 动态构建 intent preset（走和预设完全一样的 prompt 模板）
    ↓
结果报告用 slot[0].label 作为主 rate label
```

---

## 2. Intent Slot 数据结构

每个 slot 包含三个字段（与 `INTENT_PRESETS` 现有结构对齐）：

```python
# 单个 slot
{
    "label": str,        # e.g. "Subscribe"  — 用于 intent enum value（小写化）
    "description": str,  # e.g. "Would sign up for a paid subscription"
    "question": str,     # e.g. "Would this persona subscribe?"  — 注入 PHASE 2 prompt
}

# 完整 custom preset（存在 task.metadata["custom_slots"]）
{
    "purpose": str,      # 用户原始 purpose 文本
    "slots": [           # 长度 2-3，第三个永远是 pass
        {"label": "Subscribe",  "description": "...", "question": "..."},
        {"label": "Consider",   "description": "...", "question": "..."},
        {"label": "Pass",       "description": "...", "question": "..."},
    ]
}
```

约定：
- slots[0] = 正向 intent（slot1）
- slots[1] = 中性/犹豫（slot2）  
- slots[2] = 拒绝，固定为 `{"label": "Pass", "description": "Not interested / would not engage", "question": null}`

LLM 只生成 slots[0] 和 slots[1]，slots[2] 由代码自动补充。

---

## 3. LLM Slot 生成

### 3.1 后端新增接口

**`POST /api/generate-slots`**

```
Request (JSON):
{
    "purpose": "我想了解用户对健康追踪 App 的订阅意愿",
    "profile_name": "default"  // optional, 用哪个 LLM profile
}

Response:
{
    "slots": [
        {"label": "Subscribe",  "description": "Would commit to a paid subscription plan", "question": "Would this persona subscribe to this health tracking app?"},
        {"label": "Trial",      "description": "Interested but wants a free trial first",   "question": "Would this persona try a free trial?"},
        {"label": "Pass",       "description": "Not interested in this type of app",         "question": null}
    ],
    "purpose": "我想了解用户对健康追踪 App 的订阅意愿"
}
```

失败时（LLM 超时或解析失败）返回 fallback slots（详见第 6 节）。

### 3.2 Slot 生成 Prompt 设计

**System prompt：**
```
You are a UX research assistant. Generate intent classification slots for user research.
Output ONLY valid JSON. No markdown. No explanation.
```

**User prompt：**
```
A researcher wants to study: "{purpose}"

Generate exactly 2 intent slots for this research. 
The third slot (Pass / not interested) will be added automatically.

Rules:
1. slot1 = the positive/affirmative outcome (e.g. "Buy", "Subscribe", "Share")
2. slot2 = the uncertain/consideration state (e.g. "Hesitate", "Trial first", "Consider")
3. Labels should be 1-2 words, Title Case, verb-like
4. Description should be one sentence (≤15 words), third-person
5. Question should be one sentence starting with "Would this persona..."

Output format:
{
  "slot1": {"label": "...", "description": "...", "question": "..."},
  "slot2": {"label": "...", "description": "...", "question": "..."}
}
```

**设计要点：**
- 用 JSON mode（`json_mode=True`）避免解析失败
- 温度设 0.3（低温提高稳定性）
- max_tokens = 300（足够，成本可控）
- 不要求模型返回 slot3（代码自动补充 Pass）
- prompt 明确 label 用动词风格（与预设 buy/follow/trial 一致）

---

## 4. 前端变更

### 4.1 Custom Panel UI 改动

当前 custom panel 结构：
```
[Research Purpose textarea]
[Auto-generate Dimensions button]  ← 改为 "Generate Intent Slots"
[Dimensions list]                  ← 改为 "Slot Preview / Edit"
```

新 custom panel 结构：
```
[Research Purpose textarea]
[Generate Slots button]

--- Slot Confirmation Area (hidden until generated) ---
[Slot 1 Card: editable label + description]
[Slot 2 Card: editable label + description]
[Slot 3 Card: Pass (readonly)]

[Status: "AI generated · Edit if needed"]
```

### 4.2 Slot Card 组件

每个 slot card 显示：
- label input（可编辑，1-2 词）
- description textarea（可编辑，单行）
- slot1/slot2 有删除/编辑功能，slot3（Pass）只读

生成成功后 "Generate Slots" 按钮改为 "Regenerate"。

### 4.3 状态管理变更

`_customPreset` 对象扩展：
```js
let _customPreset = {
    purpose: '',
    slots: [],            // [{label, description, question}]  ← 新增
    slotsConfirmed: false, // 用户是否已看到 slot（防止意外提交未生成的 custom）
    llmGenerated: false,
};
```

移除 `dimensions` 字段（不再需要 dimension cards 系统）。

### 4.4 表单提交变更

`buildEvalPayload()` 中 custom 分支改为：
```js
if (_selectedPreset === 'custom') {
    return {
        research_type: 'custom',
        custom_slots_json: JSON.stringify(_customPreset.slots),
        custom_purpose: _customPreset.purpose,
        evaluation_criteria: [],
        custom_instructions: '',
    };
}
```

`fd.append('research_type', ...)` 这行改为：
```js
fd.append('research_type', _selectedPreset === 'custom' ? 'custom' : _selectedPreset);
fd.append('custom_slots_json', ...);  // 仅 custom 时传
```

### 4.5 结果详情页变更

`INTENT_LABEL_CONFIG` 新增 custom 分支（动态生成，从 task.metadata 读取）：
```js
// task.metadata.custom_slots 存在时，动态构建 label config
if (researchType === 'custom' && task.metadata?.custom_slots) {
    const slots = task.metadata.custom_slots;
    intentCfg = {
        breakdownTitle: 'Intent Breakdown',
        slot1Label: slots[0]?.label || 'Yes',
        slot2Label: slots[1]?.label || 'Maybe',
        rateLabel: `${slots[0]?.label || 'Positive'} Rate`,
    };
}
```

---

## 5. 后端变更

### 5.1 新增接口 `/api/generate-slots`

在 `api/app.py` 中新增：
```python
class GenerateSlotsRequest(BaseModel):
    purpose: str
    profile_name: Optional[str] = None

@app.post("/api/generate-slots")
async def generate_slots(req: GenerateSlotsRequest):
    # 1. 获取 LLM backend（从 profile 或默认）
    # 2. 调 LLM 生成 slot1 + slot2
    # 3. 补充 slot3 = Pass
    # 4. 解析失败时返回 fallback slots
    ...
```

### 5.2 `ResearchTask` 模型变更

`core/task.py` 中 `ResearchTask` 无需改字段，`metadata` 字典负责存储 custom slots：
```python
# 提交时后端把 custom_slots_json 解析后存入 metadata
task.metadata["custom_slots"] = parsed_slots  # [{label, description, question}, ...]
task.metadata["custom_purpose"] = req.purpose
```

`research_type` 字段允许值扩展为包含 `"custom"`（字符串，无需修改 Pydantic model）。

### 5.3 `INTENT_PRESETS` 动态构建

`pipeline/output.py` 中 `build_merged_prompt()` 需要支持 `research_type="custom"` 时从 task 传入的 slots 动态构建 preset：

**方案：** `build_merged_prompt()` 新增可选参数 `custom_slots`：
```python
def build_merged_prompt(
    persona_summary: dict,
    content: str,
    scenario_context: str = "",
    language: str = "English",
    research_type: str = "product_purchase",
    custom_slots: Optional[list[dict]] = None,   # ← 新增
) -> str:
    if research_type == "custom" and custom_slots:
        intent_preset = {
            "values": [s["label"].lower() for s in custom_slots],
            "descriptions": {s["label"].lower(): s["description"] for s in custom_slots},
            "question": custom_slots[0].get("question", "How does this persona respond?"),
        }
    else:
        intent_preset = INTENT_PRESETS.get(research_type, DEFAULT_INTENT_PRESET)
    ...
```

### 5.4 Worker 传递 custom_slots

`pipeline/worker.py` 的 `_infer()` 方法从 `task.metadata` 取 custom_slots 传给 `build_merged_prompt()`：
```python
custom_slots = task.metadata.get("custom_slots") if task.metadata else None
prompt = build_merged_prompt(
    persona_summary=persona_summary,
    content=self.task.content,
    scenario_context=...,
    language=language,
    research_type=research_type,
    custom_slots=custom_slots,  # ← 新增
)
```

### 5.5 intent 校验逻辑

`worker.py` 的 intent 校验（`allowed_values` 那段）需要对 custom 类型动态构建 allowed_values：
```python
if research_type == "custom" and task.metadata.get("custom_slots"):
    allowed_values = [s["label"].lower() for s in task.metadata["custom_slots"]]
else:
    allowed_values = INTENT_PRESETS.get(research_type, DEFAULT_INTENT_PRESET)["values"]
```

### 5.6 `TaskResults.from_results()` 变更

`_SLOT1` 集合需要对 custom 类型动态补充 slot1 label。  
**方案：** `from_results()` 新增可选参数 `slot1_values: Optional[set[str]] = None`，custom 类型时从 task 的 metadata 里取 slots[0].label。

---

## 6. 边界情况处理

### 6.1 LLM 生成失败

触发条件：网络超时、LLM 返回非 JSON、JSON 结构不符合预期。

处理方案：
1. 后端 `/api/generate-slots` 捕获所有异常
2. 返回 **fallback slots**（根据 purpose 文本简单规则推断，类似现有 `_inferDimensionsFromPurpose`）
3. Response 中带 `"generated_by": "fallback"` 标识
4. 前端收到 fallback 时在 slot 区域显示一个提示：「自动生成失败，已使用默认模板，请检查后编辑」

Fallback slots（硬编码 default）：
```json
[
    {"label": "Positive", "description": "Has a favorable response to this content", "question": "Would this persona respond positively?"},
    {"label": "Neutral",  "description": "Uncertain or mixed feelings about this",   "question": "Would this persona be uncertain?"},
    {"label": "Pass",     "description": "Not interested or negative response",       "question": null}
]
```

### 6.2 用户不满意 slot，想重新生成

- "Regenerate" 按钮重新调 `/api/generate-slots`
- 用户当前编辑的内容会被覆盖，前端弹一个确认提示：「这会替换当前 slot，确认？」
- 或者提供"保留当前 + 重新生成一套作为参考"选项（可选，二期再做）

### 6.3 用户跳过 slot 生成直接提交

前端校验：`_selectedPreset === 'custom'` 时，若 `_customPreset.slots.length === 0`，提交时拦截：
> "Please generate or add intent slots before running a custom research."

### 6.4 Slot label 与 LLM 返回不匹配

Worker 校验时如果 LLM 返回的 intent value 不在 allowed_values 里，fallback 到 `allowed_values[2]`（Pass），与预设类型处理方式完全一致，无需额外逻辑。

### 6.5 Custom type 的结果报告兼容性

历史结果中 `research_type = "product_purchase"` 的 custom 任务（现有任务）报告页不受影响，继续走 product_purchase 路径。新 custom 任务靠 `research_type = "custom"` + `metadata.custom_slots` 存在来区分。

---

## 7. 改动文件清单

| 文件 | 改动类型 | 内容 |
|------|---------|------|
| `worldsense/api/app.py` | 新增接口 | `POST /api/generate-slots` + `Form` 参数新增 `custom_slots_json` |
| `worldsense/pipeline/output.py` | 功能扩展 | `build_merged_prompt()` 新增 `custom_slots` 参数；`INTENT_PRESETS` 无需改动 |
| `worldsense/pipeline/worker.py` | 小改 | `_infer()` 传入 `custom_slots`；intent 校验逻辑支持 custom |
| `worldsense/core/result.py` | 小改 | `TaskResults.from_results()` 支持自定义 slot1_values |
| `worldsense/static/app.js` | UI 改动 | `_customPreset` 结构、`generateDimensionsFromPurpose` 改为 `generateIntentSlots`、`buildEvalPayload` custom 分支、结果页 `INTENT_LABEL_CONFIG` 动态 custom 分支 |
| `worldsense/static/index.html` | UI 改动 | Custom panel：替换 dimension cards 区域为 slot confirmation 区域 |

**不需要改动：**
- `core/task.py`（metadata dict 天然支持新字段）
- `core/engine.py`（透传 task 即可）
- `persona/` 目录（与本次无关）
- `llm/` 目录（与本次无关）

---

## 8. 实现优先级建议

**Phase 1（核心路径）：**
1. `POST /api/generate-slots` 接口（含 fallback）
2. 前端 Custom panel 改成 slot 确认 UI
3. 提交时传 `custom_slots_json`
4. 后端 `build_merged_prompt()` 支持 custom_slots

**Phase 2（完善报告）：**
5. 结果详情页动态 INTENT_LABEL_CONFIG
6. `TaskResults` 支持 custom slot1_values
7. getResearchTypeLabel 支持 custom type 显示 purpose 摘要

---

*文档路径：`docs/custom-type-llm-slot-design.md`*
