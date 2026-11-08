# Sigma 直接集成：隔离验证报告

日期：2026-11-08。结论：**有条件可复用，但当前适配不能上线，真实 Agent 测试尚未全部通过。**本次测试在 `/tmp/thinking-sigma-validation` 副本执行，未复制真实个人记录，也未修改题卡、审核或正式课程；结束时与工作区逐文件 SHA-256 对比：cards 13 文件、reviews 5 文件全部一致。本目录保存上游原件、实验适配、真实 Agent 事件日志和虚构学习者产物；`formal_gate.py` 是拷自隔离副本的原型，须放在项目副本的 `integration/` 下才可运行。

## 集成差距及最小迁移

| 职责 | 当前重叠或差距 | 建议 |
|---|---|---|
| Wiki survey、路线、教学、误区、复习 | 上游 Sigma 是行为规范，由 Agent 执行；本地 AI Planner 和上一轮 child-sigma-tutor 重复编排。根 Wiki 缺 overview、类型标记 | 以 Sigma 为唯一教学编排；适配 survey 使用根 index、14 页和课程计划。保留概念迁移时重读的门禁，不用无 Wiki 回退 |
| 基础课程 | `generate_roadmap.py` 提供 14 概念、关系及发布快照 | 保留；Sigma 路线覆盖 14 概念并受其硬先修约束。快照本身不是现场授权 |
| 个人规划 | Sigma 和 `skills/ai-roadmap-planner` 均生成路线 | Sigma 负责 AI 规划；保留 `validate_personal_roadmap.py` 作确定性校验和快照绑定，停用独立 Planner Skill；将其必要 schema 和约束并入适配。合并后需迁移已有 JSON/历史，不能静默删除 |
| 教学状态 | 上游单例共享目录与个人隐私冲突；上一轮 `tutor_loop.py` 是另一套状态机 | Sigma 会话按化名存储；实现一个共享、原子持久化和恢复接口，评估复用上一轮的原子写入而非保留第二套编排。审计旧数据后再退役上一轮 Skill/状态机；本次未删除工作区未提交文件 |
| 正式题与证据 | `coach.py` 检查发布但不会校验 C01→C02 先修；`learning_evidence.py` 汇总历史证据及家长确认 | 保留两者，新增不可绕过的正式操作边界：在同一锁及事务内核验证据建议、C02 先修和卡片发布，并调用 coach；涉及 resume/show/attempt 等所有路径。原 coach 直调也需受控，不能仅靠 Agent 自觉。`formal_gate.py` 的检查和 start 跨进程、有竞态，coach 仍可直调，只是验证原型 |
| 儿童保护和掌握 | Sigma 使用 80% 门槛、诊断预标掌握、错误推断误区与画像特征 | 使用项目的跨题、跨机会、迁移和家长确认规则；单次结果不标掌握、不推断固定风格或心理；误区为引用原话的待验证假设；疲劳即暂停 |
| 复习和视觉 | Sigma 每轮重写 HTML，恢复时按间隔复习 | 延用复习思路，受发布、先修和疲劳约束；路线版本不可原位覆盖；视觉按需生成，不将未执行的浏览器验收标通过 |

