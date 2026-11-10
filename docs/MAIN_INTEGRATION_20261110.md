# Windows 实例隔离与 main 集成状态（2026-11-10）

本次按项目所有者明确授权，将现有 G1、Windows 实例隔离修复与 G2 通知检查点汇总到 main。此授权不代表 Stable 发布或真实账户验收通过，也不启用双 AI 或真实资金权限。

## Windows 修复

- 服务直接绑定端口 0 并保持监听 socket；测试不再先选端口再释放。
- 唯一实例 ID、PID 与就绪记录校验；隔离写请求及专属停止路由核对实例。
- Windows Job 管理 suspended 启动的进程树，启动失败、超时和父进程退出后均清理所属子进程，不按端口查杀。
- 保留 start.bat/start.cmd/stop.bat 默认入口及已有退出风控。

## 集成前实际验证

- 后端 868 passed，0 failed，0 skipped；其中新增隔离测试 15 项。
- 相关定向 61 passed；G1 合同与打包测试 117 passed（均为全量子集）。
- Windows 实际启动、停止、中断重启通过：272 fills，NAV 943.8943549007662。
- TypeScript/Vite、图表数据、G1/事件研究/Brain 浏览器通过。
- G2 通知按渠道隔离的历史定向结果为 86 passed；不能当作合并后结果。

## 未解决的验收阻碍

- protection_browser.py 等待第二条“核对完成 · 已释放”超时；复测还出现旧脚本 bind/health 异常。
- replay_browser.py 的 86401 点压力场景出现 Node driver 内存分配失败。
- 同一压力日志中 G1 工作线程遇到 Brain 数据库忙异常并退出，仍需排查。
- acceptance_browser.py 退出码 0，但含 ConnectionResetError，不视为零异常。
- 本次未完成正式发布打包、干净 Windows 机器、真实 AI 或真实账户验证。

因此上一轮整体自主验收结论仍为 FAIL。合并用于保存最新开发成果，不改变该结论。

完整本地报告、日志、临时数据库、安装目录和用户路径不进入公开提交。
