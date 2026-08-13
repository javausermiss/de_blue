---
name: stock-analyzer
description: Use when the user asks to analyze a stock, mentions a stock code with analysis intent, or requests investment research on a specific company. Triggers on patterns like '分析XX股票', '看看XX', '研究一下XX', '分析XX', or stock codes like '300115', '00753', '000063'.
---

# Stock Analyzer (V5 Framework)

## Overview

Automated stock investment analysis using the V5 framework. Core principle: **price is the starting point, value is judgment, risk determines position size.** Good company ≠ good valuation ≠ buy. Every analysis must separate these four: company quality, valuation state, confidence level, and current action.

## Execution Mode (run end-to-end, no step-by-step confirmation)

用户说"分析 XX"即视为对完整流程的一次性授权：**从数据管道到报告产出连续执行到底**，禁止停顿询问（如"是否继续""待你确认后我再开始执行"）。

- 持仓信息未提供时按"空仓"假设处理（§7.1 直接采用空仓测试结论），不追问
- **高风险/安全操作例外：执行前必须通知用户并取得确认。** 包括：删除文件或目录（含旧数据文件、旧版报告）、覆盖已有历史报告、git 危险操作（force push / reset --hard / 删除分支 / 改写历史）、对仓库外文件的修改、首次运行未验证的新脚本。例行管道写入（`data/market/`）与新建分析报告不属于高风险，可自主执行。
- 仅在以下情况才停下来向用户报告：
  - 全部数据源失败，无法取得任何行情或财务数据
  - 用户明确要求分阶段交付
  - 即将执行的高风险/安全操作

## Workflow (multi-agent parallel, then aggregate)

### Phase 1 — Parallel launch (all at once)

主会话与三个研究子代理**同时开工**，互不等待：

**主会话：本地数据管道**（立即执行）
1. Fetch（三源 + 当日缓存）：`python fetch_market_data.py {code}` — 保存 `data/market/{code}_{date}.json`；`--force` 强制重抓（东财被封后可重试）
2. Validate：`python validate_market_data.py {code} data/market/{code}_{date}.json` — 必须 `VERIFIED`；有 error 修复或如实报告
3. Warning "东方财富失败，主数据已回退备用源"意味着 `pe`/`pb`/`market_cap`/`turnover_rate` 缺失——在报告中标"待查"或由研究代理用其他行情口径补充（标注 B 级），**禁止编造**
4. 行情数据 = 证据等级 **B**，用于 §1.1 数据字典与 §1.4 现价；`primary_source` 记录实际主源
5. 脚本或 Python 不可用时，回退网页行情（`quote.eastmoney.com/sz{code}.html`）并标"B 级待核验"

**研究代理 ×3（并行后台）**：每个代理返回**结构化事实清单**（每条 = 事实 | 数值 | 来源 | 日期 | A-D 等级），禁止输出分析结论：

**模型配置：研究代理一律使用 fast 模型**（`Agent` 工具传 `model: haiku`，当前映射 deepseek-v4-flash）——采集是体力活；主模型留给 Phase 2 锁参、Phase 3 写作与主会话组装。

| 代理 | 研究范围 |
|------|----------|
| 财务与公告 | 年报/季报财务数据、中报披露日与预告、H 股 IPO 进展、非经常损益、近期公告、审计与治理 |
| 业务与竞争 | 业务板块结构、机器人/AI 等新业务进展（出货/收入/客户/产能）、竞争格局、失败同行案例 |
| 市场与共识 | 行情与估值（价格/PE/PB/市值/52 周高低，多口径交叉）、分析师目标价与盈利预测、资金面、板块情绪 |

搜索关键词模板：`{name} {code} 财务数据 年报 季报`、`{name} 最新公告`、`{name} 行业分析 竞争 市场份额`、`{name} 研报 目标价 评级`、`{name} 机器人 AI 新业务`（按需）。

**财务代理三表科目采集清单**（§3.4 四项深度工具的数据来源；逐项采集，采不到明示"数据不足"而非编造）：

| 报表 | 科目 |
|------|------|
| 利润表 | 营业收入、营业成本与毛利率构成、销售/管理/研发/财务费用、非经常损益、净利润 |
| 资产负债表 | 应收账款+应收票据、存货、应付账款、有息负债（短/长分列）、货币资金、留存收益 |
| 现金流量表 | 销售商品提供劳务收到的现金、经营现金流、折旧摊销、资本开支 |
| 股东权益变动 | 分红、回购、股本变化 |
| 其他 | 利息支出、审计意见、会计政策变更 |

**证据分级规则**：每条事实打标 [A/B/C/D]——A=年报/季报/公告/监管文件；B=交易所行情/行业协会；C=署名研报/权威媒体/互动平台；D=推断（必须说明方法）。关键结论至少 A/B 级；仅有 C/D 级时置信度不得高于"中"。