上游 [sigma-with-wiki](https://github.com/orionpax1997/llm-wiki-sigma-agent/blob/main/.claude/skills/sigma-with-wiki/SKILL.md) 文件 blob `4deba6755b43a7e469b08cb2d51b9608e217bc8d`，原文和依赖模板、MIT 许可证见 `upstream/`。文件 blob 是内容标识，不是仓库 commit。适配规则见 `ADAPTER.md`：这是原样上游加项目优先级覆盖的实验，并非无修改直接执行上游。

## 真实 Agent 模拟与审查

使用独立 Codex 真实会话 `01a1bac7-8ec1-7650-8387-5630b7d197fc`；调用现有模型并在每轮输入虚构成人模拟回答，所有工具输出和最终消息逐轮留在 `audit/*.jsonl`。`simulation/` 是虚构数据，包含 Agent 生成的状态和路线。日志是未经独立教师审核的实验记录。

1. Agent 完整读取上游 Skill、14 概念及课程，调用 coach 和结构检查，建立 14 项路线。第一问是已发布 C01 诊断题，孩子答出区分及理由；Agent 将结果记录为单次观察，没有宣布掌握。**未通过**：它随后沿现有两题诊断顺序转到 C02，没有对充分理由继续探究。这反映 Sigma 和 coach 诊断流程的编排冲突。
2. C02 使用的是既有发布的诊断卡，不是 C02 正式训练；针对模拟回答“它们形状相同，因为颜色不一样”，Agent 保存原话并询问理由，未宣布掌握。此项符合本场景预期；诊断是否应在先修之前涉及 C02 仍须由课程所有者确定，不得将它当作 C02 教学授权。
3. 模拟孩子说累了，Agent 暂停并保存待答追问；“继续学习”后重新 survey、检查材料及 coach 状态，恢复同一追问。随后孩子表示仍不明白，Agent 给出平行例子或休息的选择，未继续强迫。这些观察仅覆盖一次演示，未证明所有分支均可靠。
4. 由本次审查对话核查：C01 和 C02 两道诊断题是现有已发布原题；动态追问为中性请求解释，未给出原题答案，简短且适龄；“平行例子或休息”并未实际展示例子，因此无法对生成例子的正确性、Wiki 一致性及泄漏风险验收。没有独立教师语义复核。
5. Agent 路线校验通过且覆盖 14 概念，但无复习步骤；C01 回答后计划理由变化，而路线仍称版本 1，缺少可靠的版本历史。`session.md` 与 `state.json` 采用多文件各自写入，断电/并发一致性未验证。不能据此认定 Roadmap 更新或间隔复习端到端通过。
6. 尚未测试多种可能性的证据核实、连续多轮不理解后的具体换例子、动态题的完整语义审核、C02 正式训练成功路径和受限发布后的真实 Agent 对抗。当前 C01 只有一张已发布训练卡，无法构造满足不同题卡条件的真实 C02 晋级；不得伪造证据。

## 确定性检查

- 在隔离副本运行 `python3 -m unittest discover -s tests -v`：22 项通过（包括上一轮未提交的 4 项 Tutor 测试）。`python3 -m unittest discover -s pilot-c01-c02/tests -v`：22 项通过。`python3 scripts/generate_roadmap.py --check`：14 概念、2 个试点可用快照。
- 既有 coach 测试 `test_unreviewed_card_is_rejected` 和 `test_changed_card_cannot_use_old_approval_or_same_version` 通过，说明其题卡加载路径拒绝未审核/已更改卡；这不是 Agent 无法绕过该路径的证明。
- 原型 `python3 integration/formal_gate.py check --learner sigma-sim --concept C02` 返回 BLOCKED：证据不足；C01 返回 ALLOWED。原型不提供原子性或防止 Agent 直接调用 coach 的保证，不可作为正式防绕过验收。
- 新路线用 `validate_personal_roadmap.py validate` 通过；此校验不判断自然语言质量、授予教学许可或证明复习效果。

## 上线前最小待办

1. 用可原子执行、不可通过普通入口绕过的边界统一先修与发布检查；明确诊断题与正式训练的界限。
2. 将 Sigma 对话和 coach 的题目状态衔接：充分理由后允许安全追问，未答追问不被下一题覆盖；每轮按化名原子保存原答、分析、支持和动作。
3. 统一路线格式和内容哈希版本，保留历史与复习触发记录；不将诊断或动态对话提升为正式证据。迁移并核验已有个人记录后才停用重复模块。
4. 在隔离副本重跑多场景真实 Agent 成人模拟、语义审查、门禁撤销及回归；涉及浏览器时另按项目约定制作交接，实际未执行不得标通过。
