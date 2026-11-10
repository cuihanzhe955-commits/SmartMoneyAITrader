# 开源组件评估与采用记录

> 更新：2026-11-10。本文区分“当前已集成”“已有研究结论”和“新一轮候选”。本次更新只确认候选方向与采用规则，没有安装或升级依赖，也没有声称完成新的代码集成。

## 最新采用原则

**先查 GitHub 和当前项目，再决定是否自行实现。** 适合的开源实现可以作为依赖、适配器、独立模块、算法或测试工具使用。不是每项功能都必须从头开发，也不应整套引入另一个交易终端。

每项候选必须先形成简短评估记录：
1. 功能是否直接解决当前已批准的现货/永续、AI、风控、回测、绩效或通知需求；
2. 上游仓库、固定 commit/tag、维护活跃度、issue/安全公告；
3. SPDX 许可证、NOTICE、版权保留、分发义务和是否存在 GPL/AGPL 等 copyleft 风险；
4. Windows、Python/Node 版本、架构、数据库和现有接口兼容性；
5. 与当前模块的重叠、依赖体积、性能、供应链和运行复杂度；
6. 隔离 POC、测试结果、采用/不采用理由及回滚方法。

若现有实现已满足要求，不为使用开源而增加依赖。任何生产依赖新增或替换，必须先给出评估和影响范围，得到项目所有者批准后再集成。

## 当前项目与候选项目

