# 最新工程测试报告

日期：2026-11-06；版本1.0-F-research-rc；基线b487a87。

| 检查 | 本轮实际结果 |
|---|---|
| 全量隔离离线 | **814通过、0失败，50.22秒**；新增49项，历史765不改写 |
| F定向故障/恢复/费用/Brain | 148通过、0失败 |
| TypeScript/Vite生产构建 | 通过；无新增依赖 |
| 浏览器研究/Brain | 实际Chrome + Playwright，1366×768、1920×1080，深浅主题；会话/预测/参考成交/结算/评估/纠错/导出/恢复/重载通过 |
| 原事件研究浏览器回归 | 发现、身份、盘口/成本/结算、保存/重载、空数据/加载/错误通过 |
| 已隔离Windows依赖环境 | 锁定版本校验、pip check、启动、临时库、240根回放、正常停止通过；复用既有干净依赖环境，不是新Windows机器安装验收 |
| 真实公开非资金观察 | ETH 6708728预测后获得完整官方结果并结算，SKIP、参与0，参考账本核对通过 |

浏览器和离线交易测试使用临时数据库、合成行情与Model Mock；真实公开观察单独记录，不混为真实AI或资金联调。用户运行数据库、凭据未用于这些测试。截图/原始日志在工程外保留，避免把运行数据或测试备份混入发布包。

复验：

```powershell
python -X utf8 -B tests/run_offline.py
npm --prefix frontend run build
# 将SMART_MONEY_UI_OUTPUT设置到工程外的截图目录后分别运行：
python -X utf8 -B tests/event_research_browser.py
python -X utf8 -B tests/brain_lab_browser.py
```

阶段实现与边界见[PHASE_F_RESULTS](PHASE_F_RESULTS.md)、[BRAIN_MEMORY_DESIGN](BRAIN_MEMORY_DESIGN.md)。保留已有Starlette/httpx弃用和前端模块指令/包体积提示。依赖清单未变，沿用原锁定审查，不声称本轮重新查询漏洞数据库。

未验收：真实Provider连接/策略有效性、平台实际费用和抵押资产、链上与真实资金；完整G/H/I、全新目标Windows安装仍待后续阶段。当前测试通过不意味着Stable。
