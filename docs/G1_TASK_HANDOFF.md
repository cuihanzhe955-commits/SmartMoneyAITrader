# G1任务合同与交接

- 任务ID：G1-automatic-prediction-challenge。
- 起始代码基线：2d55453a658f85172e975d8c1d37b89196402f16。
- 集成main基线：234d8335c6c3240bf654f280de3c9c3ccf89df85（工作结束前发现新增协作规范，已完整读取并保留其内容/入口）。
- 专属开发分支：g1-automatic-prediction-challenge；本任务采用单一写入者。检查时远端仅main，无开放PR。
- 目标：在F参考模拟执行器之上增加有界自动预测挑战、持久预约/恢复、防重统计、操作及报告UI。
- 允许路径：challenge/prediction.py、events/lab.py、market/predictions.py、terminal/api.py、frontend/src/forms.tsx、frontend/src/event-lab.tsx、frontend/src/prediction-challenge.tsx、相关tests、docs、README、SOURCE_MANIFEST和打包白名单。
- 不在本轮范围：消息发送/OpenClaw配置、影子/只读独立模式入口、生产依赖更新、主计划产品/架构变更、真实账户/资金、Stable发布。
- 禁止触碰：用户runtime数据、凭据、私人账单、既有保险备份、OpenClaw生产配置及共享远端main历史。

## 验收与已完成

全量隔离840通过/0失败/0跳过，52.75秒；新增26项。定向95通过/0失败，17.62秒；TypeScript/Vite构建通过；G1和F浏览器回归通过，两档尺寸、深浅主题。另16项打包规则检查通过，0.19秒。

本地Windows 11，Python 3.12.2，Node 24.22.2；当前分支SHA见PR元数据。模型/行情为Model Mock/合成数据；仅公开Gamma发现参数做过真实只读探测，未运行真实市场100轮或真实AI挑战。

复用既有干净依赖环境，锁定版本/pip check、临时库启动、240根回放和正常停止通过；不等于全新Windows安装验收。

已实现清单、修改目的、证据与边界见[阶段记录](PHASE_G1_CHALLENGE.md)和[结构化结果](G_TEST_RESULTS.json)。全部G1改动可从本分支相对main的PR diff复核。未新增依赖，已检查打包白名单和敏感信息形态。

## 实际命令

```powershell
python -X utf8 -B tests/run_offline.py
python -X utf8 -B tests/run_offline.py tests/test_prediction_challenge.py tests/test_event_lab.py tests/test_event_research.py
python -X utf8 -B tests/run_offline.py tests/test_package.py
npm --prefix frontend run build
# SMART_MONEY_UI_OUTPUT设在工程外，运行：
python -X utf8 -B tests/prediction_challenge_browser.py
python -X utf8 -B tests/brain_lab_browser.py
```

首次浏览器回归发现旧替身结算时间可能早于刚完成的预测，修复了替身时间顺序，保留应用严格时序检查，复测通过。首次定向回归发现旧F请求的默认数字类型规范化影响重试，已修复并加入兼容测试。

## 剩余与审阅边界

新增两张SQLite表的迁移仅在临时库验证，用户运行库未执行；提交PR供所有者审查，不能自行合并main或启动用户运行库迁移。保留新增表和当前数据库，不以回退旧库清除未决记录。

G仍未完成。下一步唯一任务：G2持久异步通知与OpenClaw/飞书/Telegram配置闭环；真实发送需遵守既有授权和目标范围。独立影子/观察入口、真实Provider/真实100轮持续运行、H/I与平台资金验收继续单列。

本轮不生成新正式发布包。最后提交SHA和PR链接在实际提交后的交付消息/PR元数据中给出；不得将草稿PR描述为已合并功能。
