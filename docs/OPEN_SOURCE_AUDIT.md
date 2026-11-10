# D 阶段组件与依赖审查

更新：2026-11-04。**D 的组件 POC 与采用评审已验收**；参见 [最终决定](COMPONENT_DECISIONS.md)、[验收记录](PHASE_D_RESULTS.md)。本结论不代表 v1.0 Stable 或真实交易验收。

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


## 2026-11-11 开发复用审查规则

本轮不预先指定必须新增的第三方依赖。每项功能开发前，先检查当前仓库已有模块、接口和测试，再搜索维护活跃、许可证兼容的成熟开源实现。仅当确认现有实现存在明确缺口时，才提出候选。

每个候选必须记录固定 tag/commit、许可证与 NOTICE、维护和安全状态、Windows/Python/Node 兼容性、与现有实现的重叠、依赖体积、隔离 POC、回归结果和回滚方案。研究参考不等于批准复制代码或新增依赖；必须先获得项目所有者批准。现有实现足够时优先复用，不为追求技术栈数量引入新依赖。
