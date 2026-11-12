# 第三轮可靠性验收报告

收尾核验日期：2026-11-12。结论：本轮离线功能验收有条件通过；v0.1 最终验收门槛尚未全部关闭，不能标记 Stable。

## 基线与边界

唯一开发分支 feat/v0-1-first-release-completion；测试基线 3da6e28aab59005e211f6373403d07c6a0b30f42 加本报告同批源码差异。main 基线4559f4282f659160273f5cc614b6884c879eca04。开始时干净，本地81c2569安全快进到远端3da6e28。PR10仍open/Draft。本轮未修改main、合并PR、访问真实交易账户或生产凭据。没有操作tests.zip；仅已知工作树根目录存在性检查，不代表全面扫描历史备份。所有交易、AI和通知测试使用临时数据库、Mock或历史回放。

## 实际修复

- events/lab.py：单独处理BrainBusy，保留持久轮次等待下一tick，避免通用异常分支误记FAILED。六工作器压力曾出现20个有效轮次却生成21条轮次；修复后保持20条，未降低唯一性断言。
- tests/test_event_lab.py：确定性注入写锁，确认不调用模型、不改变QUEUED状态，下一tick恢复WAITING且无重复轮次。
- tests/test_brain_spawn_recovery.py：Windows spawn独立进程A/B/C；终止A、到期前拒绝回收、到期后B完成、旧token响应拒绝、C重启读回正确状态。旧响应由父进程重放，不能解释为已终止的A真正返回。另测试结果与COMPLETED同事务回滚，以及旧表迁移中途异常后结构/数据完全保留，解除故障后迁移成功。
- tests/test_g1_brain_stress.py：三轮，六线程：三个记忆写入者、一个G1调度者、两个复盘领取者；每轮20个G1有效轮次、150条唯一普通记忆、12个唯一复盘任务/令牌/调用/记忆，重开数据库并integrity_check=ok。它是并发线程压力；独立进程故障由前一测试覆盖。不是长期真实运行验证。
- 八个旧浏览器脚本：实际点击“实验功能”展开导航，旧“自动交易/历史回测”入口改用当前“运行/历史”；保留业务、授权、订单和布局断言。
- tests/run_browsers.py：统一运行15个浏览器入口，Windows Job只清理自建进程树，逐项保存命令、起止时间、退出码和日志；任一非零退出使总入口失败。
- Windows workflow：从两个浏览器入口扩为全部15项，增加独立.venv安装和Windows启动/停止/恢复检查，并保存浏览器日志。

## 测试证据

| 命令（python -X utf8 -B） | 开始 | 结束 | 退出码 |
|---|---|---|---|
| tests/run_offline.py tests/test_brain.py tests/test_brain_worker_recovery.py | 2026-11-11T23:01:32.825886+08:00 | 2026-11-11T23:01:40.154922+08:00 | 0 |
| tests/run_offline.py tests/test_brain_spawn_recovery.py | 2026-11-11T23:01:40.156913+08:00 | 2026-11-11T23:01:43.792188+08:00 | 0 |
| tests/run_offline.py tests/test_g1_brain_stress.py | 2026-11-11T23:01:43.792188+08:00 | 2026-11-11T23:02:03.020608+08:00 | 0 |
| tests/run_offline.py | 2026-11-11T23:02:03.021614+08:00 | 2026-11-11T23:03:57.171785+08:00 | 0 |
| tests/integration.py | 2026-11-11T23:03:57.172782+08:00 | 2026-11-11T23:04:03.276976+08:00 | 0 |
| tests/restart.py | 2026-11-11T23:04:03.277519+08:00 | 2026-11-11T23:04:37.894515+08:00 | 0 |

按上述顺序结果：Brain39 passed；spawn/原子性/迁移3 passed；并发压力3 passed；完整离线968 passed、0 failed、0 skipped、1条Starlette弃用警告（112.94秒）；integration和restart均PASS（完整24小时、276笔模拟成交及净值一致）。专项是全量子集，不累加成总测试数。

前端npm ci及npm run build --prefix frontend成功；TypeScript检查包含在build内，Vite1.39秒。Python AST解析与git diff --check通过。项目未另设独立前端单元测试命令。

15个浏览器入口browser/ui_terminal/acceptance_browser/brain_lab_browser/challenge_template_browser/discovery_browser/e_stage_browser/event_research_browser/phase4_browser/pool_browser/prediction_challenge_browser/protection_browser/replay_browser/research_browser/sizing_browser最终全部exit0；逐项起止记录见artifacts/browser-suite/*.json，完整日志同目录。覆盖1366和1920、深浅主题及原脚本功能断言。真实截图保留在各输出目录；不是重新设计UI。

Windows start.bat --install-only从本工作树新建.venv成功；windows_smoke验证start.bat/start.cmd/stop.bat、自有实例崩溃恢复、272笔模拟成交及精确净值，exit0。它是现有Windows上的全新项目环境，不等于全新OS/普通用户安装验收。

OpenClaw Gateway、Outbox、Worker的飞书/Telegram协议与错误状态由完整离线套件覆盖；没有发送生产通知。保护订单Mock生命周期、部分成交、资金/权限风险、历史回放由原测试和浏览器覆盖，不代表平台真实账户验证。

临时数据库的integrity_check由spawn、迁移与三轮压力断言执行，均ok；没有为检查而打开生产数据库。

## 失败记录与未关闭事项

1. 初始六工作器压力43 passed/1 failed：21条轮次；已定位BrainBusy通用异常路径并修复，专项109 passed，最终全量968 passed。
2. 初始旧导航脚本超时，已更新真实导航交互并全量重跑。没有删除断言。
3. 保护单浏览器首次在第二条“核对完成·已释放”UI刷新超时；后两轮通过，根因未确认。应做重复稳定性验收，不能宣称已确定修复。
4. Windows Python3.12.2 asyncio Proactor关闭连接时偶发WinError10054。最终research_browser日志仍有该traceback，虽然脚本exit0且页面无pageerror；没有过滤或伪称日志干净。此项未关闭。
5. 全新Windows OS、普通用户权限、整包升级失败回滚尚未完整验证。数据库事务级迁移回滚已验证，不能替代安装器全流程回滚。
6. 当前压力是三轮有界压力，未证明任意时长或全部跨模块exactly-once。真实平台成交、手续费、保护单和账户对账未验收。

## 日志、Git与回滚

完整日志在本工作树artifacts/round3-*.log、artifacts/round3-final/、artifacts/browser-suite/；截图按脚本输出保存，均不随源码提交。早期失败日志保留。起止时间表来自最终记录，不将历史961项CI冒充新HEAD结果。

回滚基线为3da6e28；不使用reset/clean或旧数据库恢复。必要时在用户批准后对本轮提交做revert，并保留未知订单和运行账本。本轮无需数据库结构升级。提交仅含源码/测试/workflow/报告，不含依赖目录、数据库、密钥或私人数据。

新提交SHA和CI以Git历史及PR10对应HEAD Checks为准；在新CI完成前不声称通过。最终独立审核仍由用户/ChatGPT执行。
