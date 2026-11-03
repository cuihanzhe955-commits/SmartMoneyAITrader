# Smart Money AI Trader · 产品决策池

> 创建日期：2026-11-04  
> 性质：**新想法的候选记录，不是当前 Codex 开发指令**  
> 依据：`Smart Money AI Trader v1.0 Stable 最终实施计划书`（2026-11-03，尤其第 3、6、8、11、12 章）。以开发者本机最新源码和实际验收结果为工程事实；公开 GitHub C1 检查点不代表全部本地进度。

## 核心约定

1. **v1.0 先把已经承诺的功能做完，并完成真实执行与安全验收。** 暂不把商业销售、定价、营销或新的“赚钱功能”纳入当前开发范围。
2. **原计划书第 D 阶段本来就包含开源组件 POC。** CCXT、TA-Lib、Pydantic AI、Lightweight Charts 应按原计划审计和验证；不是今天新增加的需求，也不意味着每个都必须采用。
3. **原计划 H 阶段本来就包含策略分析和 AI 决策回放，F 阶段包含 Brain 和记忆与独立评估，G 阶段包含挑战与通知。** 可以选择第三方库帮助实现，但不能因此增加 v1.0 的功能承诺。
4. **新模块先记录、比较，再决定是否引入。** 不修改当前策略、AI 提案、风控、订单状态机、资金账本、`requirements.txt` 或实盘配置；不越过 C 阶段验收门槛。
5. **盈利是研究目标，不是已证明结果。** 回测和 Mock 通过只证明相应工程性质，不等于实盘可靠、策略正期望或 AI 增量收益。
6. **兼容与许可是基本工程要求，不代表现在要商业化。** 新依赖应核查 Windows / Python 版本、维护状态、许可证、供应链、NOTICE、锁版及回滚方式。

## A. 已在 v1.0 最终计划书中安排（维持原阶段，不额外排期）

