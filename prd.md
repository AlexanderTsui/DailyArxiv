# Product Requirements Document (PRD): ArXiv Daily Express

## 1. 项目概述 (Project Overview)
**项目名称**: ArXiv Daily Express (学术速递)
**核心目标**: 构建一个自动化的学术情报系统，每日从 ArXiv 抓取指定领域的最新论文，利用 LLM 进行深度摘要与趋势分析，并最终生成排版精美的 PDF 日报。
**核心价值**: 帮助研究人员从海量论文中解放出来，快速捕捉 **Motivation (痛点)**、**Method (创新点)** 以及 **Paradigm Shift (范式演变)**。

**关键说明**:
- ArXiv 并非每天都有新论文更新：因此“每日速递”默认生成的是**最近一天有更新的论文集合**（Latest Update Day），而不是强制按自然日/当天日期生成空报表。
- 日报除了“今日（报告日）精选论文 + 日趋势”外，还会在末尾追加**本周趋势**与**本月趋势**两块内容：每块均包含“一段宏观总结 + 一张关键字图”。
- 对“发表不久但迅速被广泛关注”的论文（下文称 **Spotlight**），日报需要给予特别介绍；**Spotlight 必须基于可追溯的外部客观信号**（如 Semantic Scholar），不得仅靠 LLM 主观猜测。

## 2. 用户故事 (User Stories)
- 作为一名 AI 研究员，我希望每天早上收到一份 PDF，默认包含**最近一天有更新**的我关注领域（如 LLM, Agent）的论文（可选切换为“过去 24 小时”窗口）。
- 我不希望只看摘要，我希望看到结构化的解读：这篇论文解决了什么具体痛点？用了什么核心方法？
- 我希望看到“今日趋势分析”，了解今天的论文整体上是在修补现有架构（如 Transformer）还是提出了新的方向（如 SSM/Mamba）。
- 我希望 PDF 排版清晰、美观，像一份专业的 Newsletter，支持高亮和标签显示。
- 作为用户，我希望可以**自行勾选 ArXiv 分区 (Category)** 来限定抓取范围（例如只看 `cs.CL`、`cs.AI`）。
- 作为用户，我希望可以**自行添加关键词**（可包含中英文、同义词、排除词），并由系统通过 LLM 阅读每篇论文 Abstract 判定是否相关，最终只呈现筛选后的论文。
- 作为用户，我希望能控制“每天最多输出 N 篇论文”，并看到被过滤掉的原因（例如“不相关/重复/综述/广告/非目标方向”）。

## 3. 系统架构 (System Architecture)
系统采用模块化流水线设计 (Pipeline Design)：

1.  **Harvester (数据摄取层)**: 负责调用 ArXiv API，按“分区 + 时间策略”拉取候选论文。
2.  **Filterer (相关性筛选层)**: 对满足分区与时间条件的**所有候选论文**逐篇读取 Abstract，基于用户关键词/意图进行 LLM 相关性判定与排序，输出当日精选列表。
3.  **Analyst (认知处理层 - Micro)**: 仅对**精选列表**并行处理单篇论文，提取结构化信息 (JSON)。
4.  **Editor (认知处理层 - Macro)**: 汇总所有分析结果，生成“报告日趋势 + 本周趋势 + 本月趋势 + Spotlight 特别介绍”。
5.  **Publisher (视觉渲染层)**: 基于 Jinja2 模板生成 HTML，利用 WeasyPrint 渲染为 PDF。
6.  **Archivist (历史存储层)**: 持久化每日的候选/筛选/分析结果，用于周/月趋势统计与回溯（建议 SQLite 或 JSONL）。

> 设计原则：先“广抓取 + 低成本筛选”，再“少量深度分析”。避免对大量不相关论文做昂贵的深度总结。

## 4. 技术栈规范 (Tech Stack)
- **语言**: Python 3.10+
- **数据源**: `arxiv` (Python Wrapper)
- **LLM 交互**: `openai` SDK (兼容 OpenAI/DeepSeek/Claude API)
- **模板引擎**: `jinja2`
- **PDF 渲染**: `weasyprint`
- **配置管理**: `pydantic-settings` / `.env`
- **类型检查**: `pydantic` (用于 LLM 结构化输出验证)

