# 本地进度审计（2026-11-11）

本轮实际根目录 E:/user/ChatGPT；开发工作树 SmartMoneyAITrader_v0_1_completion_20261111，基线 origin/main=4559f4282f659160273f5cc614b6884c879eca04。

| 本地目录（均在上述根目录） | HEAD | 状态与决定 |
|---|---|---|
| SmartMoneyAITrader | 无 Git | 历史运行目录，保留原数据库/凭据/本地独有文档，不直接同步 |
| SmartMoneyAITrader_G1_fix_20261109 | 6afed70 | 干净，成果已包含于 main |
| SmartMoneyAITrader_G2_review_20261109 | da94294 | 干净，成果已包含于 main |
| SmartMoneyAITrader_integration_20261104_104216 | 4f03671 | 干净，成果已包含于 main |
| SmartMoneyAITrader_G1_windows_instance_isolation_20261110 | 4dbda5f | 仅未跟踪本地完整验收报告，留在原处；源码已上 main |
| GitHub/SmartMoneyAITrader | 4dbda5f | 干净，落后最新 main 4 提交；不切换旧工作树 |

已确认 backups、releases、safe_sync_backups、SYNC_BACKUPS 目录存在；未改备份或运行数据。旧 tests.zip 已在上一轮获准删除，本轮不删除或移动任何同名文件。当前没有发现额外的 v0.1 UI 本地工作树；UI 成果存在远端分支。

本轮 fetch --all --prune 成功。PR4 合同及 PR7 文档已合并；PR5 与 PR9 均开放且同指 fda7126，UI 内容仅在新开发分支整合。PR8 已关闭未合并。最新远端 CI 记录存在 failure，不宣称整体绿色。

G1、G2、Brain、AI、执行与通知源码由最新 main 继承，不重写。UI 使用已有 fda7126，修复新导航影响的浏览器入口。新代码改动均保留为可审查 Git 提交；本地日志仅 artifacts，不上传。

完整性边界：运行目录本轮未做全量文件哈希重审、数据库只确认历史目录用途，未读取其内容；不能将上述摘要当作所有本地额外文件均已完成逐文件审计。


本轮实现与验证：整合 fda7126 UI（保留最新 DOC-01 使用说明冲突侧），增加 G1 调度异常重试边界与测试，修复 G1/Brain 浏览器展开高级导航。实际全量 939 passed / 0 failed / 0 skipped，72.54 秒；npm ci、TypeScript/Vite、G1 和 Brain 浏览器均退出 0。日志保存在新工作树 artifacts，不上传。没有执行完整生产通知闭环、保护单/86401压力复验、干净Windows安装或真实五门槛验收，因此只是接续检查点，尚未完成 v0.1 候选版。


## 第二轮独立复核（2026-11-11）

基线 main 4559f42 / PR10 37cf6e5；PR开放、Draft、无冲突，该 HEAD Windows CI success。本轮仅修改原开发分支，不修改 main、其他工作树或运行数据库。当前代码写入者仅本次任务；未遍历或终止其他用户进程。已知工作树根目录未发现 tests.zip，本轮没有删除/移动/覆盖同名资产；未全面递归备份。旧工作树状态沿用本轮开始只读核对，未将全部资产宣称逐字节验收。

独立审查：检查 PR 完整文件清单和主导航、使用说明、G1/Brain、G2通知、测试及依赖差异。没有新增依赖、删除历史模块、数据库或日志上传。UI目前仍使用“总览/运行”标签而不是合同精确的“首页/自动交易”，属于待完善的文案一致性，不宣称UI全部验收。主导航浏览器前进/后退及全部错误恢复未独立覆盖。

真实调用链：G1线程 tick、事件预测/结算线程、Brain同步/复盘线程均调用 Brain.db；G2使用独立Outbox连接与工作器。本轮 Brain.db 在 BEGIN IMMEDIATE 或事务内部 SQLite 错误时 rollback，分类 SQLITE_BUSY/LOCKED 为 BrainBusy；其他数据库错误保留异常因果。不会在contextmanager内部重放 yield 或事务体。Brain、G1循环对 transient失败最多等待30秒后继续新一轮；并非永远放弃持久任务，停止Event可立即中断等待。非预期异常记录traceback、显示停止状态并退出该线程；模型未配置独立分类，等待配置，不误当成程序Bug。UI复用现有 error字段，未新增健康面板。EventLab已有内部捕获/任务失败策略尚待更深入幂等审查，本轮没有证明所有G1/Brain事务跨步骤exactly-once。

新增5项测试：真实SQLite写锁后恢复、持续busy退避与停止、非数据库异常日志/停止、部分事务回滚、四线程80条唯一写入与恢复/完整性检查。保留原G1恢复和G2全量测试。未新增真实资金交易或写入交易账本。