| 编号 | 项目 | 计划书位置 | 决策 |
|---|---|---|---|
| PLAN-D-01 | [CCXT](https://github.com/ccxt/ccxt) | D；也服务于 C 实盘核心 | **已有依赖，继续按原范围核查各平台与真实订单**。不因竞品调研重写交易适配器 |
| PLAN-D-02 | [TA-Lib Python](https://github.com/TA-Lib/ta-lib-python) / [C](https://github.com/TA-Lib/ta-lib) | D | **保留优先 POC**；逐项比较 RSI/ATR/EMA 等输出、预热/NaN、Windows wheel 与原始策略结果，未经验证不得直接替换交易指标 |
| PLAN-D-03 | [Pydantic AI](https://github.com/pydantic/pydantic-ai) | D | **条件引入**；若现有结构化提案接口足够好，可明确记录“不采用”，避免为了引入而重写 |
| PLAN-D-04 | [Lightweight Charts](https://github.com/tradingview/lightweight-charts) | D、H | **复用现有前端依赖**；后续按原 UI 计划做信号标记/回放/主题与 NOTICE 检查 |
| PLAN-REF-01 | [Freqtrade](https://github.com/freqtrade/freqtrade) | 第 6 章架构参考 | **只借鉴方法，不照搬 GPL-3.0 代码** |
| PLAN-REF-02 | [Hummingbot](https://github.com/hummingbot/hummingbot) | 第 6 章架构参考 | **只参考执行器、连接器、订单生命周期设计** |
| PLAN-REF-03 | [Jesse](https://github.com/jesse-ai/jesse) | 第 6 章架构参考 | **只参考回测、显著性分析与复盘设计** |

以上不是已完成清单，阶段是否通过以真实测试和验收报告为准。

## B. 可用于已有 v1.0 功能的候选工具（不立即安装）

| 编号 | 模块 | 拟支持的既定能力 | 何时评估与限制 |
|---|---|---|---|
| IMP-01 | [QuantStats](https://github.com/ranaroussi/quantstats)（Apache-2.0） | H 阶段“策略表现分析器”、第 11 章绩效复盘 | **H 阶段评估**。须明确净值时间序列、费用口径与统计周期；不可将 24 小时样本的年化指标当作可信长期成绩 |
| IMP-02 | [ta](https://github.com/bukosabino/ta)（MIT） | D 阶段技术指标 POC 的替代实现 | **D 阶段与 TA-Lib 二选一或均不采用**；避免装两套重复指标库 |
| IMP-03 | [Hypothesis](https://github.com/HypothesisWorks/hypothesis)（MPL-2.0） | B/C/I 既有订单、风险、会计不变量的测试 | **仅作为可选测试依赖**；若能直接补强资金守恒、订单幂等、边界输入等测试可采用，不增加用户可见功能，不成为阻碍当前主线的条件 |

## C. 未来研究／下一版候选（现在不集成、不变更交易逻辑）

| 编号 | 模块或方向 | 研究价值 | 启动前置条件 |
|---|---|---|---|
| R-01 | [Optuna](https://github.com/optuna/optuna) | 离线策略参数搜索 | 先有可复现回测、成本模型、调参集/独立测试集划分；不得实时自调风险 |
| R-02 | [Pandera](https://github.com/unionai-oss/pandera) | 多源历史数据质量、Schema 检查 | 现有 CSV/行情校验确实不足且数据需求增加时再评估 |
| R-03 | [DuckDB](https://github.com/duckdb/duckdb) | 大规模历史 K 线、Parquet 分析 | 数据规模和查询需求明确后再考虑；**不取代 SQLite 交易账本** |
| R-04 | [scikit-learn](https://github.com/scikit-learn/scikit-learn) | 有标签的价格方向/概率预测研究 | 先定义标签、时点边界、校准指标和样本外收益检验 |
| R-05 | [Microsoft Qlib](https://github.com/microsoft/qlib) / [FinRL](https://github.com/AI4Finance-Foundation/FinRL) | 更复杂的 ML/RL 研究 | 先证明轻量基线必要性，再以隔离实验评估重型框架 |
| R-06 | [TradingAgents](https://github.com/TauricResearch/TradingAgents) / [AI Hedge Fund](https://github.com/virattt/ai-hedge-fund) | 多智能体、决策追踪和反馈 | 先证明单 AI 相较规则策略的增量价值；暂不直接迁移整个架构 |
| R-07 | [Backtesting.py](https://github.com/kernc/backtesting.py) / [VectorBT](https://github.com/polakowo/vectorbt) | 外部回测引擎交叉验证 | 先核查与现有引擎的重叠和实际许可（AGPL-3.0；VectorBT Commons Clause 等限制） |
| R-08 | 借鉴 Freqtrade/Jesse 的前视偏差检查、规则显著性检验、Monte Carlo、消融实验 | 检验规则与 AI 是否具有风险调整后的净收益优势 | 先形成隔离研究方案，独立样本与统一成本；研究结果不得冒充实盘成绩 |

**注：** 原计划第 8 章已要求 Brain 有/无记忆对照、Brier Score、Log Loss、净收益、最大回撤及防止未来信息泄漏；第 12 章也已有回测与样本外验证测试要求。R-08 中**重合的部分属于原定验收要求，不得被“放进未来池子”而删掉**；只把更大规模、更广泛的独立研究工具与自动化方法作为候选扩展。

## D. 候选进入正式实施时的验收清单

- 先核对是否属于原 v1.0 范围，以及现有代码是否足以完成；不能为了新增库而新增功能。
- 记录明确的版本、许可证、维护情况、依赖体积、Windows/Python 兼容性及分发条件。
- 在隔离环境做最小 POC；与原实现对照，必要时补基准数据和回归测试。
- 涉及交易指标、风险或订单时，必须验证行为差异，并且不允许悄悄改变实盘参数、订单状态或账户数据。
- 为每项候选留下“采用 / 不采用 / 延后”的原因、测试证据与可执行回滚步骤。
- 若声称更有盈利优势，需有净费用、基准、样本外、稳定性和风险指标证据；不能只展示最好的历史曲线。

## 当前决定

**继续执行 v1.0 既定 A–I 阶段计划。** 目前优先完成 C · 实盘核心验收；之后 D 阶段照计划评估 CCXT、TA-Lib、Pydantic AI 和 Lightweight Charts；F/G/H 按原计划实现 Brain、挑战、通知和分析。除计划原有验收内容外，本池研究候选**暂不进入 Codex 当前任务、不安装、不影响实盘**。

如需调整任何一项状态，应先由用户明确决定，并更新本文件和对应阶段记录。