| 项目 | GitHub / 许可证 | 当前判断 | 可评估用途 |
|---|---|---|---|
| CCXT | [ccxt/ccxt](https://github.com/ccxt/ccxt) · MIT | **已集成**（仓库记录版本 4.5.91） | 优先完善现有现货/永续适配，不另建重复交易所层 |
| Lightweight Charts | [tradingview/lightweight-charts](https://github.com/tradingview/lightweight-charts) · Apache-2.0 | **已集成**（仓库记录版本 5.2.1） | 继续复用现有图表组件，保留 NOTICE/署名要求 |
| Pydantic | [pydantic/pydantic](https://github.com/pydantic/pydantic) · MIT | **已集成** | 复用现有 Schema 和数据校验 |
| TA-Lib | [TA-Lib/ta-lib-python](https://github.com/TA-Lib/ta-lib-python) · BSD-2-Clause；C 库 BSD-3-Clause | **研究参考** | 指标对照；未经口径、预热、NaN、Windows wheel 和回归验证，不替换生产指标 |
| Hummingbot | [hummingbot/hummingbot](https://github.com/hummingbot/hummingbot) · Apache-2.0 | **新一轮优先评估候选** | 选择性研究连接器、执行器、订单生命周期和市场数据组件；避免整套引入第二套交易运行时/账本 |
| Jesse | [jesse-ai/jesse](https://github.com/jesse-ai/jesse) · MIT | **新一轮优先评估候选** | 评估策略组织、回测、复盘、统计分析中可隔离复用的部分 |
| Freqtrade | [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) · GPL-3.0 | **研究参考，复制代码前需合规审查** | 策略接口、回测、前视偏差和风控方法；不得忽略 GPL-3.0 对衍生/分发的义务 |
| QuantStats | [ranaroussi/quantstats](https://github.com/ranaroussi/quantstats) · Apache-2.0 | **绩效分析候选** | 净值曲线、回撤和风险统计；先核对输入口径，不替代交易账本 |
| Optuna | [optuna/optuna](https://github.com/optuna/optuna) · MIT | **后续研究候选** | 仅在回测、样本切分和过拟合控制成熟后用于离线参数搜索 |
| Hypothesis | [HypothesisWorks/hypothesis](https://github.com/HypothesisWorks/hypothesis) · MPL-2.0 | **测试质量候选** | 订单状态、风险边界、资金守恒和异常输入的属性测试 |

许可证信息按 GitHub 仓库元数据和 LICENSE 文件作初步核对，实际采用前仍须固定具体 commit 并复核仓库内各子目录、依赖和 NOTICE。上游默认分支变化不等于本项目自动升级。

## 选择性复用边界

- 优先复用小而清晰的组件或库，不把整个外部交易系统搬进来。
- 不同时保留两套交易执行器、两套资金账本或两套策略调度系统，除非有明确隔离实验和量化收益。
- 任何第三方交易代码都必须经过本项目的账户隔离、订单幂等、部分成交、未知订单、费用核算、重启恢复和确定性风控测试。
- 不复制许可证不兼容或来源不清楚的代码；保留版权声明、LICENSE、NOTICE 和修改记录。
- 任何新依赖必须锁版本，评估 Windows 安装、供应链、漏洞和回滚成本。

## 历史 D 阶段审查记录

以下内容保留 2026-11-04 的历史验收证据，不代表 2026-11-10 重新运行依赖审计：

## 当前分发与采用范围

- CCXT4.5.91（MIT）、Pydantic2.14.2（MIT）、Lightweight Charts5.2.1（Apache-2.0 + NOTICE）保持现有版本。
- TA-Lib Python0.8.3（BSD-2-Clause）/C0.8.3（BSD-3-Clause）及 NumPy2.5.4 只用于可选研究参考，未替换生产策略，不捆绑原生库；相应上游许可见官方库及其发行文件。
- Pydantic AI 按主计划的条件引入条款决定不安装；Freqtrade、Hummingbot、Jesse 仅研究，不复制代码。具体理由及研究提交见最终决定。
- CCXT、图表的原有许可文件在 `third_party/`；[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) 收集当前 Windows 已安装依赖的许可文本和文件哈希。上游版权、MPL/Apache/BSD/MIT 等表达式保留，不把全部依赖误标成单一许可。

## 版本与兼容性

`requirements.txt` 精确固定38个现有 Windows 生产依赖，未升级版本；`requirements-research.txt` 固定2个可选研究依赖。前端直接版本和全部解析结果由 package.json/package-lock.json 固定，包含185个锁定节点（含其他平台可选项）。

本轮在两个独立 Windows CPython3.12 x64 虚拟环境成功安装；生产导入、pip check、真实启动器依赖检查通过。`requirements-win-py312.lock` 记录实际验证的 wheel SHA256，已通过38个包的哈希校验下载及离线全新安装。它不宣称验证其他 Python/CPU/操作系统；跨环境及正式 EXE 的完整分发审查仍在 I 阶段。

## 已知漏洞及来源检查

[DEPENDENCY_AUDIT.json](DEPENDENCY_AUDIT.json) 对应当前依赖输入哈希，记录38个生产包、2个研究包和185个 npm 锁定节点。Python 查询 PyPI 当前版本漏洞回报，npm 执行完整 npm audit：本轮活动公告均为0。该结论仅是相应日期和公开公告源的结果，不是无漏洞或全部原生供应链都经过安全认证的证明。

npm 包的 SRI 被检查；内嵌 inBundle 子依赖继承其父归档 SRI，不伪造单独归档哈希。已安装的114个 npm 节点及 Python 生产包共收集182份许可文件、114份去重文本。未安装的平台可选包只列元数据，未来如被实际分发需重新审查。三个 npm 包没有本地许可文本，分别使用所属 rolldown 包的许可或可核验上游仓库文本，来源在通知文件中注明。

源码导出时，如果组件审查存在但其输入哈希过期、结果缺失或含未关闭公告，构建会拒绝沿用旧验收结论；同时保留原有敏感文件白名单及二次扫描。

## 指标参考复测

当前标准实现再次与实际 TA-Lib0.8.3、NumPy2.5.4 对照：13组、11,752个值一致，预热空值位置一致；最大绝对误差 EMA7.28e-12、RSI3.56e-14、ATR5.69e-14。该版本横盘 RSI 返回50。原 RSI 汇总、ATR均值及首价初始化 EMA 的执行口径保持不变，研究对照不证明盈利优势。

## 可复现开发命令

```powershell
# 经过本轮验证的 Windows CPython3.12 x64 环境
python -m pip install --require-hashes -r requirements-win-py312.lock
python -m pip check
npm --prefix frontend ci
npm --prefix frontend audit --json > npm-audit.json
python scripts/audit_components.py --npm-audit npm-audit.json --research-path <研究环境site-packages> --output docs/DEPENDENCY_AUDIT.json
python scripts/verify_indicator_reference.py --reference-path <研究环境site-packages> --output indicator-report.json --golden indicator-golden.json
```

日常启动不需要运行审计命令，也不需要安装 TA-Lib。开发审查不读取 API 密钥、不连接交易账户。