本轮完整回归944 passed / 0 failed / 0 skipped，65.68秒；前端构建退出0；G1、Brain、事件研究浏览器退出0。保护单原始创建/撤销/释放/替换/部分成交断言本轮通过，历史超时暂无法复现。压力首次保留100000输入/86401显示，1.17秒；复测1.003秒，JS heap used 92175006 bytes / total135405942 / limit4395630592，无pageerror；此值是浏览器JS heap，不是系统总内存或Node driver峰值。本轮未调整精度、点数、超时或断言。第二次压力日志仅输出结果，第一次含ConnectionResetError；连接关闭异常仍需进一步稳定复验。

失败尝试保留：最初复测因新工具模块与既有ai/worker.py重名导致33项收集错误；当场将工具移至ai/worker_policy.py并从HEAD恢复原Inference实现，后续全量通过。没有推送破坏Inference的中间状态。

未完成：全部九项并发/幂等验收中，独立子进程恢复、真实G1+Brain长时间竞争、重复交易账本专门测试尚未补齐；已有全量恢复测试通过不替代这些专项要求。因此数据库问题属于部分修正并验证，不宣称全部解决。

本地日志 artifacts/round2-*.log；不上传。完整Windows安装/启停本轮未重新执行。真实平台五门槛仍未验收，未读取生产凭据。主计划和DOC-01未改。


## 第三轮 Brain 租约、幂等与 Worker 隔离（2026-11-11）

本轮基于 PR #10 的开发分支继续，初始审查点 81c2569；当前代码 HEAD `73c2843253a9a017900c419212e16875980106bd`。main 仍为 `4559f4282f659160273f5cc614b6884c879eca04`，未修改 main；PR #10 保持 open/Draft、未合并。仅更新远端开发分支文件；未操作本地工作树、运行数据库、凭据或 tests.zip。

实现：brain_reflections 增加 lease_token，旧 SQLite 表采用增量 ALTER TABLE 迁移；next_try 兼作待处理到期时间与 RUNNING 租约期限，只有过期 RUNNING 才可回收；recover 失败时同步 worker 保留 recovery_required 并重试。任务完成/失败必须匹配当前 lease_token，旧 worker 无法覆盖新租约。hypothesis 记忆写入与 COMPLETED 状态在同一 SQLite 事务提交；兼容旧版本已持久化结果但未确认状态的记录，按稳定记忆 ID 直接补齐，不重复调用模型。手动 retry 不抢占有效租约。

调用节流：保留跨任务 AI interval。RUNNING、COMPLETED、FAILED 任务的 next_try 冷却时间会阻止下一条任务过早调用；新增两任务间隔测试。每日 calls 预算与现有配置继续沿用。

Worker 状态：Runtime、EventLab、Brain 同步、AI 复盘错误分别存储，error 字段聚合展示；某一工作线程成功不会清除其他通道仍存在的错误。Runtime/EventLab 调用点已改用各自状态字段。

新增/补强专项：旧表迁移、过期租约恢复、旧租约 fencing、已持久化结果恢复、AI 结果与 COMPLETED 原子提交、有效租约禁止手动 retry、全局 interval 节流、Worker 错误通道隔离。并发 SQLite 压力仍为 4 线程/80 条唯一记录及 PRAGMA integrity_check；初次 10 次×10ms 重试在 Windows CI #43 发生一次耗尽，已调整为最多 50 次指数退避（单次睡眠上限 50ms），未降低并发量或完整性断言。

Windows CI run #44（精确 HEAD `73c2843`）：**951 passed / 0 failed / 1 warning，183.46 秒**；npm ci、TypeScript/Vite 构建、event_research_browser.py、prediction_challenge_browser.py 均通过。唯一 warning 为既有 Starlette/httpx TestClient 弃用提示。运行记录：https://github.com/cuihanzhe955-commits/SmartMoneyAITrader/actions/runs/43032512262 。

可靠性边界：外部 AI 调用与本地 SQLite 不能构成分布式 exactly-once。模型响应返回后、结果持久化前若进程崩溃或数据库持续不可写，恢复时可能再次调用模型；已持久化结果幂等，旧租约不能覆盖新状态，不宣称外部模型调用严格一次。

仍未关闭：G1+Brain 长时间竞争、独立进程强制终止/恢复、完整保护单/历史回放/验收浏览器、OpenClaw 生产通知、干净 Windows 安装升级回滚；真实平台五项实盘门槛未验收。本轮未读取生产凭据、未进行真实资金操作。PR 保持 Draft，不自动合并。


## 第三轮第二批：租约/节流分离、旧结果恢复与错误通道修正（2026-11-11）

