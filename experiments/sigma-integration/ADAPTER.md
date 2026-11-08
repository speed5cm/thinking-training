# 隔离验证适配：Sigma + 儿童试点

本文件优先于同副本 `.claude/skills/sigma-with-wiki/SKILL.md` 中冲突的段落；无冲突的 survey、问题循环、回顾和误区追踪沿用原版。上游原文件 Git blob `4deba6755b43a7e469b08cb2d51b9608e217bc8d`，许可证与引用文件随原件保存。本文件是验证适配，不是正式上线。

1. 成人陪同，使用化名。Sigma 会话存到 `pilot-c01-c02/records/<化名>/sigma/`；不可使用上游全局路径或旧跨话题画像。状态须在每次提出问题前、回答后、暂停/结束时持久化，保留原话、问题、提示、分析、假设、动作、原因、家长观察和路线版本；未答问题恢复原题。此验证适配不用于真实儿童。
2. 根 Wiki 没有 overview 和上游类型标记：读取 `wiki/index.md`、全部 14 页、`curriculum/12-week-plan.md`，由 `python3 scripts/generate_roadmap.py --check` 检查结构。14 页是课程范围，不等于授权进入。保留每概念 Wiki Pages；上游缺 overview 的 plain `/sigma` 回退禁止使用。每次进入或恢复概念重读根 Wiki 和试点概念、相关资料；冲突或缺失即停止。
3. 用 Sigma 的路线推理生成候选，输出到 `personal-roadmap.json` 的现有 schema 并调用 `scripts/validate_personal_roadmap.py` 校验；规划只是建议。停止调用独立 Planner Skill，保留其校验器。不能凭诊断标 mastered、跳过先修、凭 80% 或自评宣布掌握。以 `learning_evidence.py recommend`、证据聚合、家长确认和 coach 即时门禁为权威。当前只有一张 C01 已发布训练卡，不能满足不同题卡掌握证据；C02 正常情况下不可进入。
4. 使用 Sigma 的问题、回答分析、追问、提示、例子、跨情境与复习过程，AI 自审适龄、只问一个问题、符合 Wiki、不泄露正式题答案。动态练习不是正式测评或授权。正式测评题、原题提示及支持仅走 `coach.py`，完成后通过 `learning_evidence.py capture` 采集；不能把动态练习写成已审核卡。对连续不理解提供不同方式、平行示范或休息；疲劳、拒绝或挫败立即停止并保存。只在具体证据支持时记录待验证假设；未知即 unknown，禁止学习风格、心理和稳定能力标签，不强迫填误区表。
5. 不自动打开浏览器；HTML 和可视化只在需要时生成，不用上游固定每轮重写 HTML。继续学习须重新 survey、重验发布和先修，并先恢复未答问题；复习只在已允许的概念上进行。对未发布内容，未来路线可列但不得将其作为正式教学或测评题。

## 强制会话存储协议

本节覆盖上游所有直接读取或写入 session.md、画像及逐轮记录的指令。开始、继续、查看、暂停和结束时均先运行 `python3 scripts/sigma_session_store.py read --learner <化名>`；只从返回的 `state`、`session`、`turns` 和 `revision` 恢复。每次提问展示前、接收原答后及暂停或结束前，将完整的三个字段作为 JSON 经标准输入提交给 `python3 scripts/sigma_session_store.py commit --learner <化名> --expected-revision <读取到的修订号>`；`turns` 必须保留全部已提交记录并追加新记录。先提交成功，才能展示问题或声称已保存；失败即停止，冲突时重新读取并根据最新会话重新判断，不盲目覆盖。提交载荷不含 revision 和 schema_version。不要把儿童原话放入命令行参数或历史。

`session-snapshot.json` 是 Sigma 会话唯一权威来源；禁止独立创建、修改或读取旧的 `state.json`、`session.md`、`turns.jsonl` 作为会话状态。存在任何旧文件时接口停止，须人工核对和安全迁移后才能继续；不得自动删掉旧文件或当作新会话。路线、coach 事件和正式证据各有自己的存储及门禁，不包含在此快照事务中；跨系统操作中断后须重新核对，不能声称整个学习会话跨文件原子一致。直接绕过接口的文件操作不受程序强制约束，本协议尚需真实 Agent 端到端验收。
