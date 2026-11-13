# 第三轮 Brain 并发可靠性修复报告

日期：2026-11-13。唯一开发分支 feat/v0-1-first-release-completion。
基线及当前 HEAD：e6f0da99f3a40bcaf904efc7baaedbeec5471095。本轮未经提交，测试对象是此 HEAD 加本地差异。

## 故障链与复现

旧代码 Provider 返回、Schema 验证后，结果提交最多四次。BrainBusy 耗尽后抛出，局部结果消失，数据库仍 RUNNING。固定时钟1000使1035租约永不到期，后续 tick 因有效租约退出。
本轮从 git show 指定基线读源码，在内存独立模块执行，使用临时数据库、Mock、真实 BEGIN IMMEDIATE 锁；提交耗尽后释放锁，再调用10次 tick，仍 RUNNING、attempts=1、lease_until=1035、记忆0、Provider调用1。日志 artifacts/brain-baseline-reproduction.log。这证实可达故障，不证明历史 CI 唯一根因。

## 修复设计

ai/brain.py：构造器增加容量1的待提交结果和互斥锁；_flush_reflection 使用 monotonic 控制0.8秒尝试预算，stop.wait可取消退避，每次重新开启事务，数据库连接关闭后才等待。耗尽 BrainBusy 保留结果，后续 tick 优先提交。结果包括job_id/token/source_data/reflection/model/lease_until。成功、token失效、状态改变或租约到期后清除。固定时钟下保留有效结果供后续提交，不因时间预算耗尽丢弃。
互斥锁只保护该 Brain 实例的缓存与提交；数据库领取仍用原原子事务，允许原有并发 Provider 工厂和嵌套过期恢复。不同实例/进程由数据库 token 与事务隔离。本缓存不跨崩溃、不承诺 Provider exactly-once。
_commit_reflection_result 未修改：取得写锁后验证有效token、RUNNING及租约；确定性记忆和COMPLETED同事务。没有结构迁移，没有修改租约长度或SQLite等待参数，没有降低WAL/FULL、30秒排空或100秒回放门槛。

## 新增测试

tests/test_brain_reflection_commit_retry.py 六个用例：真实锁冲突同调用恢复；跨tick单工作器；跨tick双工作器；替换token拒绝旧缓存；停止与连接释放；过期缓存清理。锁冲突由事件协调，验证确实收到BrainBusy，不用固定sleep制造竞争。
单/双worker恢复均断言Provider一次、attempts=1、COMPLETED、记忆一条、integrity_check=ok及同一token。替换token用SQL模拟已经被新owner接管；真实spawn领取/终止/重启及事务中途回滚继续由原有test_brain_spawn_recovery覆盖，未修改其断言。

## 失败保全与自审

初稿锁住整个tick，导致原有并发工厂Barrier和嵌套过期恢复失败；收窄锁后原测试全部通过。过期缓存新增测试曾错误传dict给设置接口，已改用BrainSettings。失败日志brain-commit-new.log、brain-commit-repair.log、brain-commit-repair2.log及artifacts/brain-concurrency-20261113/均保留；首次批处理在发现失败后停止，不能当最终结果。
最终命令、起止时间、退出码逐项保存在artifacts/brain-concurrency-final/results.json，各项完整日志同目录。未运行远端CI，未访问生产账户/密钥或数据库，未操作tests.zip。

## 最终结果

本专项本地验收 PASS。新增专项6 passed；Brain相关48 passed（含新增与spawn）；压力连续三次执行，每次3 passed，分别10.68/13.07/10.98秒；全量981 passed、0 failed、1条既有Starlette弃用警告，92.77秒。专项是全量子集，不相加作为总数。
15浏览器入口全部exit0，前端TypeScript/Vite构建exit0（构建包含工具提示，详见原日志）。Windows完整入口exit0，一次不中断加三次强制终止恢复，恢复分别22.110/21.968/20.953秒，均小于原100秒。每轮保留272 fills、NAV943.8943549007662容差、86400秒、1441分钟完整覆盖、integrity_check及账本相等断言。

| 项目 | 开始 | 结束 | 退出码 |
|---|---|---|---|
| new | 2026-11-13T18:57:30.959802+08:00 | 2026-11-13T18:57:32.901453+08:00 | 0 |
| brain | 2026-11-13T18:57:32.902459+08:00 | 2026-11-13T18:57:41.730725+08:00 | 0 |
| stress-1 | 2026-11-13T18:57:41.732230+08:00 | 2026-11-13T18:57:53.202346+08:00 | 0 |
| stress-2 | 2026-11-13T18:57:53.203829+08:00 | 2026-11-13T18:58:07.051877+08:00 | 0 |
| stress-3 | 2026-11-13T18:58:07.052878+08:00 | 2026-11-13T18:58:18.849076+08:00 | 0 |
| offline | 2026-11-13T18:58:18.849650+08:00 | 2026-11-13T18:59:52.784965+08:00 | 0 |
| browsers | 2026-11-13T18:59:52.785970+08:00 | 2026-11-13T19:02:30.018064+08:00 | 0 |
| build | 2026-11-13T19:02:30.019072+08:00 | 2026-11-13T19:02:33.430560+08:00 | 0 |
| windows | 2026-11-13T19:02:33.430560+08:00 | 2026-11-13T19:04:51.941845+08:00 | 0 |

代码位置：ai/brain.py:58缓存初始化、:301提交重试、:324跨tick入口、:399返回结果暂存；原_commit_reflection_result事务不变。新增测试在tests/test_brain_reflection_commit_retry.py。原压力测试和spawn测试未修改。

## 剩余边界与Git交接

指定缺口已由旧基线确定性复现和修复后测试关闭：同一存活Brain实例中，AI返回后的BrainBusy不会因重试预算耗尽丢弃结果，下一tick可用原token恢复提交，不重复Provider，attempts保持1。持续不释放的数据库锁仍会阻止任何提交；租约失效后旧缓存必须丢弃，进程崩溃后仍可能重新调用Provider。这些不属于本缓存的exactly-once承诺。
未提交、未推送，未运行新远端CI；不能用本地通过声称Windows CI或整个v0.1 Stable已经通过。历史CI失败唯一根因仍不确定。项目其他未关闭事项仍以原报告为准。
当前HEAD仍e6f0da99f3a40bcaf904efc7baaedbeec5471095。工作树仅ai/brain.py修改，新增专项测试及本报告。git diff --check通过；跟踪文件差异45新增/13删除，新增文件另计。完整命令和时刻见results.json，旧失败日志保留。回滚无需数据库迁移；保留当前差异供用户/ChatGPT审核，未经确认不执行提交、推送或合并。