## 5. 数据结构定义 (Data Schema)
*开发时必须严格遵守以下 Pydantic 模型定义。*

### 5.0 趋势关键字权重 (`KeywordWeight`)
```python
class KeywordWeight(BaseModel):
    keyword: str                   # 关键字/短语（中英文均可）
    weight: float                  # 权重（用于画图，例如 0-1 或计数）
```

### 5.1 候选论文元信息 (`PaperCandidate`)
> Harvester 输出的“候选论文集合”，用于后续 LLM 相关性筛选。该阶段必须包含 Abstract，因为筛选依赖 Abstract。

```python
class PaperCandidate(BaseModel):
    id: str                        # ArXiv ID
    title_en: str                  # 英文原标题
    authors: List[str]             # 前3位作者
    url: str                       # 论文链接
    publish_date: str              # 发布日期 (ISO 8601)
    categories: List[str]          # 论文全部分区 (如 ["cs.CL", "cs.AI"])
    primary_category: str          # 主分区 (如 "cs.CL")
    abstract: str                  # 原始摘要 (英文)
```

### 5.2 LLM 相关性判定 (`RelevanceJudgement`)
> Filterer 输出。用于解释“为什么入选/为什么剔除”，同时用于排序与控制每日篇数。

```python
class RelevanceJudgement(BaseModel):
    is_relevant: bool              # 是否与用户兴趣相关
    relevance_score: int           # 0-100, 相关度
    matched_terms: List[str]       # 命中的关键词/概念（允许为同义词）
    reason_cn: str                 # 中文理由（<=80字），说明相关/不相关原因
```

### 5.3 单篇论文模型 (`PaperAnalysis`)
```python
class PaperAnalysis(BaseModel):
    id: str                  # ArXiv ID
    title_en: str            # 英文原标题
    title_cn: str            # 中文翻译标题
    authors: List[str]       # 前3位作者
    url: str                 # 论文链接
    publish_date: str        # 发布日期
    primary_category: str    # 主分区
  
    # LLM 生成字段
    motivation: str          # [痛点] 核心解决的问题 (中文, <50字)
    method: str              # [方法] 核心技术创新 (中文, <50字)
    paradigm_relation: str   # [范式] 与主流SOTA的关系 (例如: "改进了RAG的检索召回", "基于Mamba的新架构")
    score: int               # [推荐度] 1-5分，基于创新性和相关性

    # 筛选与可解释性字段
    relevance: RelevanceJudgement
```

### 5.4 周/月趋势模型 (`PeriodTrend`)
> 用于“本周趋势 / 本月趋势”。关键字图可以由 `keywords` 渲染（如词云/条形图），也可通过 `chart_path` 指向生成的图片文件。

```python
class PeriodTrend(BaseModel):
    period: str                    # "week" | "month"
    start_date: str                # ISO 8601
    end_date: str                  # ISO 8601
    summary_cn: str                # 中文宏观总结（建议 150-250 字）
    keywords: List[KeywordWeight]  # 关键字及权重（用于生成关键字图）
    chart_path: str | None         # 生成后的图片路径（可选）
```

### 5.5 广泛关注信号 (`AttentionSignal`)
> 用于识别“发表不久但被广泛关注”的论文（Spotlight）。Spotlight 的“真实性”要求：
> - `signals` 必须来自可追溯的外部数据源（至少 1 个），并记录抓取时间 `fetched_at`
> - Spotlight 不得仅使用 LLM 进行“热度臆测”；LLM 仅用于在确认 Spotlight 后生成 `intro_cn`
> - 允许多源交叉验证（例如 Semantic Scholar + OpenAlex + Papers with Code），以降低单一平台偏差

```python
class AttentionSignal(BaseModel):
    source: str                    # 例如 "semantic_scholar" / "openalex" / "pwc" / "github"
    metric: str                    # 例如 "citations_7d" / "mentions_24h" / "repo_stars" / "pwc_score"
    value: float                   # 指标数值
    fetched_at: str                # ISO 8601
```

### 5.6 Spotlight 特别介绍 (`SpotlightItem`)
```python
class SpotlightItem(BaseModel):
    paper_id: str
    attention_score: int           # 0-100 归一化热度分
    signals: List[AttentionSignal] # 组成 attention_score 的原始信号
    intro_cn: str                  # 特别介绍（中文，建议 120-200 字）
```

