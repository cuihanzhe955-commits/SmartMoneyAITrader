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
