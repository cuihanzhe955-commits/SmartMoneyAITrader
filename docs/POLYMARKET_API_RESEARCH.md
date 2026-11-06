# Polymarket能力核验索引

当前仅公开只读：Gamma市场发现/精确ID、CLOB盘口/费用参数、Data API官方结算。网络GET白名单、有界体积、超时、禁止重定向；没有钱包、签名订单、下单或撤单路径。

F1–F5.1历史证据见[公开研究](PHASE_F_READONLY_RESULTS.md)、[成本模型](PHASE_F4_COST_RESEARCH.md)、[研究记录](PHASE_F5_OBSERVATIONS.md)。本轮研究、参考模拟、官方结果与Brain闭环见[F阶段验收](PHASE_F_RESULTS.md)。

| 能力 | 当前状态 |
|---|---|
| 二元v1元数据、结果Token、公开盘口 | 已实现；新鲜度/身份与精度核验 |
| 指数1 taker费用曲线 | 已核验官方公式与实时参数，实际扣费尚未核验 |
| 原生最小单位/抵押资产 | 未完成执行验收；Gamma名义金额与CLOB数值分开说明 |
| 参考成本模拟 | 本地独立资金账本与假设，不冒充平台忠实执行 |
| 官方结算 | 仅完整已完成向量；micro-USDC整数换算，未知/未决不猜结果 |
| 链上兑付、账户资格、签名、真实订单 | 未验收/未启用 |
| v2 Position ID/其他费用曲线 | 未支持，不误用v1 Token |
| Gate事件 | 默认禁用，契约保留，能力unverified |

官方依据：[市场详情](https://docs.polymarket.com/market-data/market-details)、[费用](https://docs.polymarket.com/trading/fees)、[CLOB规则](https://docs.polymarket.com/api-reference/markets/get-clob-market-info.md)、[官方结算Schema](https://docs.polymarket.com/api-reference/markets/get-resolution-state.md)。文档复核不替代账户准入和真实交易验收。
