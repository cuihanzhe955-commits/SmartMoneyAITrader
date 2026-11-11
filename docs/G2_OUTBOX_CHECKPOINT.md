# G2通知待发送记录：小检查点

> **DOC-01 范围说明（2026-11-11）：** OpenClaw、飞书和 Telegram 完整生产通知链路已纳入
> v0.1 第一版目标。本文件记录的 Outbox、Worker、Gateway 代码和测试仍只是局部/离线证据；
> 尚未完成生产认证、真实发送、送达核验、Runtime/UI 闭环，不能标记为第一版已交付。

日期：2026-11-06；依赖G1提交8b94bae。分支为独立通知研究分支，G1的PR尚未合并，此处不修改main。

本轮仅实现events/notification_outbox.py及隔离测试：显式入队、持久化、按平台/产品/环境/会话/事件/通道/账号/目标去重，冲突保留原记录，有界读取，数据库忙返回未确认而非假成功。只有PENDING状态，不声称送达或exactly-once发送。

没有接入Runtime、API或UI，没有读取用户凭据或OpenClaw配置，没有执行用户运行库迁移，没有发送消息。生产调用方将来必须在交易/保护事务外入队；写入失败不能成为交易核心的同步依赖。

验证：python -X utf8 -B tests/run_offline.py tests/test_notification_outbox.py，21通过、0失败，1.56秒。覆盖重启、并发、重复、冲突、多作用域、数据库忙、旧表保留和非法配置。本轮未重新运行全量或前端检查（尚未接入调用链、前端未改）；原G1的840项属于历史基线。

仅保存本地提交，不推送、不新建PR、不打包。回滚点8b94bae；无需回滚用户数据库。

下一步：建立通知发送状态机与独立工作器/有限重试，再研究Gateway实际协议并接入UI；目的地、凭据和真实发送仍须按既有授权处理。当前没有投递与去重送达保证。

## 后续小步：发送状态机与独立工作器（2026-11-06）

在688ee68的入队检查点上继续，实现events/notification_worker.py，并扩展outbox。保留原有通知意图表，新增独立notification_dispatch表记录SENDING、RETRY、ACKNOWLEDGED、FAILED、UNKNOWN；没有派发记录的意图仍为PENDING。未对用户运行数据库执行迁移。

独立后台线程领取任务，发送回调在数据库事务外运行。每次尝试使用独立令牌，避免重复领取和过期回调覆盖状态。只有适配器明确确认远端未受理时，才按5秒起步的指数退避有限重试；明确拒绝进入FAILED。网络超时、非预期返回、退出中断及发送租约过期进入UNKNOWN，不盲目重发。重启保留已受理记录和原重试上限。

ACKNOWLEDGED仅表示适配器报告通道受理，不表示用户收到；delivery_verified始终为false。单工作器最多一个发送任务，卡住的发送线程隔离至返回，期间该工作器暂停后续发送，避免线程无界增长；关闭不等待卡住的发送回调。尚未接入交易Runtime，因此本步不声称已验证完整交易调用链的通知隔离。

验证命令：python -X utf8 -B tests/run_offline.py tests/test_notification_outbox.py tests/test_notification_worker.py。结果37通过、0失败，1.33秒。覆盖明确未受理重试、超时未知、迟到回执、并发领取、重启恢复、旧表兼容及资源限制。未修改前端，未执行真实消息发送或全量回归；G1的840项仍仅为历史基线。

本步仅保存本地提交，不推送、不新建PR、不打包。修改文件为outbox、worker、新增worker测试及本检查点，并更新源码清单。回滚点688ee68；临时测试数据库无需迁移回滚。下一步为核实Gateway协议并实现实际通道适配、运行生命周期接入及UI状态展示；这些功能尚未实现。

保存前补充源码包规则回归：同上两份通知测试加tests/test_package.py，共53通过、0失败，1.43秒；修改文件敏感模式扫描与git diff --check通过。

## 后续小步：Gateway直接发送协议适配（2026-11-06）

基于151f369增加events/notification_gateway.py与tests/test_notification_gateway.py。GatewayNotificationSender将已校验的通知转换为send请求，显式指定channel、accountId、to、message和稳定idempotencyKey，每次RPC使用新的请求ID。只接受匹配请求ID、事件runId和通道、且带有效messageId的成功回执；通道受理仍不等于送达。

本地无效通知在调用传输前拒绝。RPC异常、错误帧、部分或缺失回执、跨请求或跨通道回执均转为UNKNOWN；即使远端错误标注retryable也不能证明从未发送，不自动重试。错误正文不进入持久状态。

核验依据：G盘已安装OpenClaw版本2026.10.8的SendParamsSchema和send处理器（src-D6kL8tMP.mjs、send-B60CD8vU.mjs），以及[官方直接发送RPC说明](https://docs.openclaw.ai/gateway/protocol/rpc-system-and-channels)。通过Node只加载官方参数验证器，飞书和Telegram两组非私人样本均通过校验；未连接Gateway、未加载用户凭据或修改OpenClaw配置。

本适配器注入rpc(frame, timeout=seconds)传输函数，尚未实现生产WebSocket连接、认证与通道健康读取，也未接入Runtime或UI。测试RPC为替身，不代表真实平台联调。官方幂等键不被当作跨重启永久exactly-once保证。

验证：python -X utf8 -B tests/run_offline.py tests/test_notification_outbox.py tests/test_notification_worker.py tests/test_notification_gateway.py tests/test_package.py，共84通过、0失败，1.67秒（其中新增31项）。无前端变更，未跑全量回归。本步仅本地保存，不推送、不打包。回滚点151f369，无用户数据库迁移。下一步为Gateway认证连接及只读通道状态接入，再接运行生命周期和设置UI。