### 5.7 日报模型 (`DailyReport`)
```python
class DailyReport(BaseModel):
    date: str                 # 报告日：默认取“最近一天有更新的日期”，而非强制=今天
    generated_at: str          # 生成时间（ISO 8601）
    source_range_start: str    # 本期抓取的时间窗口起点（ISO 8601）
    source_range_end: str      # 本期抓取的时间窗口终点（ISO 8601）
    domain: str              # 例如 "Computer Science - AI" (或自定义兴趣域名)
    categories: List[str]    # 用户勾选的分区 (如 ["cs.CL", "cs.LG"])
    keywords: List[str]      # 用户输入的关键词
    global_trend: str        # [趋势] 今日宏观综述 (中文, ~200字)
    papers: List[PaperAnalysis]

    weekly_trend: PeriodTrend | None
    monthly_trend: PeriodTrend | None
    spotlight: List[SpotlightItem] # Spotlight 论文列表（通常 0-3 条）
```

## 6. 功能模块详情 (Functional Requirements)

### 模块 1: Harvester (爬虫)
- **输入**:
  - 用户勾选的分区列表（如 `["cs.CL", "cs.LG"]`）
  - 时间策略（默认 `latest_update_day`，可配置）
  - 时间窗口（作为 fallback；例如过去 24 小时/48 小时，可配置）
  - 最大候选数限制（如 `max_results=100`，用于控制 API 与后续筛选成本）
- **逻辑**:
  - 按分区检索（ArXiv query: `cat:cs.CL OR cat:cs.LG`）。
  - 默认策略：**最近一天更新 (latest_update_day)**  
    - 如果“过去 24h”内无结果，则按天向前回溯（如最多回溯 `lookback_days=7`），找到**最近一个有更新结果的日期**作为本期 `date`。
    - 本期只收集该日期内（00:00-23:59，按配置时区）提交/更新的论文。
  - 可选策略：固定窗口（如过去 24h/48h），用于需要严格“每天一报”的场景。
  - 提交/更新口径需配置：Submitted vs Updated（默认 Updated 更符合“最近一天更新”的语义）。
  - 去重：同一 ArXiv ID 只保留最新版本信息。
  - (可选) 轻量启发式预过滤：标题/摘要的字符串匹配，用于进一步降低 LLM 调用量（该步骤不可替代 LLM 筛选）。
- **输出**: `List[PaperCandidate]`

### 模块 2: Filterer (LLM 相关性筛选)
- **目标**: 对满足“分区 + 时间窗口”的所有候选论文逐篇读取 Abstract，判定是否与用户兴趣相关，并输出精选列表。
- **输入**:
  - `List[PaperCandidate]`
  - 用户关键词（`keywords`）与可选“兴趣描述/研究方向”短句（如“我关注 Agentic RAG、tool use、long context eval”）
  - 最大输出篇数（如 `max_selected=20`）与阈值（如 `relevance_score>=60`）
- **LLM 策略（建议默认两段式）**:
  1) **Fast 模型**：只做相关性分类 + 评分 + 理由（结构化 JSON，低 token）
  2) **Smart 模型**（可选）：对边界样本（分数在阈值附近）复核，减少误杀/漏检
- **输出**:
  - `List[PaperCandidate + RelevanceJudgement]`（全量带判定结果，便于调试与审计）
  - `List[PaperCandidate]`（最终精选集合，供 Analyst 深度分析）
- **验收标准**:
  - 对每篇候选都必须产生 `RelevanceJudgement`（包括不相关的），且 JSON 可被 Pydantic 校验
  - 输出精选集合大小满足 `<= max_selected`
  - 精选集合按 `relevance_score` 与时间排序（规则需明确）

### 模块 3: Analyst (单篇分析)
- **模型**: 用户自选，默认使用 `model_smart`（深度分析）
- **Prompt 策略**:
  - Role: 资深 AI 研究员。
  - Task: 阅读 Abstract（必要时可追加读取引言/方法段，但需明确成本与开关），提取 `PaperAnalysis` JSON。
  - **关键指令**: 
    - "Motivation 必须直击痛点，不要废话。"
    - "Method 必须包含技术关键词（如 LoRA, DPO, KV-Cache）。"
    - "Paradigm Relation 需要判断它是 Incremental (增量改进) 还是 Disruptive (颠覆性)。"
    - "score 体现创新性 + 相关性（相关性来自 Filterer 结果，可作为先验）。"

