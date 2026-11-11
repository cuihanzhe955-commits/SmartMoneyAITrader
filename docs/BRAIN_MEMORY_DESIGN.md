# Smart Money Brain：实现与操作

日期：2026-11-06；实现见`ai/brain.py`、`events/lab.py`、`events/evaluation.py`及`frontend/src/event-lab.tsx`。

## 数据契约

SQLite增量表：`brain_preferences`、`brain_memories`、`brain_versions`、`brain_cursors`、`brain_reflections`、`brain_ai_usage`、`brain_ai_state`；事件轮次/现金为独立`event_lab_*`表。现货、事件与真实订单表不串用。

记忆包含id、scope、kind、status、available_at、source_time、revision、来源/模型/快照/证据data。现货scope为`spot:交易所:会话ID`（仅paper），事件为`event:会话ID`（reference_paper）。模型不是主键，换模型不删记忆。

状态区分观察、已确认本次结果、待验证假设、已失效和恢复记录（源待核验）。单个已确认结果不是策略已验证。AI不能修改风控、账户、订单权限或实盘配置。

## 时间与一致性

后续预测只引用同作用域、当时已经可用且源时间不晚于快照的版本。纠错保存旧版本；历史评估读当时版本。导入新增记录在恢复时才可用，标为源待核验，不倒填到历史预测。已有修订发生冲突时整次恢复拒绝，不覆盖本机数据。

现货索引每批最多25条；游标与幂等来源保留，暂停后可续读。AI复盘独立daemon，Schema失败不污染事实，重启恢复RUNNING任务。现货复盘每日调用上限沿用当前AI配置calls，最短间隔沿用interval；事件每会话单独预留calls调用数，配对预测两次、复盘一次。以上不是H阶段尚待实现的全Provider统一费用预算。

记忆读写短事务，忙等待上限50ms。模型在事务/Runtime锁外运行；初始化失败时核心交易仍可用，后台重试。事件研究初始化失败可在界面重新连接。来源记录在原决策/轮次账本中保留。

## UI操作

进入策略实验室 → AI Brain。可开启/暂停模拟学习写入、后续决策引用记忆、自动AI复盘；搜索来源和内容；查看来源、纠错、标记失效；导出与恢复JSON备份。纠错只是记忆修订，不会改变已执行订单或历史预测。

首次默认学习写入开启、引用关闭、自动AI复盘开启。缺少模型时AI复盘保持等待，事实记录仍可用。已结算事件的复盘失败可重试；现货失败任务在折叠区重试。模型Key继续通过已有后端DPAPI配置读取，不进入记忆表。

## 配对评估

创建研究会话时勾选配对预测。同一快照生成无记忆/有记忆提案，模型指纹不同或结果迟到拒绝混合计分。只在可信官方结算后计算Brier、Log Loss与资金重放指标；资金重放按预测/结算实际发生顺序处理，未来兑付不能提前用于下一次入场。

收益和费用是明确参考模型的数值；净值口径为现金加未结算持仓成本，不是实时盯市。不以一个样本、单次盈利或模型自评信心证明策略有效，不允许自动优化实盘风险参数。

## API与备份

`GET /api/brain`搜索；`POST /api/brain/settings`开关；`POST /api/brain/correct`版本纠错；`GET /api/brain/export`导出；`POST /api/brain/restore`恢复（8MB上限）；`POST /api/brain/retry`重试失败复盘。完整导出上限5000条记忆、20000个历史版本；UI最近50条，来源列表有界。

校验SHA256检测意外损坏，不是来源签名或资金验证。导出可能包含私人研究记录，保存在用户选择的位置，不进入公开发布包。回滚保留当前库及新增表。


## 2026-11-11：复盘任务租约、幂等恢复与节流隔离

### 状态字段

`brain_reflections` 使用独立的 `lease_token` 与 `lease_until`：
- `next_try` 只表示 PENDING 任务的下一次允许尝试时间，不再兼作运行中租约。
- `lease_until` 是当前 RUNNING 持有者的到期时间。
- `lease_token` 是每次领取生成的随机持有者令牌；完成、失败和手动重试都必须尊重令牌与租约状态。

`brain_ai_state.last_call_at` 持久化跨任务、跨进程、跨 UTC 日期的全局模型调用时间；`brain_ai_usage` 继续记录每日调用预算。全局调用间隔、每日预算和单任务租约彼此独立。

