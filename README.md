# DailyArxiv — ArXiv Daily Express

按 `prd.md` 落地的“学术速递”流水线：抓取 ArXiv → LLM 相关性筛选 → LLM 单篇结构化解读 → 日/周/月趋势 → 输出 **HTML + PDF**。

## 功能概览
- **默认按最近一天更新**（`latest_update_day`）：ArXiv 当天没更新时不会生成空报表。
- **用户可配置**：分区（category）多选、关键词 include/exclude、每日最多输出 N 篇。
- **LLM 筛选 + 深度解读**：先按摘要相关性筛选，再对入选论文生成结构化字段（Motivation/Method/Paradigm/Score）。
- **周/月趋势**：末尾追加“本周趋势/本月趋势”（一段总结 + 关键字图）。
- **双输出**：同一份数据生成 `report.html` 与 `report.pdf`（WeasyPrint）。
- **Spotlight（真实性热度）**：接口已预留，默认关闭（后续接 Semantic Scholar 等外部信号源）。

## 环境与安装（推荐 Conda）
### 1) 创建环境
```bash
conda create -n dailyarxiv python=3.10 -y
conda activate dailyarxiv
```

### 2) 安装 PDF 依赖（Windows 推荐）
WeasyPrint 在 Windows 上通常建议用 conda-forge 安装其系统依赖：
```bash
conda install -c conda-forge weasyprint -y
```

### 3) 安装项目（可编辑模式）
```bash
pip install -e ".[dev]"
```

> 如你不需要跑单测，可用 `pip install -e .`。

## 配置
编辑 `config.yaml`，重点是 LLM：
- `llm.base_url`: 例如 `https://co.yes.vg/gemini`
- `llm.model_fast/model_smart`: 例如 `gemini-3-flash`
- API Key **不要写进仓库**，建议用环境变量提供：
  - `GEMINI_API_KEY`（优先）
  - 或 `OPENAI_API_KEY`（兼容变量名）

示例（仅示意，不要把真实 key 写进文件）：
```yaml
llm:
  api_key: ""
  base_url: "https://co.yes.vg/gemini"
  model_fast: "gemini-3-flash"
  model_smart: "gemini-3-flash"
  temperature: 0
```

## 使用方法
### 1) 生成日报（HTML + PDF）
```bash
dailyarxiv run --config config.yaml --out-dir reports
```

输出目录：`reports/<report_date>/`
- `daily_report.json`：结构化结果（最重要）
- `report.html`：HTML 版日报
- `report.pdf`：PDF 版日报（WeasyPrint 可用时生成）
- `debug_candidates.json`：候选与筛选信息（用于调参/审计）

### 2) Dry-run（只抓取，不调用 LLM）
```bash
dailyarxiv run --config config.yaml --out-dir reports --dry-run
```

### 3) 仅渲染（不重新调用 LLM）
```bash
dailyarxiv render --input reports/<report_date>/daily_report.json --out-dir reports/<report_date>
```

### 4) 查看/导出 SQLite 归档
默认归档库在项目根目录：`dailyarxiv.sqlite`
```bash
dailyarxiv db --db dailyarxiv.sqlite stats --days 30
```

导出某天的日报 JSON（建议用 `--out`，避免某些终端编码问题）：
```bash
dailyarxiv db --db dailyarxiv.sqlite export --date 2026-02-18 --format json --out exported_report.json
```

## 重要说明
- 当 `search.keywords_include` 为空时：系统会默认将候选视为相关，并按最新时间选取 `max_selected` 篇，避免“无关键词导致全被过滤”。
- Spotlight 需要外部客观信号源保证真实性，当前默认关闭（见 `config.yaml:spotlight.enable`）。

## Troubleshooting
- **PDF 没生成**：先确认环境里能 import `weasyprint`；Windows 建议用 `conda-forge` 安装（见上文）。
- **LLM 调用超时**：已内置重试；仍失败可降低 `max_results`/`max_selected` 或换更快模型。
- **模型名不匹配**：如果你的 Gemini 网关实际模型名是 `gemini-3-flash-preview`，项目内部已对 `gemini-3-flash` 做了别名映射。
