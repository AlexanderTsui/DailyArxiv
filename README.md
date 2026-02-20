# DailyArxiv — ArXiv Daily Express

按 `prd.md` 落地的“学术速递”流水线：抓取 ArXiv → LLM 相关性筛选 → LLM 单篇结构化解读 → 周/月趋势总结 → 输出 **HTML + PDF**，并可归档到 SQLite。另提供本地 Web GUI（Streamlit）。

## 功能概览
- **默认取最近一次更新日**：ArXiv 并非每天更新，因此默认模式会选择“最近一天有更新的论文”来生成日报。
- **分区 + 关键词筛选**：用户可多选 ArXiv 分区（categories），并可填写 include/exclude 关键词。
- **LLM 筛选与解读**：对满足“分区 + 时间”的候选论文逐篇读取摘要，LLM 判定是否相关；最终展示的单篇论文是 LLM 筛选后的结果，并附结构化解读字段。
- **周/月趋势**：在日报末尾附加“本周趋势 + 本月趋势”（各 1 段总结 + 关键词图）。
- **双产物**：同一份数据输出 `report.html` 与 `report.pdf`（PDF 通过 WeasyPrint，若不可用则跳过）。
- **Spotlight（计划项）**：对“发表不久但广泛关注”的文章做特别介绍；为保证真实性，后续将接入 Semantic Scholar 等外部信号源（目前默认关闭）。

## 环境安装（Conda 推荐：`arxivdaily`）
```bash
conda create -n arxivdaily python=3.10 -y
conda activate arxivdaily
```

### 安装依赖
开发/GUI：
```bash
pip install -e ".[dev,gui]"
```

PDF（Windows 推荐 conda-forge 安装 WeasyPrint 及系统依赖）：
```bash
conda install -c conda-forge weasyprint -y
```

## 配置与密钥
编辑 `config.yaml`（参考 `config.example.yaml`）。

LLM（本项目支持 Gemini 网关，**不是 OpenAI 协议**也可以用）：
- `llm.base_url`: 例如 `https://co.yes.vg/gemini`
- `llm.model_fast/model_smart`: 例如 `gemini-3-flash`
- API Key：不要写进仓库，建议用环境变量提供
  - `GEMINI_API_KEY`（优先）
  - 或 `OPENAI_API_KEY`（兼容变量名）

PowerShell 示例：
```powershell
$env:GEMINI_API_KEY="YOUR_KEY"
```

## CLI 使用
生成日报（HTML + PDF）：
```bash
dailyarxiv run --config config.yaml --out-dir reports
```

输出目录：`reports/<report_date>/`
- `daily_report.json`：结构化结果（最重要）
- `report.html`：HTML 版日报
- `report.pdf`：PDF 版日报（WeasyPrint 可用时生成）
- `debug_candidates.json`：候选与筛选信息（用于调参/审计）

仅抓取不调用 LLM：
```bash
dailyarxiv run --config config.yaml --out-dir reports --dry-run
```

仅渲染（不重新调用 LLM）：
```bash
dailyarxiv render --input reports/<report_date>/daily_report.json --out-dir reports/<report_date>
```

SQLite 归档（默认库：`dailyarxiv.sqlite`）：
```bash
dailyarxiv db --db dailyarxiv.sqlite stats --days 30
dailyarxiv db --db dailyarxiv.sqlite export --date 2026-02-18 --format json --out exported_report.json
```

## GUI（Streamlit）
启动：
```bash
dailyarxiv-gui
```
或：
```bash
python -m streamlit run dailyarxiv/gui/app.py
```

GUI 特性：
- 生成报告时实时输出日志、进度条、自动刷新（可在侧边栏调整刷新频率）。
- 当 `report.html` 出现后提供 “Live HTML preview” 以便边跑边看。
- 支持 **中/英双语切换**（侧边栏 Language）。

## Troubleshooting
- **PDF 没生成**：先确认 `weasyprint` 可 import；Windows 建议用 `conda-forge` 安装（见上文）。
- **LLM 调用超时/失败**：可降低 `max_results` / `max_selected`，或重试；Gemini 网关已内置重试与较长超时。