### 模块 4: Editor (趋势综述)
- **模型**: 用户自选，默认使用 `model_smart`
- **输入**: 当天所有 `PaperAnalysis` 对象的列表。
- **Prompt 策略**:
  - "作为主编，阅读今天这 20 篇论文的摘要。"
  - "总结今天的热点（例如：'今天 40% 的论文都在解决 RAG 的幻觉问题'）。"
  - "指出是否有反直觉的研究出现。"
  - "给出 Top Themes（2-5 条）与代表论文索引（可用于 PDF 高亮）。"
- **周/月趋势**（追加要求）:
  - 本周趋势：汇总最近 7 天（或最近 1 个自然周，按配置）的入选论文，输出一段宏观总结 + `keywords`（用于关键字图）。
  - 本月趋势：汇总最近 30 天（或最近 1 个自然月，按配置）的入选论文，输出一段宏观总结 + `keywords`（用于关键字图）。
  - 关键字来源建议：从 `PaperAnalysis.method/paradigm_relation` 与 Abstract 中抽取候选关键词，做聚合去重后取 Top-K（K 可配置）。

### 模块 4.1: Spotlight Detector（广泛关注识别）
- **目标**: 对“发表不久但迅速被广泛关注”的论文进行识别，并产出 `SpotlightItem` 供日报特别展示。
- **输入**:
  - 本期入选论文 `List[PaperAnalysis]`
  - 历史存储（用于“相对同龄论文”的基线比较）
  - 外部热度信号源（必须，网络可用时；推荐 Semantic Scholar）
- **输出**: `List[SpotlightItem]`
- **真实性要求（必须）**:
  - `SpotlightItem.signals` 至少包含 1 个外部来源信号
  - `attention_score` 必须由 `signals` 通过确定性规则计算得到（可配置权重），而非 LLM 直接给分
  - PDF/JSON 中需保留用于解释的关键指标（如近 7 天引用数、保存数等）
- **实现建议（推荐优先级）**:
  1) Semantic Scholar：以 `arXiv:<id>` 作为检索键，拉取引用/影响力/时间序列相关字段（以可用字段为准）
  2) OpenAlex：补充引用、被引用速度与相对同龄分位
  3) Papers with Code / GitHub：补充“工程落地关注度”（可选）

### 模块 5: Publisher (排版)
- **模板**: 使用 HTML/CSS (Flexbox/Grid)。
- **样式指南**:
  - **字体**: 正文使用衬线体 (Serif)，标题使用无衬线体 (Sans-Serif)。
  - **配色**: 
    - Motivation: 浅红背景 (`#fadbd8`)
    - Method: 浅绿背景 (`#d5f5e3`)
    - Paradigm: 灰色胶囊标签
  - **布局**: 
    - 首页: 报头 + Global Trend + Top 3 推荐论文。
    - 后续页: 双栏布局或卡片流式布局。
  - 信息展示建议：每篇论文卡片显示 `primary_category`、`relevance_score`、命中关键词、以及 `reason_cn`（可折叠）。
  - 末尾追加版块（必须）：
    - **本周趋势**：`weekly_trend.summary_cn` + 关键字图
    - **本月趋势**：`monthly_trend.summary_cn` + 关键字图
    - **Spotlight**：若存在，单独成块，展示 `intro_cn` + 论文卡片（可高亮边框/徽章）

## 7. 交互与配置 (UX & Config Requirements)
### 7.1 用户可配置项（必须）
- ArXiv 分区勾选：支持多选 `cs.*` 分区；配置可来自 `config.yaml` 或交互式 CLI 参数
- 关键词输入：支持列表输入；支持“包含词/排除词”；支持中英文混合
- 每日输出上限：`max_selected`
- 时间策略：默认 `latest_update_day`（最近一天更新）；可切换为固定窗口模式
- 回溯天数：当启用 `latest_update_day` 且当天无更新时，向前回溯的最大天数（如 7 天）