### 领取与恢复

领取在 SQLite `BEGIN IMMEDIATE` 写事务内完成：
1. 先把已过期 RUNNING 租约回收到 PENDING，清空旧令牌。
2. 若仍存在未过期 RUNNING 租约，不创建第二个模型调用。
3. 检查全局 `last_call_at + interval` 与当天 calls 预算。
4. 原子地领取任务、递增 attempts、设置 `lease_until` 与新令牌，并预留一次每日调用额度、更新 `last_call_at`。

同一数据库同一时刻只允许一个有效 RUNNING 租约；即使 interval 配置为 0，也不会并发执行两条复盘任务。租约长度为 `max(30 秒, provider timeout + 30 秒)`，不再借用 interval 延长租约。预算在领取时预留，因此若进程在实际请求前崩溃，也可能保守地消耗一次预算。

`recover()` 只回收 `lease_until <= now` 的 RUNNING 任务。有效租约不会被重启流程或手动 retry 抢占；租约过期后，retry 才能清除旧令牌并重新排队。旧 Worker 即使稍后返回，也不能写入新任务状态。

### 结果提交与幂等边界

AI 结果使用稳定 ID：`digest(scope + ':' + job_id + ':ai-reflection')`。结果记忆写入与任务 COMPLETED 确认在同一个 SQLite 事务中提交；锁冲突时二者一起回滚。提交前在取得 SQLite 写锁后重新读取时钟，并同时验证 status、lease_token 与 lease_until，防止锁等待期间租约过期后仍提交。

短暂 SQLite 锁冲突时，当前 Worker 最多进行四次提交尝试，采用可被 stop 中断的 50/100/200ms 退避，重用已经获得的同一份模型响应，不立即再次请求模型。若锁持续不可用、进程在结果持久化前崩溃，租约到期后仍可能再次调用模型；外部模型服务与本地 SQLite 无法构成分布式 exactly-once。系统保证已持久化结果幂等、旧令牌不能覆盖新状态，不宣称外部模型请求严格一次。

恢复会扫描 PENDING、RUNNING、FAILED 任务的稳定结果 ID；发现旧版本已经持久化的结果时，直接补齐 COMPLETED，不再次调用模型。手动 retry 同样先检查稳定结果，避免把旧版“结果已保存、状态未确认”的任务重新送入模型。

旧数据库通过 `PRAGMA table_info` 增量增加缺失字段，不重建表、不删除任务。升级时将旧 RUNNING 任务的 `next_try` 迁移为 `lease_until`；首次创建全局节流状态时，如发现旧版仍在冷却的任务或当天已有调用记录，则从迁移时刻保守开始计算 interval，避免升级后立即绕过旧节流。

### Worker 状态隔离

Runtime 初始化/恢复、EventLab 学习、Brain 同步、AI 复盘分别保存错误状态；API 的 `error` 字段聚合展示。普通 Brain 同步成功只清除 `sync_error`；只有 `recover()` 成功（由 Runtime 启动路径或 Brain `sync_tick` 执行）才清除 `runtime_error`；EventLab 学习成功才清除 `event_error`；AI 复盘成功或确认没有待处理/有效租约任务时才清除 `reflection_error`。一个错误通道不会清除其他模块尚未解决的状态。

### 专项测试覆盖

- 旧表无 lease_token、已有 lease_token 但无 lease_until 两种迁移路径；保留有效旧租约与全局冷却。
- 过期租约恢复、未过期租约禁止手动 retry、过期令牌即使没有新 Worker 接管也不能提交。
- 同一任务结果稳定 ID 恢复（含旧版 FAILED/PENDING/RUNNING 遗留记录）、结果与 COMPLETED 原子提交、瞬时 SQLite 锁冲突复用同一模型响应、持续锁冲突到期后恢复。
- 多线程同时 tick 只允许一个 Worker 领取；有效租约存在时即使 interval=0 也不启动第二个模型调用。
- 完成后跨任务 interval、重启后 interval 持久化、手动 retry 不绕过 interval、每日调用预算对不同任务生效。
- Runtime 与 Brain 同步错误隔离；原有并发 SQLite 4 线程/80 条唯一记录及 `PRAGMA integrity_check` 压力测试保留。

