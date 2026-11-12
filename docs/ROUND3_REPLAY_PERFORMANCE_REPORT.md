# 第三轮恢复回放吞吐专项

日期2026-11-12。原始基线5b45e9adb6edd67f0795820d2109d31c6526297e；唯一分支feat/v0-1-first-release-completion。源码HEAD见本报告所在提交；后续CI状态按对应HEAD核验。

## 原因及测量

原CI run43149616347源码69ef2d0：后台仍有心跳，100秒时剩94分钟。不是已证明的数据损坏；证据指向推进吞吐不足。

本地原始cProfile真实24小时回放：76.779秒、1441次tick、COMPLETED。tick累计18.391秒（12.76毫秒/步），scan12.167秒（8.44毫秒/步），11528次analyze9.401秒；SQLite连接事务退出1.317秒（0.914毫秒/步）；historical切片未进入前25热点。profile包含分析器开销，非无开销延迟分布。后台固定每步wait(.04)额外约57.6秒，Windows等待粒度、计算及磁盘开销进一步影响CI。没有证明全部CI差异仅由sleep造成，但移除积压时固定等待是测量支持的主要优化。

原始日志artifacts/replay-profile.log；基准脚本artifacts/replay-profile.py。SQLite始终WAL+synchronous=FULL，没有降低持久性、合并事务或减少记录。

## 修改

terminal/runtime.py增加replay_delay：只对RUNNING、paper、history、规则引擎、speed>1且next_scan已经到期的任务，用可中断1毫秒等待代替40毫秒。每次仍调用原tick，逐分钟、全8交易对，原风险/决策/成交/独立提交保持。每步释放锁，未推进到未来分钟；public、实盘、AI、暂停及正常速度保留原等待。无大范围重构。

SMART_MONEY_ACCEPTANCE_TRACE=1启用每秒JSONL诊断，写入独立runtime/acceptance-performance.jsonl；仅字段白名单，不记录资金、持仓、密钥或配置。记录elapsed、pid、生命周期、t/next_scan/deadline/heartbeat、累计分钟、吞吐、平均tick时长与报告标识。average_tick_duration不是average_scan_duration，不混淆两个口径。scan/提交热点由cProfile单独测量；当前没有逐次scan/提交P95/P99分布，后续可继续补充，未据此放宽超时。scans_per_second是该进程存活时间内累计分钟数比值，重启时含已恢复分钟，不能当严格恢复后增量吞吐。

tests/windows_smoke.py增加未中断基线及连续三轮实际启动4秒后强制终止/重启，保留100秒等待上限和原结果断言，新增1441连续时间点无重复缺失、86400秒跨度、integrity_check及完整成交账本一致性。新增SQLite只读连接显式关闭，避免Windows临时文件占用。新增tests/test_replay_pacing.py七种边界及FULL设置断言。

## 实测

首次修复后完整三轮恢复：22.375 /25.109 /24.578秒，未中断26.266秒。
最终脚本再跑：未中断30.031秒、首次启动3.588秒；恢复三轮27.735 /24.375 /24.515秒，重启初始化4.040 /3.555 /3.335秒。恢复等待计时从重启就绪后开始，不包含前4秒或启动时间。该批同时运行全量/浏览器，存在本机负载差异；三点不足估计可靠P95/P99，报告全部样本及最大值，不伪称统计置信度。

两批三轮均COMPLETED，fills272，nav943.8943549007662（误差<1e-7），报告跨度86400，1441分钟完整，integrity_check=ok，最终成交t/symbol/kind/完整data逐条等于该批未中断账本。日志artifacts/replay-three-fixed.log、replay-three-final.log；JSONL留存artifacts/replay-traces/。

975 passed/0 failed/1 warning（107.89秒），含七项新增调度边界，日志artifacts/replay-full-final.log。全部15浏览器exit0，日志replay-browsers-final.log；npm ci及TypeScript/Vite构建成功（678毫秒），start.bat --install-only成功。未连接生产交易接口、读生产凭据或操作tests.zip/历史数据库。

## 结论与剩余限制

本地性能/账本一致性PASS，达到原100秒要求；原结果完整保留。100秒是现有smoke验收预算，未发现其为用户产品SLA的证据。本次没有修改该预算，也没有用更长等待掩盖吞吐。

推送后需核对Windows CI：workflow原有windows_smoke入口现在自身跑未中断+三轮恢复，保留全部断言。新CI尚未返回前不能声称远端PASS。第三轮其他遗留连接关闭异常、偶发保护刷新及整包升级回滚缺口不由本性能修复自动关闭。BrainBusy退避日志保留，未过滤。原始失败日志replay-three.log保留；它是验收新增SQLite连接未close导致清理失败，非成交结果失败。

最终CI链接和提交SHA以之后追加的核验记录为准；main及PR10 Open/Draft保持原样。

## CI补充

run43226262715（c0aebf6）及run43228277267（c2628e5）先后暴露旧压力辅助函数在无轮次/预留扫描时间下的错误假设；修正仅针对合成压力时钟和有界重试，最终20轮和全部唯一性断言保留，不影响真实恢复计时。6a3533e本地975通过；Windows run43229744883也975通过（333.77秒），浏览器14通过/1失败（prediction_challenge_browser），后续恢复测试被跳过。日志artifacts/replay-ci*.log保留。

因此增加独立replay-performance job，直接在Windows2022/Python3.12.2新环境安装并运行同一个windows_smoke（未中断基线+三轮真实进程崩溃恢复+全部100秒/成交/净值/分钟/完整性断言），留存JSONL。原regression job及其失败不被绕过或改为通过。此项保证专项性能证据不被其他浏览器失败遮挡。