### 7.2 用户可配置项（建议）
- 相关性阈值：`relevance_threshold`，用于平衡漏检与误报
- 排序偏好：按相关度优先/按时间优先/混合
- 输出渠道：PDF 文件路径、（可选）邮件/Telegram/Notion 等（可作为 Roadmap）
- 周/月趋势：是否开启、统计窗口（最近 7/30 天 vs 自然周/月）、关键词 Top-K、图表类型（词云/条形图）
- Spotlight：是否开启、定义“发表不久”的天数阈值、热度阈值、信号源开关

## 8. 配置文件 (`config.yaml`)
```yaml
llm:
  api_key: ""
  base_url: "https://co.yes.vg/gemini" # 支持修改为第三方中转
  model_fast: "gemini-3-flash"   # 用于相关性筛选（低成本）
  model_smart: "gemini-3-flash"  # 用于单篇深度分析/趋势总结

search:
  categories:
    - "cs.CL"
    - "cs.LG"
  mode: "latest_update_day" # latest_update_day | fixed_window
  time_window_hours: 24     # fixed_window 时生效
  lookback_days: 7          # latest_update_day 时生效
  timezone: "UTC"           # 用于按日切分与报告日定义
  max_results: 100
  keywords_include:
    - "Large Language Model"
    - "Generative"
    - "Agent"
  keywords_exclude:
    - "survey"
    - "benchmark"

filter:
  relevance_threshold: 60
  max_selected: 20
  reviewer_mode: "fast_only" # fast_only | fast_then_review

trend:
  enable_weekly: true
  enable_monthly: true
  weekly_days: 7
  monthly_days: 30
  top_k_keywords: 20
  chart_type: "wordcloud" # wordcloud | bar

spotlight:
  enable: false             # Spotlight 依赖外部信号源，建议在后期实现后再开启
  recent_days: 7              # “发表不久”的定义
  attention_threshold: 70
  max_items: 2
  sources:
    - "semantic_scholar"
    # - "openalex"
    # - "pwc"
    # - "github"
```

## 9. 非功能性需求 (Non-Functional Requirements)
- **成本控制**: 默认启用“两段式”策略；支持对每日 LLM 总调用量/总 token 做上限控制（超过则降级为仅标题/关键词启发式）。
- **稳定性**: 失败重试（指数退避），超时控制；某篇论文失败不影响全局产出。
- **可观测性**: 记录当日候选数、入选数、阈值、模型名、失败数；可输出调试 JSON 供回放。
- **可解释性**: Filterer 必须为每篇候选输出 `reason_cn`，便于用户校准关键词与阈值。
- **可复现性**: 同一日同一配置可重复生成相同结果（允许 LLM 的非确定性，但应支持固定 `temperature=0` 的模式）。
- **历史数据**: 必须持久化每日结果（至少入选论文 + 分析 JSON），以支持周/月趋势的可重复生成与 Spotlight 的基线比较。

## 10. 开发路线图 (Roadmap)
1.  **Step 1 (Core)**: 完成 `Harvester` + `Filterer`，实现 CLI 输出“全量判定结果 JSON”与“精选列表 JSON”。
2.  **Step 2 (Analysis)**: 完成 `Analyst`，仅对精选列表生成 `PaperAnalysis`。
3.  **Step 3 (History)**: 加入 `Archivist`，把每日结果落盘（SQLite/JSONL），并能按时间范围读取。
4.  **Step 4 (Rendering)**: 完成 `Publisher`，调试 HTML 模板，生成 PDF（含周/月趋势与关键字图占位）。
5.  **Step 5 (Intelligence)**: 完善 `Editor`：日报趋势 + 周/月趋势；完成关键字图生成。
6.  **Step 6 (Polish)**: 优化 PDF CSS，增加错误重试/缓存/限流机制。
7.  **Step 7 (Spotlight - Hard)**: 接入 Semantic Scholar（可选补充 OpenAlex/PwC/GitHub）实现真实性 Spotlight，并补齐缓存/配额/降级策略。

## 11. 交付物 (Deliverables)
- 源代码仓库
- `requirements.txt`
- `template.html` (Jinja2 模板)
- 示例生成的 PDF 文件 (`example_report.pdf`)
