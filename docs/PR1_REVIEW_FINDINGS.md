# PR #1 与全仓只读代码审查：问题台账

> 日期：2026-11-07  
> 仓库：cuihanzhe955-commits/SmartMoneyAITrader  
> PR：[ #1 G1 自动预测挑战、断点恢复与统计 ](https://github.com/cuihanzhe955-commits/SmartMoneyAITrader/pull/1)  
> 被审查的 PR 原始 HEAD：**8b94bae636072a52a0aec63197becf46da95a43a**  
> 被审查的 main 基线：**234d8335c6c3240bf654f280de3c9c3ccf89df85**  
> 审查方式：GitHub 源码、Diff、历史报告及测试代码的**只读静态核查**；没有在本轮重新执行 Windows 测试、浏览器测试、真实 API 或数据库迁移。  
> 本文件**仅记录问题，不表示问题已修复、重新验收或获得合并批准**。本次审查文件提交产生的新 HEAD 仅用于保存审查结果，G1 业务代码基线仍是上述原始 SHA。

## 0. 结论与保全要求

**结论：暂缓合并 PR #1。** 现存至少 1 项 P1 阻断问题、2 项 P2 逻辑/验收问题，另有多个需要专门测试或证据核实的风险。本次没有证据表明这些问题已被修复。PR 仍为 Draft；无 GitHub Actions 执行记录；Codex 的 840 通过 / 0 失败来自其在 Windows 的历史验收报告，不是本轮独立复跑结果。

保全规则（必须执行）：

1. 不删除、重置、rebase、force-push 或覆盖 G1 分支的原始提交及 25 个变更文件；不得直接修改 main。
2. 不触碰任何真实用户 runtime 数据库、历史记录、私钥、API Key、账户和交易权限；不运行真实资金交易。
3. 不移动或覆盖独立的 **ai/codex/g2-outbox-checkpoint** 分支。G2 的异步通知研究仍是另一条独立工作线。
4. 后续修复须另有明确任务授权，保持逐问题修复、逐测试验证和独立提交；本次审查报告写入不是修复动作。
5. 恢复 Codex/Copilot 时先读取本文件、主计划、进度文档和现有 PR 评论，不重新从零实现 G1。
6. 新增审查报告是**附加历史记录**，不得为了令 SOURCE_MANIFEST 的历史记录看起来一致而重新生成/覆盖原先源码快照。后续正式打包时再评估是否将本报告列入文档白名单。

### 审查证据层级

- **已确认（源码推导）**：当前代码可直接推出存在确定性的状态或调度缺陷，但尚未在本轮动态复现。
- **证据缺口**：历史自动测试缺失指定场景、或仅有旧报告，不能据此声称已通过。
- **待验证风险**：静态阅读发现竞态、兼容或安全疑点，尚无充分证据证明在实际运行中可触发。
- 所有“建议”均不是已实施变更；风险分级是本次审查判断，不是发布验收认证。

## 1. 需要修复的 PR 问题

### PR1-001 · P1 阻断 · 官方结果早于预测完成导致永久 WAITING / STOPPING

- **状态**：已确认（源码路径推导），未修复。
- **证据**：events/lab.py 约第 285–287 行，settle 对官方 resolved_at 不晚于 decision_at 抛出 ValueError；同文件 tick 异常分支约第 356–374 行只将 WAITING 延迟 60 秒重试。challenge/prediction.py 第 70–89、119–145、177–186 行仅以概率及 decision_at < expires_at 判定有效预测，WAITING 仍属 pending。tests/test_prediction_challenge.py 约第 278 行后的早结果测试只断言没有计入 settled/valid_completed。
- **影响**：同一已核验且时间固定的早结果被无限请求；挑战无法推进目标轮次，STOPPING 可能无法结束。若此轮已有参考 DEBIT，现金长期占用，不能随意将记录标为 FAILED 而忽略对账。
- **复现条件**：模型返回预测后，官方结果的 resolved_at <= decision_at；先进入 WAITING，再触发 settle；随后命令 stop 并继续 tick 多轮。
- **建议修复/验收标准**：为确定性无效结算定义终态（与暂时 API 故障严格区分）；账本若有 DEBIT 应采用可追踪的 VOID/REFUND 或等价幂等更正，不改写历史记录；完成后 stats 不误计有效样本、reference cash/reconcile 均一致；STOPPING 最终可停止，重启后仍不重试该无效结果。增补上述组合测试并复跑 F 兼容测试。
- **已有 GitHub 审查定位**：https://github.com/cuihanzhe955-commits/SmartMoneyAITrader/pull/1/files

### PR1-002 · P2 重要 · 50 个旧暂停挑战可饿死新挑战

- **状态**：已确认（调度查询逻辑），未修复。
- **证据**：challenge/prediction.py 第 220 行查询所有非 COMPLETED/STOPPED，按 rowid 升序 LIMIT 50，包含 PAUSED；create 的唯一活动挑战限制不禁止累计旧 PAUSED 挑战。
- **影响**：较早的 50 个 PAUSED / 需要人工恢复记录一直占据扫描窗口，新的 ACTIVE 或 INITIALIZING 无机会被 _advance 处理；新挑战在 UI 中可能永远没有进度。
- **复现条件**：使用隔离库预置 50 条较早 PAUSED 挑战，再创建一条新的 ACTIVE / INITIALIZING；重复执行 tick。
- **建议修复/验收标准**：按可调度状态和到期时间选取、确保公平性；暂停记录允许查阅但不永久阻塞活动挑战；测试至少覆盖 50+ 历史暂停记录和调度器重启。
- **已有 GitHub 审查定位**：https://github.com/cuihanzhe955-commits/SmartMoneyAITrader/pull/1/files

### PR1-003 · P2 重要 · 完整进程重启与旧 F 数据迁移证据不足

- **状态**：证据缺口，未验收。
- **证据**：tests/test_prediction_challenge.py 第 50–60 行的 100 轮测试在第 50 轮只重新创建 PredictionChallenges 管理器，复用原 EventLab、Brain 与进程；预约恢复测试同样复用原对象。challenge/prediction.py 第 25–33 行使用 CREATE TABLE IF NOT EXISTS 增量创建新表；events/lab.py 启动时重排 FETCHING → QUEUED。
- **影响**：无法据此证明 Windows 服务崩溃/恢复时，旧 F 的 session、round、cash 数据以及 G1 预约、处理中、等待结算的所有状态能原样恢复且不重复扣费/结算。
- **复现/验收**：在仅含旧 F 表/旧字段/真实格式合成历史行的临时 SQLite 文件中写入会话与 cash；关掉所有服务和连接，启动一个新进程重新打开**同一文件**，重建 Brain、EventLab、PredictionChallenges 和启动生命周期；分别覆盖 RESERVED、QUEUED、FETCHING、PREDICTING、WAITING、SETTLED、STOPPING；逐项确认迁移不丢失旧记录、不重复 reference DEBIT/PAYOUT、不重复排队、可完成断点恢复。用户原运行库不得用作测试输入。
- **现状边界**：历史报告宣称 840/0 和重启恢复，但本条特定场景**没有独立测试证据**；不能把 840 当成全进程迁移验收。

### PR1-004 · P2 待验证 · 停止时后台线程可能仍在运行

- **状态**：待验证风险，不作为已复现漏洞宣称。
- **证据**：challenge/prediction.py 第 246–253 行 start 后启动 daemon thread，close 通过 stop 标志和 join(timeout=.2) 后立即关闭 discovery；events/lab.py 第 376–388 行采用类似短 join；terminal/api.py lifespan 先关闭 EventLab 及 details，再关闭 Runtime 的数据库。
- **风险**：如果发现/结算的外部请求未及时结束，旧 daemon 工作线程可能在资源关闭后才返回；快速重复创建应用实例、同进程热重启时需验证不会发生迟到写入、连接关闭竞态或重复调度。
- **建议验收**：在隔离环境注入卡住且可释放的网络调用，测试 close/重开/撤销/中断，核对线程存活、资源关闭顺序、数据库写入与幂等。不要仅因 join(.2) 就断言已泄漏；必须动态验证。

### PR1-005 · P3 统计口径与对账显示需补充边界测试

- **状态**：测试和语义核查建议；正常 Mock 结算路径未发现独立的算术性 P1 问题。
- **证据**：challenge/prediction.py 第 95–117 行 stats 定义 predicted=所有 valid_prediction（可包含未结算）、participated=存在参考 order、completed=已 SETTLED 且有效、accuracy 仅统计二元且概率不等于 0.5、胜率只按已结算的参考参与轮次；max_cost_basis_drawdown_pct 按已结算损益累加，并非实时市值回撤。测试验证了 100 轮 50% Mock、SKIP、失败等正常场景。
- **建议验收**：补充有已占用参考资金、浮动未决订单、部分/非二元兑付、概率恰好 0.5、结果先于预测时间、人工终止和恢复的组合数据；验证每项分子/分母、未知值使用 null 而不是 0、成本基础回撤不被标为真实最大回撤。UI/导出要明确“模拟参考收益，不是市场交易业绩”。

### PR1-006 · P2 验收缺口 · 当前提交无自动 CI 门禁

- **状态**：证据缺口。
- **证据**：GitHub PR 对原始提交没有 check runs/status checks；本轮查看 Actions 没有 workflow 运行记录。docs/G_TEST_RESULTS.json 与 docs/G1_TASK_HANDOFF.md 记录 Windows 11、Python 3.12.2、Node 24.22.2 的 840 个离线测试、定向测试、打包、前端和浏览器结果，但这些是此前 Codex 交付报告。
- **影响**：不能从 GitHub 独立确认审查时的 HEAD 已在干净环境复现该结果；PR 后续修复更不能沿用旧测试数量。
- **建议验收**：为 PR 设置不读取任何真实密钥的隔离 CI：Python 指定锁定依赖、离线全量回归、前端类型检查与构建、数据库迁移/恢复用例、包白名单检查；浏览器专项可另设 Windows 或受控 runner。若暂不配置 CI，则在干净 Windows 环境手动复跑并附原始日志与 SHA，明确标注为手动证据。

## 2. 整个仓库发现或需追踪的事项

### REPO-001 · P1 产品验收门槛 · 真实账户/真实资金仍未通过

- **状态**：已确认的产品验收缺口，不等于已经存在真实资金安全事故。
- **证据**：主计划与 docs/LIVE_TRADING_VERIFICATION.md、SOURCE_MANIFEST.json、docs/RELEASE_READINESS.md 均区分离线/模拟与外部账户验收；G1 view 和 API 明确 execution_enabled=false、environment=reference_paper；没有把 G1 连接到真实订单 API 的证据。
- **要求**：继续锁定真实资金权限，E 的多平台仅有非资金验收；Gate 事件接口不可用普通现货/永续接口替代。任何 Stable 声明必须以单独授权及真实平台/产品验收为前提。当前不得为了审查触发实盘测试。

### REPO-002 · P2 待验证 · 本地 API 暴露边界需要安全测试

- **状态**：待验证风险，不宣称已发现远程可利用漏洞。
- **证据**：terminal/api.py 提供多个 POST 控制路由，包括挑战创建/命令、AI 设置、账户/保护相关操作；server.py 和 Windows 启动说明设计为回环地址服务。当前审查没有看到完整的 Host/Origin/CSRF/反向代理暴露威胁建模和自动化验收报告。
- **风险与建议**：在保持 loopback-only 前提下验证 Host/Origin、跨站表单、错误 CORS 配置与意外暴露到局域网/公网时是否能 fail closed；对影响账户/保护的敏感端点做更严格本地来源约束。任何远程部署均应另做认证及权限审查。不要将条件性风险表述成已经可以远程访问。

### REPO-003 · P2 工程流程缺口 · G1 合并前仍缺自动化门禁和独立重启矩阵

- **状态**：与 PR1-003 / PR1-006 相关的跨模块质量门槛。
- **证据**：仓库已有大量 tests、阶段报告和人工回归记录，仍未在当前 PR 发现 GitHub Actions 检查结果；测试证据与具体提交、系统、数据集的对应关系须持续维护。
- **建议**：按 docs/AI_DEVELOPMENT_COLLABORATION.md 建立 CI/手动复验合同，禁止在分支合并前将报告中的通过数自动继承到更新后的代码。

### REPO-004 · P2 待验证 · 非资金功能不等于外部市场完整可用

- **状态**：依赖外部服务的待验收限制。
- **证据**：E 阶段公开市场报告记录过 Binance 地区访问限制、Gate 行情源时间不满足准入等情况；F/G1 只读发现及参考账本仍未证明 100 轮真实公开市场顺利自动完成，未证明持续 AI provider 预算/失败回退闭环。
- **建议**：对 HTTP 451/429、时间戳缺失、市场提前结算、市场元数据变化和网络断开分别做模拟故障注入；不得绕过地区或账户资格限制。保持“Model Mock 100轮通过”与“100轮真实市场观察验证”分别展示。

### REPO-005 · P3 打包文档同步 · 新审查报告尚未纳入快照白名单

- **状态**：已知设计结果，不是本次必须修改的缺陷。
- **证据**：scripts/build_source_package.py 中 DOCS 是显式允许集合；本次新增 docs/PR1_REVIEW_FINDINGS.md，按当前白名单不会自动进入源发行快照；SOURCE_MANIFEST.json 是既有代码检查点的快照清单。
- **建议**：后续正式打包时由单独任务核对文档准入、依赖/许可证、快照校验以及审查报告保留策略。本次严格遵守只写审查文件，不修改打包脚本、manifest 或其他文档。

### REPO-006 · P3 环境兼容与依赖审计应随发布重新核验

- **状态**：工程复验建议，非新发现依赖漏洞。
- **证据**：项目按 Windows 目标环境、固定 Python 依赖、Node/Vite 前端构建及历史浏览器测试推进；docs/DEPENDENCY_AUDIT.json 的公开公告结果属于以前的审查时点，不是未来所有版本的安全认证。
- **建议**：最终发布前使用锁定环境重新运行 pip/npm 依赖许可与公告审查、干净 Windows 安装/升级/回滚及启动脚本测试。

### REPO-007 · P2 协作风险 · G2 分支需继续独立保全

- **状态**：已确认 GitHub 存在单独的 ai/codex/g2-outbox-checkpoint 分支；不是 PR #1 的提交内容。
- **证据**：仓库分支列表还存在 main 与 G1 head。G2 属于独立 checkpoint。
- **建议**：不得把 G2 的通知 outbox 代码视为已合并或已验收；G1 修复和评审不得覆盖 G2，后续单独比对与提 PR，避免两个 AI 在同一分支或文件并发写入。

## 3. PR #1 的 25 个原始文件覆盖清单

下表登记已检查的 PR Diff 范围，便于后续逐文件复查。**登记不表示已在真实环境执行每个文件。**

| # | 文件 | 检查主题 |
|---:|---|---|
| 1 | README.md | 项目状态和 G1 功能声明 |
| 2 | SOURCE_MANIFEST.json | 版本、快照、Stable/真实资金标志 |
| 3 | challenge/prediction.py | 持久预约、状态机、统计、调度、公平性、线程 |
| 4 | docs/G1_TASK_HANDOFF.md | 交接 SHA、测试和保全约束 |
| 5 | docs/G_TEST_RESULTS.json | 840/0 报告与测试范围真实性边界 |
| 6 | docs/PHASE_G1_CHALLENGE.md | 本轮目标、范围与剩余事项 |
| 7 | docs/POLYMARKET_RESEARCH.md | F/G 平台假设与真实只读边界 |
| 8 | docs/PROGRESS_STATUS.md | G1 阶段进度不冒充 Stable |
| 9 | docs/README.md | 文档目录链接 |
| 10 | docs/RELEASE_READINESS.md | 发布阻塞项 |
| 11 | docs/SmartMoney_Stable_Plan.md | 主需求与执行范围不冲突 |
| 12 | docs/TEST_REPORT.md | 测试报告的时间与口径 |
| 13 | docs/V1_ROADMAP.md | G1/G2/H/I 路线图 |
| 14 | events/lab.py | SQLite、结算、参考现金、状态/取消竞态 |
| 15 | frontend/dist/assets/index-D1-gAVSm.js | 编译产物与源码一致性（不能独立替代构建测试） |
| 16 | frontend/dist/index.html | 构建入口及资产引用 |
| 17 | frontend/src/event-lab.tsx | 旧 F 研究 UI 兼容 |
| 18 | frontend/src/forms.tsx | 新面板挂载与布局 |
| 19 | frontend/src/prediction-challenge.tsx | 100 轮 UI、命令和报告 |
| 20 | market/predictions.py | 开放市场发现和未来时间筛选 |
| 21 | scripts/build_source_package.py | 发行白名单、G1 文件与版本 |
| 22 | terminal/api.py | G1 独立 API、权限边界、生命周期 |
| 23 | tests/event_research_browser.py | F 页面回归 |
| 24 | tests/prediction_challenge_browser.py | G1 浏览器路径 |
| 25 | tests/test_prediction_challenge.py | 100轮 Mock、异常场景和恢复缺口 |

全仓横向审查另涉及：README、主计划、PROGRESS_STATUS、AI_DEVELOPMENT_COLLABORATION、RELEASE_READINESS、LIVE_TRADING_VERIFICATION、DEPENDENCY_AUDIT、requirements/锁定依赖、.gitignore、server、启动器、terminal runtime/settings/config、execution venue/live、market discovery/details、events store/observations、AI brain/provider/coordinator、风险模块及打包脚本。**此范围是源码目录与重点模块静态审查，不能冒充对全部仓库文件的逐行执行式安全审计。**

## 4. 必须通过的修复后验收矩阵

| 项目 | 最低验收条件 | 当前证据状态 |
|---|---|---|
| 确定性早结果 | 无无限 WAITING/STOPPING；准确终止/拒绝；参考现金与对账一致 | 阻断 |
| 大量 PAUSED 历史记录 | 至少 50+ PAUSED 时新 ACTIVE 挑战持续推进 | 阻断 |
| 完整服务重启 | 新进程重建对象、重新打开旧 F SQLite 文件且保留历史数据 | 缺证据 |
| 预约/入队崩溃窗口 | 每条 request_id 至多一轮、无重复 DEBIT/PAYOUT | 部分 Mock 证据 |
| 停止/暂停网络竞态 | 迟到请求不复活取消轮次、资源安全关闭 | 部分 Mock 证据 |
| 统计/报告 | 预测、参与、SKIP、失败、结算、有效完成口径可复核；金额对账 | 需补边界 |
| 原 F 兼容 | 旧入参、旧会话与旧轮次继续可用；新字段不破坏幂等 | 部分离线证据 |
| 全量回归 | 针对修复后实际 HEAD 在隔离环境复跑，并保存真实结果 | 840/0 仅旧报告 |
| UI 与构建 | 类型检查、Vite 构建、F/G 浏览器回归 | 仅旧报告 |
| 安全与发布 | 无密钥/真实资金访问；不宣称 Stable、真实交易验证 | 维持关闭 |
| Git 提交 | 独立 PR 变更可审查、无强推、保留其他分支、无无关改动 | 本次仅报告 |

## 5. 合并准入与下一阶段

- 在 PR1-001、PR1-002 修复并提供测试证据，PR1-003 完整重启/增量迁移通过，线程与报告风险完成验证之前，不批准合并。
- 修复应在独立提交中完成，并记录新的 head SHA、文件列表、测试环境及实际通过/失败/跳过；更新阶段报告时保留原 840/0 的历史含义。
- 所有必需测试通过后，重新检查 PR Diff、工作流、分支冲突与权限边界，并由项目所有者最终决定是否合并。
- G2 的 OpenClaw / 飞书 / Telegram 异步通知继续作为**独立阶段**；G1 合并不代表 G2 已验收。

## 6. 本次审查记录的提交约束

本次操作**只新增本文件** docs/PR1_REVIEW_FINDINGS.md 到现有 G1 PR head 分支。不修改、删除或覆盖其余 25 个原有文件；不改动 main，不合并 PR，不接触本地/用户数据库及真实资金。PR 原始 HEAD 与 main 基线已在文件顶部保存，作为后续恢复和核对依据。

相关原有审查记录：[PR #1 审查及行内评论](https://github.com/cuihanzhe955-commits/SmartMoneyAITrader/pull/1)；原审查 review ID 为 5800821011。
