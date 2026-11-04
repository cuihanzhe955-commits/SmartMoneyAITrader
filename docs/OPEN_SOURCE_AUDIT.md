# D 阶段组件审查与采用边界

日期：2026-11-04。开发检查点，非 Stable；未访问真实交易账户或提交订单。

| 组件 | 本轮实际版本 / 许可 | 实际动作 | 采用结论与剩余门槛 |
|---|---|---|---|
| CCXT | 4.5.91 / MIT | 保留原适配器；三所原生客户端在拦截 HTTP 下验证现货 IOC 签名、K 线、余额、精度与异常不重发 | 保留依赖；不据此启用 Gate 或声称平台联调通过。市场发现研究已完成 [D3](PHASE_D3_DISCOVERY.md)；实际执行接入与平台返回仍需逐项验收；协议对照见 [D2](PHASE_D2_CCXT.md) |
| TA-Lib Python / C | 0.8.3 / BSD-2-Clause、BSD-3-Clause | 独立 Windows CPython 3.12 wheel 实测；13 组数据、11,752 个指标值对照 | 仅研究依赖；不替换生产策略。不在源码包分发 wheel 或原生库 |
| NumPy | 2.5.4 / BSD-3-Clause | 与 TA-Lib 隔离 POC 配合；研究依赖固定版本 | 生产程序无需安装；其他 Python/Windows 架构尚未验证 |
| Pydantic AI | 未安装；上游 MIT | 评估现有 Provider 双角色、Pydantic 严格 Schema 及既有异步故障测试 | 条件引入项暂不采用。现有流程足够本轮需要，避免增加第二套调度框架；不声称执行了该库兼容 POC |
| Lightweight Charts | 5.2.1 / Apache-2.0 + NOTICE | 拆分独立 React 净值组件、数据整理、主题与同长度刷新修复 | 保留已有依赖；保留图内署名、可见链接、LICENSE 与 NOTICE。性能压力、完整 K 线与交易回放仍待后续验收 |

## 指标兼容性

原 RSI 是最近 14 次涨跌幅汇总、ATR 是最近 14 次真实波幅均值；原 EMA 使用最近 60 根首价作为初始化。研究模块使用 Wilder RSI/ATR 和均值初始化 EMA，因此不能默认为等价替换。

标准实现仅供研究；当前策略仍执行原口径。参考值来自实际 TA-Lib 0.8.3 原生库（该版本横盘 RSI 返回 50），包含预热空值、单调、横盘、冲击和随机序列，以及项目所附八币种公开历史归档。最大绝对误差：EMA 7.28e-12、RSI 3.56e-14、ATR 5.69e-14。比较不证明任何盈利优势。

可选研究环境：在独立虚拟环境安装 `requirements-research.txt`，运行：

```powershell
python scripts/verify_indicator_reference.py --reference-path <研究环境的site-packages> --output <报告.json> --golden <参考值.json>
```

本轮 Windows wheel：`ta_lib-0.8.3-cp312-cp312-win_amd64.whl`；SHA256：`233d78abdd31df3ab91c04dccd4aaa0fdb127c3ab1cce0765476526adf27344b`。生产代码不导入 TA-Lib；日常使用研究面板无需安装它。已提交的参考向量支持离线回归。

## 供应链与许可

- 前端直接依赖固定为现有 lockfile 的精确版本，未升级解析版本；使用 `npm ci` 重现。2026-11-04 `npm audit --omit=dev --json` 返回 0 条已知漏洞。这不覆盖所有 Python 依赖，也不是无漏洞证明。
- CCXT、Lightweight Charts 的许可证文本保留在 `third_party/`。图表在 UI 中保留 TradingView 链接；重分发应继续保留许可与 NOTICE。
- TA-Lib/NumPy 为可选研究下载，不随源码导出原生二进制。未来如捆绑为 EXE，必须另行审查所有实际分发库及 C 运行时许可。
- Freqtrade、Hummingbot、Jesse 仍是参考候选，本轮未复制或集成其代码，不据此宣称完成架构研究。
- 本轮没有对全部 Python 间接依赖作漏洞扫描，没有证明跨版本 ABI 兼容。D 阶段是部分完成，不关闭整体阶段门槛。

## 官方来源

- [CCXT 源码与许可](https://github.com/ccxt/ccxt)
- [TA-Lib Python](https://github.com/TA-Lib/ta-lib-python)、[C 库](https://github.com/TA-Lib/ta-lib)、[PyPI 元数据](https://pypi.org/pypi/TA-Lib/0.8.3/json)
- [NumPy 许可](https://github.com/numpy/numpy/blob/main/LICENSE.txt)
- [Pydantic AI](https://github.com/pydantic/pydantic-ai)
- [Lightweight Charts](https://github.com/tradingview/lightweight-charts)、[5.2.1 NOTICE](https://github.com/tradingview/lightweight-charts/blob/v5.2.1/NOTICE)