### Phase 2 — Lock valuation parameters (main session only)

研究结果齐后，**主会话统一推导并锁定核心估值参数**，保证全文数字一致：

- 2027E 三情景 EPS（保守/基准/乐观）+ 主业/机器人分部拆解
- 合理 PE 区间与概率（合计 100%）
- 概率加权价值、安全边际、SOTP 残差市值、当前价格隐含 EPS
- 中报/下一复核日的变量阈值（CFO、机器人收入、毛利率）
- **财务质量评分卡结果**（§3.5 六维打分与 A-D 等级）+ 映射规则应用（概率调整/倍数取位/买入最低安全边际/仓位上限；偏离映射须写明理由）

写作代理**不得改动这些数字**，只能引用。

### Phase 3 — Parallel report writing

锁定参数 + 完整事实包（研究代理返回原文）同时交给两个写作代理：

- **写作代理 B（B 层）**：§2 业务事实表/因果链与断裂点/护城河与治理/失败者教训、§3 财务时间序列/三个财务结论/会计检查、§4 同业对标/市场预期与集体偏差
- **写作代理 C（C 层）**：§5 估值（仅使用锁定参数）/反向估值与敏感性、§6 风险登记表/分场景下跌应对、§7 仓位与退出/组合约束、§8 机器人/新技术附录
- **主会话**：写 §1 A 层决策摘要（四项分离/投资假说/行为偏误快检/空仓测试），组装 B/C 层成全文，写入报告文件（`{公司名}_{代码}_投资分析[_V{n}].md`）

各节最低要求（写作代理必须逐项覆盖）：

**A 层（主会话）**

| Section | Non-negotiable contents |
|---------|------------------------|
| §1.1 Data Dictionary | Ticker, currency, price date/source/grade, fiscal period, share count, valuation date, 数据管道校验结果 |
| §1.2 Company Snapshot | Type, holding period, one-line business, current stage |
| §1.3 Conclusion | **Four separate judgments**: Quality (强/中/弱), Valuation (低估/合理/偏贵), Confidence (高/中/低), Action (买/等/持/减/卖) — each with rationale |
| §1.3 Hypothesis | One sentence, falsifiable. Status: 初始/维持/上调/下调/推翻 |
| §1.4 Returns & Downside | Current price, conservative/base/optimistic value, probability-weighted value, **safety margin = (conservative − price) / price**, max drawdown, position |
| §1.5 3 Variables + 3 Risks | Each with leading indicator + threshold + next review date |
| §1.6 Behavioral Bias Check | Answer ALL 6 questions honestly. Identify the #1 psychological mistake. |

**Critical: §1.4 must show BOTH metrics separately — never conflate them:**
```
Safety margin     = (conservative value − price) / price   → measures downside protection
Probability-weighted value = Σ(scenario value × probability) → measures expected return
```

**B 层（写作代理 B）**

| Section | Non-negotiable contents |
|---------|------------------------|
| §2.1 Business Facts | What does it sell? To whom? Growth driver (volume/price/share)? Value chain position? Who captures industry profits? |
| §2.2 Causal Chain | Forward chain (3-5 links) + **reverse chain with breakpoint analysis per link**: current state → trigger → recovery difficulty |
| §2.3 Moat | Why don't customers switch? Stronger or weaker in 3-5 years? Moat rating. Governance: 3 past promises vs delivery, controller risk, "would I invest if management moved to another company?" |
| §2.4 Failure Lessons | 3 biggest industry failures → what killed them → shared vulnerability? |
| §3.1 Financial Time Series | 3-5 years + latest quarter: revenue, growth, gross margin, op margin, net profit, net margin, CFO, FCF, ROE, ROIC, receivables, inventory, capex, debt ratio |
| §3.2 Three Financial Conclusions | ① Revenue → profit? ② Profit → cash? ③ Quality improving or deteriorating? |
| §3.3 Accounting Check | Receivables/inventory vs revenue growth, CFO vs net profit, non-recurring items, goodwill, related-party transactions, audit opinion, **incremental ROIC, FCF conversion rate** |
| §3.4 四项深度财务分析 | 每项 = 标准模板表 + 红旗判定 + 结论段：杜邦分解（ΔROE 贡献分解）、利润与现金流质量（收现比/OCF 归因桥/营运资本周转天数）、三表勾稽校验（三项校验）、资产负债表质量（含收入 −20% 压力测试）；数据不足明示"数据不足，跳过" |
| §3.5 财务质量评分卡 | 六维 1-5 分打分（每维附指标+数值+年份+证据等级）→ A-D 等级；映射规则应用记录（概率调整/倍数取位/买入最低安全边际/仓位上限） |
| §4.1 Peer Comparison | 3-5 real alternatives. "Why this one instead of the best alternative?" "Is there a better替代 elsewhere?" |
| §4.2 Market Expectations | Left = observable facts, Right = inferences. Three reflexivity questions. **Seller consensus — what might they be collectively wrong about?** |

