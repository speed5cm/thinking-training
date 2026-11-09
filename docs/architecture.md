# 上游机制与试点架构

> 状态说明（2026-11-09）：本文其余部分保留当时的上游核查与试点架构历史，不能将“现均未实现”或未来时表述作为当前实现状态。当前 Sigma 为唯一 AI 教学与规划核心，Coach 执行已审核题卡，动态教学不构成正式晋级证据；儿童正式入口关闭。现行协议见 [ADAPTER](../experiments/sigma-integration/ADAPTER.md)。
>
> **已决定**采用同一 Sigma 动态生成教学题和评估题，并取消固定题卡作为新机制晋级前提；**待实现、待验证**的目标数据流和模块职责见 [动态评估设计](sigma-dynamic-assessment.md)。目标采用绑定人工审核内容版本和摘要、可撤销的概念级授权；每次概念晋级须家长确认，无须逐题确认。跨不同 UTC+8 自然日且至少间隔 12 小时的有效评估要求已决定。这些机制均待实现和验证，现有门禁不变；Wiki、先修、安全停止及可信家长身份仍须保障。旧 Coach、题卡及审核代码保留，不能把目标架构当作已经上线。

核查日期：2026-11-04。依据上游 [仓库目录和 README](https://github.com/orionpax1997/llm-wiki-sigma-agent)、[AGENTS.md 实际工作流](https://github.com/orionpax1997/llm-wiki-sigma-agent/blob/main/AGENTS.md)、[sigma-with-wiki 技能文件](https://github.com/orionpax1997/llm-wiki-sigma-agent/blob/main/.claude/skills/sigma-with-wiki/SKILL.md)。通过网页读取文件，未克隆仓库或执行代码；上游 main 未锁定 commit，实施时须记录实际 SHA 并重新核验。README 与源码属于项目自述及指令，不能证明功能已实际运行。

## 上游目录及 ingest

根目录包括 `.claude/`、`docs/`、`examples/`、`graph/`、`raw/`、`tools/`、`wiki/`、AGENTS.md/CLAUDE.md/GEMINI.md 和 Python 依赖文件。AGENTS.md 指定 raw 原文不可修改，wiki 为代理维护层；index 为目录、log 追加操作、overview 为综合，sources/entities/concepts/syntheses 各有页面，graph 为生成层。`tools/health.py` 做无 LLM 结构检查，`lint.py` 做内容质量检查，图工具有可选依赖；本次没有读取或执行这些脚本，不能断言它们覆盖我们的门禁。

Codex 自然语言 `ingest` 流程依次完整读取源（非 Markdown 可转 Markdown）、读 index/overview、写 source 摘要、更新 index/overview、建立实体与概念、标记冲突、追加 log，再查链接和目录。默认自动改 wiki，因此绝不可对本项目原始资料直接运行；应在单独工作副本、版权预筛选之后执行。摘要不等于可靠引用或版权许可。

## Teaching Concept 与课程生成

上游要求概念具备完整结构，如 Core Thesis、Mental Model，并在 index 标 `(Teaching Concept)`，或依据 frontmatter 与结构判断；标准概念仅作参考，跨章节综合概念可纳入教学。具体完整模板应在固定版本的上游源中逐项复核；不能将本地已有的中文“教学动作/例子/掌握”直接假定符合。建议映射：ID、标题、核心命题、儿童心理模型、教学动作、反例/误区、先修链接、来源位置、题目链接、掌握证据、状态及版本；在适配副本保留上游必需标题，增加本地字段。

启动先完整读 overview/index，以 overview 的范围及叙事顺序筛 Teaching/Synthesis，结合依赖关系建 roadmap；全 wiki 默认纳入，超过 25 概念分阶段但不省略；不存在概念先终止。诊断决定从哪里开始，session.md 的 Concept Map 为每项记录 Wiki Pages、先修、状态、得分、复习时间。此行为不保证遵循 60 节日程，因此首周需固定 W01D1—D5 路由，不能只依赖上游自由生成。

## Gate、状态和教学循环

Wiki Read Gate 在每次进入概念前，根据 session.md 的 Wiki Pages 按顺序完整重读并记录；失败则停下，请用户选择处理，不靠记忆继续。恢复时重新 survey 并再读当前概念；路径列表相对于 wiki root。试点增加来源和题目版本核对，来源错误或审核撤销时也失败关闭。源文件写了“wiki 为真”，不代表它实际上不会出错；发现冲突应停用和上报，不能让 wiki 覆盖已核实的错误。

上游依次诊断、最小引入、1—2 问/轮、提示及误区追踪、3—5 轮后评估；评价准确、解释、新情境、区分四项，每检查题至少 3/4、概念总体至少 80%，再通过实践才标 mastered。每轮更新 session 和 HTML，已掌握概念每 3—4 问交错；恢复先按复习间隔队列复习。约 80% 是上游规则，不是本项目证据；“每次错答都推断误区”也不能作为儿童稳定特征。

`learner-profile.md` 是跨主题摘要，含学习方式、反复误区、掌握主题和自评；规定两次以上观察才记模式、更新纠错且低于 80 行。`session.md` 是固定单会话目录的状态、路径、误区及日志；新建可能归档，恢复重查 wiki，缺少多儿童隔离。原版所有问题永不直接给答案，但允许共同完成最小示例；本地平行例题完整示范、儿童显式索要答案、退出/恢复、H3 和分数均需明确适配，不能假装原版已有。

## 复用边界

| 分类 | 内容 | 处理 |
|---|---|---|
| 可直接复用的设计/规范 | raw 与派生 wiki 分层、索引与追加日志、来源页、Wiki Read Gate、概念图及按轮保存状态、health/lint 的工作流思路 | 原版规则和文件格式可参考；脚本需在副本测试兼容后才能认定可执行复用。 |
| 需要适配 | ingest 的权限预检、Teaching Concept、按五课排程、诊断、提示、掌握、复习、可恢复状态、Codex 工具替换、儿童用语、视觉输出 | 本地 0—3/H0—H3 和 1/3/7/14 天规则优先；冻结课次、禁止原题剧透、减少视觉和提问负担。 |
| 必须新增 | 题目审核与版本发布门禁、儿童可见题卡和成人答案分离、来源逐条溯源、会话/反馈历史、多儿童隔离、删除机制、错误来源停训、试点题及人工审核 | 先文件化、人工执行，再考虑自动化；现均未实现。 |

Codex 读 AGENTS.md，但 `.claude/skills/...` 及 Claude 的 slash 命令/AskUserQuestion 不等于 Codex 自动可用技能。未来应在隔离试点目录用符合 Codex 的 AGENTS.md 或真正安装的 Skill 指向适配规则，继承本仓库约定且避免覆盖现有用户指令；用普通对话实现交互，不宣称 slash 命令可用。儿童看到的消息只展示已审核题面及允许的提示；同一 agent 的上下文隔离是行为约束而非安全边界，实际可靠隔离须另行实现及验证。

## 预期数据流

合法来源登记 → 在副本内编制/审校概念和题目 → 发布冻结版本 → Codex 按课次读已批准概念和儿童题卡 → 单轮问答/最小记录 → 成人按分离的评分参考复核 → 追加反馈和恢复检查点。成人管理答案；先执行来源和审核门禁，再进入 Gate。试点不依赖 Web、数据库或视觉生成。
