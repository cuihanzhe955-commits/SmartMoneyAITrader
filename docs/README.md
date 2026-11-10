# 项目文档导航

> 文档按用途组织。计划说明目标，验收记录说明已经证明的事实，决策池记录延后候选；三者不可混用。

## 推荐阅读顺序

1. 首次了解项目：[仓库首页](../README.md) → [产品路线图](V1_ROADMAP.md)。
2. 安装和运行：[完整使用说明](../使用说明.md) → [Windows 快速启动](WINDOWS_QUICK_START.md)。
3. 了解当前真实状态：[项目进度](PROGRESS_STATUS.md) → [集成阻断记录](MAIN_INTEGRATION_20261110.md) → [实盘验证状态](LIVE_TRADING_VERIFICATION.md)。
4. 了解产品目标：[主实施计划 §16.12](SmartMoney_Stable_Plan.md) → [产品决策池](PRODUCT_DECISION_POOL.md)。
5. 评估第三方项目：[开源组件评估](OPEN_SOURCE_AUDIT.md) → [组件采用历史决定](COMPONENT_DECISIONS.md)。

## 文档索引

| 文档 | 用途 |
|---|---|
| [README](../README.md) | 产品定位、当前状态、快速开始 |
| [使用说明](../使用说明.md) | Windows 运行、配置和操作说明 |
| [Windows 快速启动](WINDOWS_QUICK_START.md) | 安装、启动与常见问题 |
| [主实施计划](SmartMoney_Stable_Plan.md) | 当前产品范围、实施顺序与验收标准 |
| [项目进度](PROGRESS_STATUS.md) | 当前代码状态、历史测试证据和未完成门槛 |
| [v1.0 路线图](V1_ROADMAP.md) | 基础版本的产品能力和交付顺序 |
| [产品决策池](PRODUCT_DECISION_POOL.md) | 延后功能和候选方向 |
| [开源组件评估](OPEN_SOURCE_AUDIT.md) | 开源项目筛选、许可证和复用决定 |
| [组件采用历史决定](COMPONENT_DECISIONS.md) | 既有 POC 和采用/不采用证据 |
| [实盘验证状态](LIVE_TRADING_VERIFICATION.md) | 按平台和产品记录真实交易验收边界 |
| [集成阻断记录](MAIN_INTEGRATION_20261110.md) | Windows、G1、G2 集成后的已知问题 |
| [G1 自动预测挑战](PHASE_G1_CHALLENGE.md) | G1 历史实现和测试证据 |
| [G2 通知检查点](G2_OUTBOX_CHECKPOINT.md) | 通知队列、发送状态和生产接入边界 |
| [Brain 记忆设计](BRAIN_MEMORY_DESIGN.md) | 记忆来源、验证和隔离原则 |
| [开发与交付规范](AI_DEVELOPMENT_COLLABORATION.md) | 单一写入者、分支、测试、开源与安全要求 |

## 状态口径

- **已规划**：需求已确认，尚不代表代码存在。
- **已实现**：源码存在，不代表外部平台已经接通。
- **离线测试通过**：指定测试环境/Mock/历史数据通过。
- **平台联调通过**：有目标平台 demo 或受支持接口的可复核证据。
- **真实账户验收通过**：有明确授权及订单、成交、费用、余额、退出和保护状态对账证据。

模拟、Mock、公开只读行情、浏览器展示和文档更新不能替代真实平台验收。

## 兼容与历史记录

阶段报告保留当时测试结果和边界。旧阶段中关于 24 小时挑战的说明属于历史记录；该功能已获准移出产品范围，代码清理需另行完成。G1 自动预测挑战、通知、Brain、回测、实验报告和其他未获准删除的能力继续保留。

公开仓库不得存放密钥、私人数据库、个人账户流水、运行日志或本机工作目录。
