# P0 修复与真实 Agent 定向复测

结论：三个 P0 功能已实现，动态复习和事件恢复的指定成人模拟通过；实质性 Wiki 修改后的路线调整**未通过**，整体 P1 尚未通过，不能切换儿童入口。没有依据模拟结果宣称真实儿童掌握或教学效果。本轮只修改隔离实验适配、确定性存储及相应测试；没有修改正式题卡、审核记录、真实学习档案或正式授权规则。

## 修改

- `scripts/sigma_plan_store.py`：在现有单文件规划历史中新增动态复习任务。`schedule-dynamic` 引用已保存的问答分析，按 Agent 指定的 1–32 天安排；`complete-dynamic` 检查到期、任务与已保存复习问答分析的关联，在一次原子写中记录结果并创建下一任务。原有正式证据复习逻辑保持独立；动态结果不能授予正式掌握或晋级。会话与队列仍是独立文件，失败时需回读核对。
- `scripts/sigma_session_store.py`：新回答必须在同一提交中追加关联 question ID 的 `answer` 和非空 `analysis` 事件，验证唯一性和顺序；既有事件仍不可覆盖。旧快照不自动改写，也不能凭该修复恢复过去已经覆盖的详细分析。
- `scripts/validate_personal_roadmap.py`：不再把普通 coach 事件日志直接放入规划摘要；正式证据和家长确认继续独立绑定。使用旧摘要方案保存的路线可能因此变为 stale，须按适配规则重新核对和规划。
- `experiments/sigma-integration/ADAPTER.md` 及 `blocker-validation/ADAPTER.md`：明确分析追加协议、动态复习调用、跨文件失败核对与规划依据的边界。即时选择平行例子、普通问答或下一步动作不属于重规划依据；实质性学习判断仍须诚实更新。
- 更新与新增相关回归测试，覆盖分析恢复、拒绝缺失/重复分析、动态任务到期及完成后续排、重复提交、正式证据分离和普通事件不使路线失效。

## 隔离与审计

新建 `/tmp/sigma-targeted-clean` 白名单副本，records 初始为空，未复制历史记录、审计日志、隐藏配置或凭据；检查常见凭据名称和特征无匹配。仅使用已授权的同一 Codex 模型服务、正常 workspace-write 沙箱、虚构化名及合成数据。将 18 个原有题卡和审核相关文件与仓库比较，散列均一致；没有产生 `synthetic-p1/evidence.jsonl`。

此目录的 `input-*.txt` 是测试者逐轮输入，`turn-*.jsonl`、`restart-*.jsonl`、`new-agent-*.jsonl` 和 `ordinary-*.jsonl` 是真实 Codex Agent 工具调用与输出，`state-*.json`、`plan-*.json` 是虚构会话关键快照。该目录中不含真实儿童数据。`turn-01.jsonl` 使用旧规划摘要代码；该次发现 coach 诊断启动即令路线 stale，随后修正摘要并在新虚构学习者上复测。

## 成人模拟结果

| 验收项目 | 结果与证据 |
| --- | --- |
| 根据回答发现复习需求并创建动态任务 | 通过所测案例。Agent 从 `diag-001` 的原答与分析发现事实/推测混淆，在学习者请求复习后建立 C01 一天任务；见 `turn-04-review-schedule.jsonl`、`plan-04-before-clock.json`。 |
| 到期后实际复习、分析并安排下次 | 通过所测案例。测试者仅将隔离任务时间回拨两天模拟到期，前后文件分别为 `plan-04-before-clock.json`、`plan-04-simulated-due.json`。Agent 先保存关联任务的复习题，收答后保存分析，将旧任务完成并产生两天后的任务；见 `turn-05-due.jsonl`、`turn-06-review-answer.jsonl`、`plan-06.json`。无正式证据。 |
| 普通教学及平行例子不频繁重规划 | 五个非复习动态问题 `explore-001` 至 `explore-004`、`practice-001` 均有答和分析，路线保持 v1；第 2 次诊断回答选择平行例子也未重规划。五个动态问题中间有暂停、独立 Agent 恢复和 Wiki 基线恢复，不能声称五轮完全不间断；见 `state-ordinary-final.json`、`plan-ordinary-final.json`。 |
| 暂停并重启 Agent 后恢复详细分析 | 通过所测案例。新 Codex 线程没有先前对话上下文，从磁盘恢复当时全部五组问题、原答、分析；会话仍暂停、路线 v1。见 `new-agent-restore.jsonl`、`state-restore.json`。后来又追加了三组问答分析。 |
| Wiki 实质性变化先核对再调整路线 | **未通过完整验收**。隔离 C01 增加“两种可核实解释”的教学要求，见 `wiki-substantive.diff`。新 Agent 先检测 stale，缺少旧正文时停止；提供测试者保存的旧正文后，核验与 v1 的完整课程摘要匹配，识别新增目标及试点材料的覆盖缺口，继续暂停且未发布新路线。见 `new-agent-wiki.jsonl`、`new-agent-wiki-baseline.jsonl`。安全停止和先分析通过，路线调整未完成。随后仅为普通教学测试把隔离 Wiki 恢复为原版。 |

真实 Agent 开始时还暴露两次可复现的操作问题：一个新 Agent 先读未创建的化名目录而安全停止，测试者创建空目录后继续；随后 Agent 生成的首题快照命令和第一次 coach 作答调用各有一次语法错误，均停止并在核对后重试，原答未重复。见 `restart-01.jsonl`、`restart-02.jsonl`、`restart-03.jsonl`、`turn-02.jsonl`、`reconcile-02.jsonl`。这些不能计为无人工协助的完整启动或跨模块自动恢复通过。

暂停恢复后的 Agent 还指出路线原文仍含初始“尚无学习者回答”的描述。当前进度和问答可从快照读取，但路线文字不是实时进度展示；本轮未新增 UI。实际重要理解变化何时需要进入 `planning_basis` 仍依赖 Agent 判断，此次五轮保持路线不变不证明所有实质变化都能被识别。

## 回归与未完成项

- `python3 -m unittest discover -s tests -v`：33 项通过，见 `tests-main-final.log`。首次执行有一项旧测试未同时提交分析而失败，已按新协议更新，失败日志为 `tests-main.log`。
- `python3 -m unittest discover -s pilot-c01-c02/tests -v`：24 项通过，见 `tests-coach.log`。
- `python3 scripts/generate_roadmap.py --check`：14 概念、2 个试点可用快照通过，见 `roadmap-check.log`。
- 旧会话迁移与回滚、受控发布/撤销、跨模块故障恢复、C02 有效授权后的真实 Agent 正式训练及旧入口停用仍须独立验收；本次未声称通过。
- 对不同 Wiki 实质变化、正式材料覆盖冲突、旧 Wiki 正文不可取得的恢复仍需处理。本次因材料覆盖边界未确认而暂停，没有重规划，故 P1 整体不能标为通过。
