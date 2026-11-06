# F1–F3 事件研究只读实现与验证记录

补录日期：2026-11-06。记录对应已上传代码，不把本次补文档当成新增功能。

## 检查点与实际结果

| 检查点 | 源码提交 | 当次离线回归 | 已实现 |
|---|---|---|---|
| F1 | [370b6b2](https://github.com/cuihanzhe955-commits/SmartMoneyAITrader/commit/370b6b266884b70ab020da22d9b979d2f76e2f7f) | 624通过、0失败，31.49秒 | Polymarket公开市场发现、市场/条件/结果Token映射、分页/缓存/拒绝提示及策略实验室入口 |
| F2–F3 | [0491e4c](https://github.com/cuihanzhe955-commits/SmartMoneyAITrader/commit/0491e4c08a0f0ba83771a64f89abd4347c66c9b7) | 692通过、0失败，40.78秒 | 绑定市场与Token的公开盘口、基准费率、关闭市场筛选及官方结算证据查询 |

这些是Windows CPython 3.12下的本地隔离测试。外部网络由离线运行器禁止；公开API探测另外执行；没有GitHub Actions CI或真实账户成交认证的含义。保留一项Starlette/httpx弃用提示。F阶段整体尚未完成，版本仍是开发检查点，不能标Stable。

## F1：市场发现

- Gamma官方公开GET；仅固定HTTPS域名和路径，不读取密钥，不跟随重定向，不使用环境代理。
- 每页1–50条，1–3页；关键词只在读取样本内筛选，slug可精确指定；不宣称全市场完整发现或存在指定5分钟市场。
- 市场ID、事件ID、条件ID、两个结果及Token按原顺序保留；非法或重复映射拒绝或去重；外部标题按不可信文本处理。
- 元数据缓存30秒、最多8组查询；返回深拷贝，失败不以过期缓存冒充成功；关闭不等待网络。
- 未提供或未核验的字段保留未知，不把元数据价格当可成交报价，不假定结算资产或手续费为零。

## F2：盘口与基准费用参数

- 先按官方市场ID重新读取单市场元数据，再按对应结果Token读取订单簿，核对条件和Token身份。
- 检查源时间小于30秒、快照哈希、价格档位、最小份额、数量和价格有效性、重复档位、交叉盘口；归一化排序后展示前20档。
- 单边或空盘口可明确展示，但不宣称双边报价可用。三秒缓存保留原始源时间，缓存不会让旧盘口变新。
- 读取官方`base_fee`参数，以bps原值显示。**该参数不是完整费用模型，尚未核验费用曲线与实际扣费，因此模拟准备状态仍为false。**
- 盘口和结算各自有界、互不等待；无钱包、下单、撤单、授权或真实资金接口。

## F3：官方结算证据

- 支持开放/已关闭市场筛选。已关闭不等于已结算；按精确市场ID取得元数据，避免开放市场列表过滤掉关闭记录。
- 官方Data API `/v2/resolutions` 按条件ID查询。空记录、未知/待决/争议状态、缺失兑付字段或缺失/未来完成时间均不能变为已核验结算。
- 官方Schema的兑付数组单位为每份额micro-USDC整数；校验两个结果、非负范围与总额1,000,000，保留原向量并按固定单位转换，不能根据向量总额猜缩放比例。
- `[500000,500000]`按官方50/50兑付向量处理，不强制判某一结果胜出；不以现货K线、盘口价格或标题代替结算。
- `settlement_verified=true`仅指官方API身份、状态、时间和兑付向量校验通过；`onchain_verified=false`保持独立。未进行实际资金兑付，也未完整核验市场抵押资产。

## 真实公开探测与浏览器证据

- F1公开只读探测读取并校验5个市场；未访问账户，无订单写入。
- F2在两个公开市场读到新鲜双边盘口，官方基准费率为1000bps；静默市场的旧盘口也曾被拒绝，没有放宽源时间门槛。
- F3曾在公开市场6742367、6742336读到`resolved`和完整micro-USDC向量，通过官方API证据校验；其他`resolved`记录缺少兑付字段时仍返回未确认。上述为当时观察，不保证当前接口或市场状态相同；未将原始HTTP快照提交仓库。
- TypeScript/Vite构建通过。Playwright实际打开临时服务，明确使用合成平台数据，检查1366×768、1920×1080及深浅主题、Token详情、结果切换、盘口/费用/结算显示、关闭市场筛选、加载/空数据/失败提示和外部文本不执行；会话状态保持不变。截图在本地验收目录保留，不作为真实平台回报。
- 构建保留既有包体积和依赖模块指令提示，未为消除提示而更改依赖。

## 修改范围与复验

核心文件：`market/predictions.py`、`market/event_details.py`、`terminal/api.py`、`frontend/src/event-research.tsx`及策略实验室入口、前端构建产物。测试：`tests/test_event_research.py`、`tests/test_event_details.py`、`tests/event_research_browser.py`。

```powershell
python -X utf8 -B tests/run_offline.py
npm --prefix frontend run build
$env:SMART_MONEY_UI_OUTPUT = "<项目外截图目录>"
python -X utf8 -B tests/event_research_browser.py
```

本轮没有数据库结构迁移，用户运行数据库及凭据未改。可恢复对应Git检查点的源码/构建产物；不要回退用户数据库来清除未知订单。敏感内容扫描只发现0个已知模式匹配，不代表绝对不存在泄露。

## 未完成项与下一步

当前实现以clobTokenIds字段映射CTF结果；尚未验证Protocol V2的positionIds或所有协议版本兼容，未知映射不宣称支持。完整费用曲线和逐档成本预检、可追溯事件模拟账本与幂等结算、AI预测/复盘、Brain长期记忆及检索/对照评估、100轮挑战尚未交付。下一步先核验费用与成本边界，再允许建立事件模拟闭环。Gate事件接口继续待验证、默认禁用。C/E外部平台及真实资金门槛不因本记录关闭。

操作见[Polymarket研究使用说明](POLYMARKET_RESEARCH.md)，结构化结果见[F_TEST_RESULTS.json](F_TEST_RESULTS.json)。官方协议依据：[市场发现](https://docs.polymarket.com/api-reference/markets/list-markets)、[单市场](https://docs.polymarket.com/api-reference/markets/get-market-by-id)、[盘口](https://docs.polymarket.com/api-reference/market-data/get-order-book)、[基准费率](https://docs.polymarket.com/api-reference/market-data/get-fee-rate)、[结算状态及Schema](https://docs.polymarket.com/api-reference/markets/get-resolution-state.md)。