本节修正并取代上一节中间态的时间字段设计：`next_try` 不再兼任 RUNNING 租约或全局 AI 冷却。验证代码提交为 `97c97fe2d91ac8e1aa01c74de3245c9149e708cb`；其后的 `08bfaa2` 仅更新设计文档。当前开发分支 HEAD 为 `08bfaa289ff97b98ac7aed7f2f32113a19dd4b84`。main 仍为 `4559f4282f659160273f5cc614b6884c879eca04`，PR #10 仍 open/Draft、未合并，base/head 未改变为 main。所有改动仅在 `feat/v0-1-first-release-completion`；未操作本地工作树、运行数据库、生产凭据或 tests.zip。

### 最终实现方案

- `brain_reflections.next_try`：只控制 PENDING 任务的再次尝试时间。
- `lease_until`：当前 RUNNING 任务的租约到期时间；`lease_token`：本次持有者随机令牌。
- `brain_ai_state.last_call_at`：持久化跨任务、跨进程、跨 UTC 日期的全局 AI 调用间隔；`brain_ai_usage`：每日 calls 预算。
- 任务领取在 `BEGIN IMMEDIATE` 中原子执行：回收过期租约、阻止第二个有效 RUNNING 租约、校验全局 interval 与每日预算、更新任务租约/令牌/attempts，并预留调用额度与 last_call_at。即使 interval=0，也保持单任务 single-flight。
- 租约时长为 `max(30 秒, provider timeout + 30 秒)`，不再用 interval 延长租约。模型网络调用始终在 SQLite 事务外。
- 结果记忆稳定 ID 为 `digest(scope + ':' + job_id + ':ai-reflection')`；记忆写入与 COMPLETED 确认同一事务提交。提交时在取得写锁后重新读取时钟，并验证状态、令牌与租约期限。旧 Worker 无法覆盖新持有者。
- 短暂 SQLite busy 时，最多四次可中断提交重试（50/100/200ms 退避），复用同一份 AI 响应。持久锁冲突或进程在结果持久化前崩溃时，租约过期后可能再次调用模型；外部 AI 与本地 SQLite 不宣称分布式 exactly-once。
- recover 扫描 PENDING/RUNNING/FAILED 的稳定结果 ID；发现旧版本已持久化的结果时直接补齐 COMPLETED。手动 retry 也先检查稳定 ID。没有结果的过期 RUNNING 才回到 PENDING；有效租约不被抢占。
- 旧库通过 `PRAGMA table_info` 增量添加 lease_token/lease_until，不重建表、不删除任务。旧 RUNNING 的 next_try 迁移为 lease_until；首次创建全局节流状态时，若存在旧版冷却或当天已有调用，则从迁移时刻保守开始计算 interval。
- Runtime、EventLab、Brain 同步、AI 复盘错误分别保存；API error 聚合展示。普通同步只清 sync_error；只有 recover 成功才清 runtime_error；EventLab 学习成功才清 event_error；AI 复盘错误独立处理。

### 测试覆盖与验证

新增/补强覆盖：旧表无 token 与已有 token 两种迁移；有效旧租约和全局冷却继承；过期租约恢复；旧令牌在无人接管前也不能提交；结果与 COMPLETED 原子提交；瞬时锁冲突复用同一响应；持续锁冲突到期恢复；旧版 FAILED/PENDING/RUNNING 已持久化结果自动对账；手动 retry 不绕过 interval；跨重启 interval 持久化；每日预算预留；多线程只领取一次；有效租约即使 interval=0 也阻止第二次模型调用；Runtime/Brain/EventLab/Reflection 错误通道隔离。原有 SQLite 4 线程、80 条唯一写入与 `PRAGMA integrity_check` 压力测试保留，重试改为最多 50 次有上限指数退避，没有降低并发量或完整性断言。

- Windows CI run #61（代码提交 `d9d7791`）：959 passed / 0 failed / 1 warning，174.32 秒；构建和两项浏览器测试通过。
- Windows CI run #65（代码提交 `9768971`）：960 passed / 0 failed / 1 warning；构建和两项浏览器测试通过。
- Windows CI run #68（代码提交 `97c97fe`）：**961 passed / 0 failed / 1 warning，148.24 秒**；npm ci、Vite 构建、`tests/event_research_browser.py`、`tests/prediction_challenge_browser.py` 全部通过。唯一 warning 为既有 Starlette/httpx TestClient 弃用提示。运行记录：https://github.com/cuihanzhe955-commits/SmartMoneyAITrader/actions/runs/43038792657 。
- 中间回归失败均保留并已修正：全局 interval 测试曾把异常 Mock 放在 provider_factory，修正为断言 provider.chat 未被调用；旧版结果已存在的恢复测试预期从 PENDING 更正为 COMPLETED。没有删除测试或降低断言。

### 仍未验收的事项

G1+Brain 长时间竞争、独立进程强制终止/恢复、完整保护单/历史回放/全部验收浏览器、OpenClaw 生产通知、干净 Windows 安装升级回滚仍未全部关闭。真实平台五项实盘门槛仍未验收；本轮未读取生产凭据、未进行真实资金操作。PR #10 保持 Draft，不自动合并，不修改 main。
