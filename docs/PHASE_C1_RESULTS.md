# C1 工程验收记录

日期：2026-11-03。阶段 C 的无需资金授权部分完成；阶段 C 整体验收尚未通过。

## 实际修改

- execution/venue.py：提取权限和市场检查；OKX 7 类条件单清单完整分页，未知或不可读时拒绝入场；成交历史按 billId 分页，最多 20 页，重复、错误、错单或缺少费用全部拒绝结算。
- execution/health.py：只读检查账户身份、资金匹配、规则、行情、条件单、数据库与未确认订单；检查期间账户、配置或持仓变化时作废；结果不能修改授权或启动状态。
- terminal/runtime.py、terminal/api.py：新增只读检查入口和 acceptance_reports 持久化表，检查网络请求在数据库锁之外；重复点击不并发运行。
- frontend/src/forms.tsx 及 frontend/dist：设置页增加只读健康检查、逐项结果、明细和本机 JSON 导出，刷新后可重新显示最近结果。
- scripts/build_source_package.py、.gitignore：白名单源码导出、归档复扫、清单哈希，禁止覆盖或在主工程内构建发布目录。
- tests/test_acceptance.py、tests/test_package.py、tests/acceptance_browser.py：新增分页故障、只读隔离、检查快照变化、未知订单、重启恢复和发布清理测试。
- README.md、使用说明.md、GitHub 上传和实盘验收说明同步当前行为。

## 验证

执行命令：

- python -B tests/run_offline.py
- 在 frontend 执行 npm run build
- python -B tests/acceptance_browser.py
- python -B scripts/build_source_package.py

自动化回归：106 通过、0 失败，其中原有 74 项与新增 32 项。现有 FastAPI TestClient 有一项弃用提示。

前端 TypeScript 与生产构建通过。存在已有的大包体积和第三方 use client 指令提示，不影响本轮构建。

导出的干净源码目录再次独立运行同一套 106 项回归，全部通过。实际 Windows 启动器完成中断回放、重新启动、结算和安全停止，仍为 272 笔成交、净值 943.8943549007662；这是历史模拟回放，并非真实账户收益。

Chrome 实际打开界面：1366×768、1920×1080、深浅色均完成截图；只读检查、余额阻断、结果刷新恢复、JSON 下载通过，无页面脚本错误。测试使用临时数据库与明确的 Mock 账户读取，未向真实账户下单。首次浏览器脚本未正确返回设置页，已修正并复跑通过。

## 数据和回滚

数据库变更仅新增 acceptance_reports 表；历史会话、订单与成交表不做删除或覆盖。开发测试均在临时目录，原 runtime 保留。本轮开始前已核验 Phase 4 检查点 SHA-256，并建立独立工程和私有 runtime 备份，具体本机路径记录在 docs/phaseC_baseline.json（此文件不进入公开源码包）。

回滚前安全停止并备份最新 runtime。把本轮开始前 project.zip 恢复到新目录核对，再切换启动位置；保留原 runtime，不用旧数据库覆盖之后发生的成交记录。新增表可保留，旧代码不会读取。遇到真实订单状态不明，先在交易所核对，不通过恢复旧库清除未知状态。

## 尚未通过的门槛

1. 未获本轮真实资金试单授权，未读取用户实际私有账户、未执行真实成交闭环。
2. 托管保护单生命周期尚未完整实现与验收，当前明确为本地止损。识别到外部条件单即阻止自动入场，不会宣称已托管保护。
3. Binance 条件单清单未在本轮完整实现；只读验收会显示阻断。多平台切换、动态全市场、AI Memory、开源组件审计及后续 UI 集成属于后续阶段。
4. 干净 Windows 机器安装及真实平台模拟环境联调本轮未完成。源码包含编译前端和安装器，不是独立 EXE；这不是 Stable 发布包。

本轮未推送 GitHub、未公开仓库、未发送通知到外部联系人。GitHub 上传由用户按指引操作。