**C 层（写作代理 C）**

| Section | Non-negotiable contents |
|---------|------------------------|
| §5.1 Method Selection | 2-4 methods matching company type. **State which methods are NOT applicable and why.** |
| §5.2 Three Scenarios | Conservative/Base/Optimistic with locked inputs, probabilities (sum=100%), evidence basis |
| §5.3 Reverse Valuation | What does current price imply? Sensitivity matrix (EPS × PE). Most sensitive single input. |
| §5.4 Two Metrics | Safety margin and probability-weighted value **separately** |
| §6 Risk Register | risk/hypothesis → probability → impact → leading indicator → 🟡Watch/🟠Reduce/🔴Exit thresholds → reversibility → review frequency |
| §6.1 Scenario Decline Responses | Same -X% decline, different responses by cause: sentiment vs compression vs fundamental deterioration vs thesis break |
| §7.1 Position Status | Cost basis, P&L, % of assets, original thesis, **"Would I buy at this price if I held no position today?"** (无持仓信息按空仓假设) |
| §7.2-7.4 Entry/Exit/Constraints | Batch entry triggers, portfolio correlation, liquidity, max drawdown contribution, exit conditions |
| §8 Appendix | Robot/AI/new tech: current facts table, 5 must-verify questions, SOTP implied valuation |

### Phase 4 — Independent QA agent

1 个独立质检代理（fast 模型，`model: haiku`）通读全文，完成后返回问题清单（主会话修订后交付）：

- 20 项清单逐项核查：

| # | Check | # | Check |
|---|-------|---|-------|
| 1 | Data dictionary complete | 10 | Valuation methods match company type |
| 2 | Key conclusions have source/date/grade | 11 | Three scenarios with probabilities and sensitivity |
| 3 | Quality, valuation, confidence, action separated | 12 | Safety margin ≠ expected return (not conflated) |
| 4 | Hypothesis and its evolution traceable | 13 | Current price implications reverse-engineered |
| 5 | ≤3 core variables, each with indicator + threshold | 14 | Risk register with triggers, three-level actions, review frequency |
| 6 | Forward causal chain + reverse breakpoint chain | 15 | Position includes correlation, liquidity, drawdown constraints |
| 7 | Financial data consistent; revenue→profit→cash explained | 16 | Next action, next review date, "what facts would change conclusion" |
| 8 | Accounting quality, capital allocation, governance checked | 17 | **Behavioral bias check passed; #1 blind spot identified** |
| 9 | Peers and best alternative compared | 18 | **"Would I buy today if I held no position?" answered** |
| 19 | 四项深度工具按模板完成，各附结论段，红旗已标注 |
| 20 | 评分卡六维打分有依据，Phase 2 已按映射表应用或写明偏离理由 |

- 关键算术独立复核：概率加权价值、安全边际、毛利率/占比推导、SOTP 残差——与锁定参数核对一致

## Common Mistakes (from baseline testing)

| Mistake | Fix |
|---------|-----|
| Presenting data without evidence grade | Every number gets [A/B/C/D] |
| Mixing facts with assumptions | State "this is a D-grade inference" explicitly |
| Skipping behavioral bias check (§1.6) | It's mandatory — do it before writing the conclusion |
| Conflating safety margin with expected return | Show both, label both, explain the difference |
| Listing risks without triggers | Every risk needs 🟡/🟠/🔴 thresholds |
| Not asking "would I buy today if empty?" | §7.1 is required even for first-time analysis |
| Using DCF without justification | DCF is invalid for high-uncertainty businesses; state why you're not using it |
| Omitting reverse causality chain | §2.2 must include breakpoint analysis per link |
| No confidence level stated | Always state 高/中/低 with reason |
| Treating price decline from peak as "cheap" | Anchoring bias — check §1.6 before concluding |
| Writing agents inventing valuation numbers | Only Phase 2 locked parameters may be used; flag any mismatch to main session |
| Depth tools filled without conclusion paragraphs | §3.4 每项工具的结论段是必写项（QA 19 逐项检查） |
| Scorecard without evidence or not carried into Phase 2 | 每维必须附指标+数值+年份+证据等级；锁参必须引用评分卡并应用映射表，偏离写明理由 |

## Disclaimer

Every analysis must include at the top: "本报告用于研究与决策辅助，不构成证券投资建议。行情数据应在下单前以交易所实时行情复核。"
