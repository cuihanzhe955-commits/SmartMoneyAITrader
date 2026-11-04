# D 阶段开源组件最终采用决定

日期：2026-11-04。按主计划第3、6节完成最小原型、兼容性、许可、版本及回滚评审。本文件不扩大执行平台、账户或资金权限。

| 组件 | 决定 | 已有实证 | 兼容与撤销边界 |
|---|---|---|---|
| CCXT 4.5.91 | 保留已有适配器和当前版本 | 三所原生签名、K线、余额、精度、异常不重试 POC；OKX 公开行情实际读取；现有订单/保护 Mock 回归 | Gate 仅研究/协议原型，未启用生产交易；撤销新增研究模块即可保留原适配器 |
| TA-Lib Python/C 0.8.3、NumPy 2.5.4 | 仅采用研究参考，不替换原策略 | Windows CPython3.12 原生库对照13组数据、11,752个值；预热、横盘、NaN拒绝、前缀因果性验证 | 标准 RSI/ATR/EMA 与原策略口径不同；卸载可选研究环境不影响日常程序；不分发其原生二进制 |
| Pydantic AI | 按计划的条件条款暂不引入 | 保留现有 Provider + Pydantic2.14.2；双角色、严格Schema、超时、取消、过期拒绝和规则回退已有测试 | 未安装该库，不声称验证了它的 Windows ABI 或全部工具调用；当前没有引入第二套 Agent 调度器的必要 |
| Lightweight Charts 5.2.1 | 采用独立 React 原型组件 | 净值、K线、成交标记、账本回放、主题、故障回退与10万点压力验证 | 回放只读，不暂停或驱动交易；实时未保存K线不伪造成历史；保留 LICENSE、NOTICE、图内署名及链接 |
| Freqtrade | 研究参考，不复制或安装 | 阅读官方策略、预热和未来数据说明；对照本项目指标因果性和闭盘验证 | GPL-3.0；没有把框架或策略代码搬入主工程，不改变本项目许可或数据模型 |
| Hummingbot | 研究参考，不复制或安装 | 阅读 Controller/Executor 分工、市场数据和执行器信息结构；对照本项目既有独立订单/保护通道 | Apache-2.0；不引入第二个执行器/数据库体系 |
| Jesse | 研究参考，不复制或安装 | 阅读官方研究、回测及交互图表说明；本项目回放仍直接读取自己的归档和账本 | MIT；不使用其执行器替换现有账本，不引入其优化/机器学习服务 |

## 研究资料快照

以下为本轮读取官方资料时查询到的仓库提交；只固定本轮证据，不固定未来必须使用的最新版本。

- `freqtrade/freqtrade`：`7d9717cdf86595e96fbedaa981a01c0636ee87c2`（develop，2026-11-03T18:51:05Z）。
- `hummingbot/hummingbot`：`9af100d6822da7d2d0291a906c730ef172284ee2`（master，2026-09-22T08:53:54Z）。
- `jesse-ai/jesse`：`8665b253d43af7b06a88c6ebcda7a0b6393ec937`（master，2026-11-03T14:41:46Z）。
- `pydantic/pydantic-ai`：`2b8123be8f11842896a3a736529e750b86310ca6`（main，2026-11-04T14:25:26Z）。

官方材料：

- [CCXT](https://github.com/ccxt/ccxt)、[TA-Lib Python](https://github.com/TA-Lib/ta-lib-python)、[TA-Lib C](https://github.com/TA-Lib/ta-lib)
- [Pydantic AI](https://github.com/pydantic/pydantic-ai)
- [Lightweight Charts 5.2.1](https://github.com/tradingview/lightweight-charts/tree/v5.2.1)
- [Freqtrade 策略和预热说明](https://www.freqtrade.io/en/stable/strategy-customization/)、[GPL许可](https://github.com/freqtrade/freqtrade/blob/develop/LICENSE)
- [Hummingbot Controller](https://github.com/hummingbot/hummingbot/blob/master/hummingbot/strategy_v2/controllers/controller_base.py)、[Apache许可](https://github.com/hummingbot/hummingbot/blob/master/LICENSE)
- [Jesse README](https://github.com/jesse-ai/jesse)、[MIT许可](https://github.com/jesse-ai/jesse/blob/master/LICENSE)

## 阶段边界

D 验收的是组件原型和采用决定，不是把七套框架全部安装。原型可运行不等于交易平台和真实资金验收通过。异步市场调度、动态模拟准入、多平台切换及其账户隔离继续作为 E/可靠性集成待办；完整 AI、Brain、通知和 UI 仍按 F–H 及主计划实施。
