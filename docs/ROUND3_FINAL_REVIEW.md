# 第三轮最终代码审查与交付准备

日期：2026-11-13；分支 feat/v0-1-first-release-completion；HEAD e6f0da99f3a40bcaf904efc7baaedbeec5471095。开始时已有预期差异：ai/brain.py及两个新增测试/报告文件。已核对git status、diff --check、生产差异、新测试、原报告和原results.json。没有覆盖已有成果；历史报告是上轮实测，本报告记录本轮证据。

## 单槽缓存结论及证明边界

结论：在当前受控领取状态机、同一数据库及不倒退的租约时钟条件下，容量1安全，无需扩大缓存或修改生产实现。不能将此结论推广为任意多个有效Provider可以同时写入单槽缓存。

1. ai/brain.py:346-352检查有效RUNNING；:373-392在BEGIN IMMEDIATE事务内再次检查全局有效RUNNING后才能领取。即使两个工厂同时创建，也只允许一个任务提交领取并进入chat；Provider工厂并不等于Provider调用。
2. 第一笔结果遇锁后保留在_pending_reflection；:324-334入口优先处理缓存，该分支返回，不会领取第二笔任务。其他已进入工厂的调用仍受第二次事务检查约束。
3. :400-404暂存和flush与入口共用同一实例锁；有效租约只允许一个任务进入这一阶段，因此正常路径不存在第二份有效结果覆盖第一份的机会。
4. 租约过期后可能有重叠的旧Provider响应，:399拒绝本地已过期响应；提交时:278-299重新在写锁内验证数据库token、状态和截止时间。无效结果不得强求写入。不同Brain实例没有共用内存缓存，但仍受数据库全局领取及fencing约束。
5. 缓存只有一个字段，没有追加集合，容量确实为1；成功/无效token/任务状态改变/过期均清除。关闭进程会失去内存缓存，后续仍依赖租约恢复，不承诺Provider exactly-once。
6. 锁没有覆盖Provider或工厂，不形成它们之间的环形等待；入口采用非阻塞获取。提交重试使用stop.wait，可取消，单次SQLite等待仍为原50ms，未在打开连接期间sleep。既有stop资源测试与并发工厂Barrier、嵌套过期恢复测试保留。

## 新增确定性测试

tests/test_brain_reflection_commit_retry.py新增test_two_distinct_jobs_serialize_results_during_write_contention：两个线程、两个不同job、两个真实BEGIN IMMEDIATE锁窗口。每个Provider返回前，由事件确认已进入，再开启写锁并放行返回；确实触发BrainBusy后，结果保留在缓存。另一工作器再次tick只能重试缓存，Provider调用计数不增加，缓存job_id不变。释放锁后完成第一笔，才允许第二笔进入同样流程。
最终断言两个任务COMPLETED且attempts各1、Provider各调用1次、两个不同token、两条记忆及各自原始observation、integrity_check=ok。此测试验证用户允许的安全串行化方案，没有伪造两个同时有效的租约来绕过真实领取逻辑。
新增后专项7 passed；本轮生产ai/brain.py未再改变，哈希36eeb5393a662e2d5996080aa89589cb5db0e879b56e348dc81d8561501d2716，与开始时相同。上轮新增测试从6增至7。原压力/spawn测试未修改。

## 安全与交付清单

生产改动仍仅上轮ai/brain.py的重试与缓存。待交付四文件：ai/brain.py、tests/test_brain_reflection_commit_retry.py、docs/ROUND3_BRAIN_CONCURRENCY_FIX_REPORT.md、本报告。未暂存任何文件。日志和results.json保留在artifacts/brain-final-review，旧日志不删除。没有操作tests.zip、生产数据库、凭据、main、远端或PR。
对源码、新测试和上轮报告检查常见GitHub令牌、私钥头及硬编码API凭据模式，匹配0；扫描不是绝对无泄漏证明，结合实际差异人工复核均为Mock、任务UUID和文件哈希。完整命令、时间与退出码由results.json记录。

## 本轮回归结果

本轮本地验收 PASS，具备将这四个文件提交到当前开发分支的条件，仍等待用户确认；没有执行git add/commit/push或创建/合并PR。

| 项目 | 结果 |
|---|---|
| 新增提交专项 | 7 passed，1.74秒 |
| Brain全部相关 | 49 passed，0 failed，7.21秒 |
| 压力第1/2/3次 | 每次3 passed，11.14/10.95/10.69秒，原30秒门槛 |
| 完整离线 | 982 passed，0 failed，1条既有弃用警告，88.45秒 |
| 浏览器 | 15个入口全部exit0 |
| TypeScript/Vite构建 | exit0，Vite811ms |
| Windows完整回放 | exit0，一次不中断，三次崩溃恢复 |
| 三次恢复 | 21.141/22.171/22.250秒，原100秒门槛 |

Windows每次均保留272成交、精确NAV943.8943549007662容差、86400秒、1441分钟时间点、不缺失/不重复、integrity_check=ok、恢复账本与不中断基准一致。专项为全量子集，不累加作总数。

| 验收 | 开始 | 结束 | 退出码 |
|---|---|---|---|
| brain | 2026-11-13T19:26:42.452937+08:00 | 2026-11-13T19:26:50.461830+08:00 | 0 |
| stress-1 | 2026-11-13T19:26:50.462881+08:00 | 2026-11-13T19:27:02.342849+08:00 | 0 |
| stress-2 | 2026-11-13T19:27:02.343931+08:00 | 2026-11-13T19:27:14.099551+08:00 | 0 |
| stress-3 | 2026-11-13T19:27:14.100593+08:00 | 2026-11-13T19:27:25.767656+08:00 | 0 |
| offline | 2026-11-13T19:27:25.769297+08:00 | 2026-11-13T19:28:55.332871+08:00 | 0 |
| browsers | 2026-11-13T19:28:55.333870+08:00 | 2026-11-13T19:31:16.051822+08:00 | 0 |
| build | 2026-11-13T19:31:16.052863+08:00 | 2026-11-13T19:31:18.422024+08:00 | 0 |
| windows | 2026-11-13T19:31:18.423028+08:00 | 2026-11-13T19:33:33.808289+08:00 | 0 |

所有完整执行命令及时间记录见artifacts/brain-final-review/results.json；浏览器逐项日志同目录browsers/。原artifacts/brain-concurrency-final/results.json和历史失败日志保留。生产文件哈希在本轮结束时再次确认不变。

## 最终交接

缓存容量1在当前串行领取不变量下安全，两个不同有效任务不会同时进入chat；确定性双任务测试证明两笔原结果都完成，没有重复Provider或丢失有效结果。不宣称任意时钟倒退、人工制造多有效租约或未来启用并行chat仍安全；若改变领取约束，需要重新设计缓存。本轮不修改时钟或租约机制。
当前工作树：M ai/brain.py；新增tests/test_brain_reflection_commit_retry.py、docs/ROUND3_BRAIN_CONCURRENCY_FIX_REPORT.md、docs/ROUND3_FINAL_REVIEW.md。原修复报告保留上轮981项历史实测，本报告明确最新为982项。HEAD不变，未修改main，没有新增远端CI结果。整个v0.1 Stable和历史CI唯一归因不因本轮通过而自动验收。
提交准备结论：四文件范围已复核，git diff --check通过，敏感模式检查0匹配，无依赖、运行库、凭据或测试日志在待交付清单中。等待用户批准提交，暂不暂存/提交/推送/创建PR/合并。
