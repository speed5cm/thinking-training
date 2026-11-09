# Sigma 动态教学收敛：未完成验收记录

本记录对应隔离合成验证，不开放真实儿童入口。最终完成标准尚未满足。

## 初始回归

使用 `python3 -m unittest discover -s tests -v` 和 `python3 -m unittest discover -s pilot-c01-c02/tests -v`。初始主套件 56 项：2 failures、31 errors（含子测试）；Coach 套件 24 项：2 failures、17 errors。原始输出分别为 `/tmp/sigma-main-regression.log` 和 `/tmp/sigma-coach-regression.log`，临时目录日志可能被清理。

| 失败来源 | 初始表现及分类 |
| --- | --- |
| `test_dynamic_candidate`、`test_sigma_assessment_records` | 初始夹具缺少现行确认路线；现已使用真实 prepare/publish 建立合成路线，两套测试通过。 |
| `test_dynamic_transition` | 共享夹具更新后曾有 5 项失败：3 项仍要求固定题卡启动或其并发行为，2 项仍认为普通证据或授权变化会使整条路线过期。现改为检查动态提交并发和持锁重验、证据更正及实时授权，6 项通过。测试时间原设在未来，导致真实子进程时钟倒退拒绝；现使用早于系统时钟的合成时间。 |
| `test_personal_roadmap` | 规划单元测试的模拟授权及路线门禁夹具过旧，且错误地认为普通问答使路线过期；已更新为普通问答不改变路线、实质性 `planning_basis` 才使其过期。 |
| `test_sigma_session_store` | 记录层测试的模拟授权缺少概念且未提供路线门禁；已限定为存储单元测试并更新夹具，另有实际门禁集成测试。 |
| `test_concept_authorization` | 旧测试要求开始空会话即授权；已更新为允许开始会话、对问题提交逐项检查授权和路线，变化后重发布路线。该测试通过。 |
| `test_roadmap` | 旧测试认为 C01/C02 正式入口开放；已更新为全部关闭。 |
| `test_sigma_integration`、`test_sigma_review` | 旧测试依赖固定题卡证据自动产生或完成复习任务；现行流程采用动态复习，历史记录仍须保留。集成测试已改为验证旧证据不创建任务和普通问答不使路线过期，其动态复习和 Wiki 变更路径通过；复习单元测试已迁移通过。 |
| `test_coach` | 初始大量测试期望开始、展示、作答、提示或恢复固定题卡，当前入口明确拒绝这些操作；并发开始及错误文案断言亦基于旧契约。更新后的 24 项测试验证入口拒绝、历史记录读取、暂停、结束、隔离、并发拒绝和题卡归档完整性，全部通过。 |

环境问题：`python` 命令不存在，使用项目协议指定的 `python3`；这不是上述 Python 测试失败的原因。受限网络下 Agent 模型连接失败；具备网络访问的隔离配置连通性检查通过。

## 已处理和已验证

- 最终完整回归：主套件 57 项全部通过（含新增的路线过期拒绝测试），Coach 套件 24 项全部通过。命令与初始回归相同，日志分别为 `/tmp/sigma-main-validation.log` 和 `/tmp/sigma-coach-updated.log`；未跳过测试或放宽生产门禁。
- 会话存储原先把路线或先修门禁失败当作授权失效，允许不适用的授权中断路径；现将两者分开，路线失败直接拒绝。新增拒绝测试；存储单元测试通过。
- 清除 Coach 已关闭入口后不可达的固定题卡执行分支；保留历史记录读取、暂停、结束与反馈。旧版证据和复习接口尚未全部清除。
- `test_c02_integration.py` 3 项、`test_dynamic_candidate.py` 8 项、`test_dynamic_transition.py` 6 项、`test_sigma_assessment_records.py` 8 项、`test_sigma_integration.py` 1 项、`test_sigma_generic_loop.py` 2 项、`test_sigma_session_store.py` 3 项、`test_roadmap.py` 5 项及 `test_personal_roadmap.py` 8 项通过。这些是脚本测试，不是 Agent 自主验收。

## 遗留和阻断

- `learning_evidence.py` 的 `capture`、`assess`、`confirm-c01`、`recommend` 和 C01/C02 专用辅助函数已移除；`sigma_plan_store.py complete-review` 显式拒绝旧入口。历史证据仍只读，旧设计文档已标为历史记录，其中旧命令仅供追溯。
- 完整回归通过，但脚本回归不能替代真实 Agent 验收。
- 真实 Agent 连通性检查只回复了 `SIGMA_AGENT_READY`，没有执行教学。启动完整副本验收的自动审批被拒绝：副本可能包含敏感文件，发送到外部模型服务的范围未经明确授权。没有真实 Agent 的 C01→C02→C03、撤销、证据失效、Wiki 或路线变化、中断恢复和复习的端到端证据。
- 程序要求独立会话跨至少 12 小时及本地日边界；真实 Agent 验收不得伪造时间。需要真实等待或明确设计且披露的隔离时间机制，同时不能将后者表述为真实时钟验收。

复现：在仓库根目录执行上述两条全量命令；单独验证修复可运行 `python3 -m unittest discover -s tests -p test_sigma_session_store.py -v` 和 `python3 -m unittest discover -s tests -p test_sigma_generic_loop.py -v`。任何真实 Agent 重试须先明确允许发送给模型服务的文件范围，并在独立可写副本内执行。
