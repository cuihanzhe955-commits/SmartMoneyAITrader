# 项目文档导航

> 适用范围：Smart Money AI Trader 公开仓库。文档状态以具体版本、日期和测试证据为准。
> 本页是**文档入口**，不是新的开发计划，也不代表功能已通过验收。

## 建议阅读顺序

1. **首次了解项目**：[仓库首页](../README.md) → [v1.0 公开路线图](V1_ROADMAP.md)。
2. **希望运行软件**：[完整使用说明](../使用说明.md) → [Windows 快速启动](WINDOWS_QUICK_START.md)。
3. **需要判断当前真实完成度**：[阶段与验收口径](PROGRESS_STATUS.md) → [C2 工程验收记录](PHASE_C2_DIAGNOSTICS.md) → [C3 联调准备](PHASE_C3_READINESS.md) → [D1 组件记录](PHASE_D_COMPONENTS.md) → [实盘验证状态](LIVE_TRADING_VERIFICATION.md)；[C1 记录](PHASE_C1_RESULTS.md)保留为历史证据。
4. **查看尚未采用的新想法**：[产品决策池](PRODUCT_DECISION_POOL.md)。

## 文档按职责划分

| 类型 | 当前文件 | 主要职责 |
|---|---|---|
| 项目介绍 | [README](../README.md) | 产品定位、核心模块、公开状态及快速开始 |
| 公开开发计划 | [V1_ROADMAP.md](V1_ROADMAP.md) | v1.0 A–I 阶段、目标和验收边界的公开摘要 |
| 用户操作 | [使用说明](../使用说明.md)、[WINDOWS_QUICK_START.md](WINDOWS_QUICK_START.md) | 使用方法、启动与排障 |
| 验收证据 | [PHASE_C1_RESULTS.md](PHASE_C1_RESULTS.md)、[LIVE_TRADING_VERIFICATION.md](LIVE_TRADING_VERIFICATION.md) | 历史阶段测试结果与实盘未通过项 |
| 已发生的功能变更 | [CHALLENGE_TEMPLATE_UPDATE.md](CHALLENGE_TEMPLATE_UPDATE.md) | 挑战模板 UI 调整的历史记录 |
| 仓库维护 | [GITHUB_UPLOAD.md](GITHUB_UPLOAD.md) | 公开仓库状态及上传说明的历史兼容信息 |
| 未来候选 | [PRODUCT_DECISION_POOL.md](PRODUCT_DECISION_POOL.md) | 新模块、研究方向及延后理由，**不构成当前开发指令** |

## 状态与优先级

- **计划**回答“准备做什么”；**验收记录**回答“实际上证明完成了什么”；**决策池**回答“将来可能做什么”。三者不可混用。
- 公开 v1.0 路线图不扩充原定功能范围。新增想法先评估是否属于既定阶段，再决定是否进入未来候选。
- C1 是开发检查点；真实资金成交闭环和交易所托管保护单全生命周期尚未在公开证据中通过验收。不能用模拟回放、Mock 测试或 UI 展示替代。
- 某次阶段报告是**历史记录**，其测试数量和当时状态不可不加说明地当成当前源码的重新验证结果。
- 公开仓库仅存放适合对外披露的说明。不要提交私有密钥、用户运行数据库、本机工作目录、内部执行指令或个人数据。

## 现有目录结构

```text
SmartMoneyAITrader/
├── README.md                 # 项目首页
├── 使用说明.md               # 用户手册
├── docs/                     # 本页归档与文档导航
│   ├── README.md
│   ├── V1_ROADMAP.md
│   ├── PHASE_C1_RESULTS.md
│   ├── LIVE_TRADING_VERIFICATION.md
│   ├── PRODUCT_DECISION_POOL.md
│   ├── WINDOWS_QUICK_START.md
│   ├── CHALLENGE_TEMPLATE_UPDATE.md
│   └── GITHUB_UPLOAD.md
├── market/                   # 行情获取与导入
├── strategy/                 # 指标、规则与策略组合
├── ai/                       # AI 提案与异步协调
├── risk/                     # 仓位与风险约束
├── execution/                # 模拟/交易所执行与订单状态
├── challenge/                # 策略实验生命周期与报告
├── events/                   # 持久化事件账本
├── terminal/                 # 本机服务与会话调度
├── frontend/                 # React / TypeScript 工作台
├── tests/                    # 自动化测试
├── scripts/                  # 启动及源码打包辅助脚本
├── data/                     # 受控的历史数据与市场规则样本
└── assets/                   # 静态资源
```

**兼容性决定：** 当前不物理移动或重命名已有文档和程序目录；现有 README 链接、历史文档引用、测试与源码打包白名单依赖这些路径。以后确需迁移时，应单独审计引用、更新打包规则并完成回归测试。
