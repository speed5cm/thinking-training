# AI Wiki-derived Roadmap：对照与最小实现

2026-11-08 核对上游 [sigma-with-wiki/SKILL.md](https://github.com/orionpax1997/llm-wiki-sigma-agent/blob/main/.claude/skills/sigma-with-wiki/SKILL.md)，Git blob `4deba6755b43a7e469b08cb2d51b9608e217bc8d`；是文件内容标识，不是仓库 commit。上游先 survey overview/index，筛 Teaching/Synthesis，综合叙事及 WikiLink 依赖形成覆盖全 Wiki 的路线；诊断决定起点，每项保留 Wiki Pages、状态与复习，进入概念重读 Wiki，进行交错与恢复时的间隔复习，并更新个人状态及 HTML。源文件是行为规范，并非运行效果证据。

当前 `generate_roadmap.py` 检查根 Wiki 的 14 页、关系、来源登记及发布快照，输出静态课程投影；不读画像、学习记录，不进行语义推理或动态复习。上游的 overview 和 Teaching 类型标记在本仓库不存在，适配为根索引、全部中文教学概念及 12 周叙事；不伪造缺失文件。上游的诊断预标掌握和约 80% 门槛不适用本儿童试点：现行跨机会、不同题卡、迁移及家长确认规则优先。上游单会话被化名目录取代。

Sigma 按 [儿童适配协议](../experiments/sigma-integration/ADAPTER.md) 读取 Wiki 和证据、生成个人建议，统一使用 `sigma_plan_store.py prepare` 展示候选并等待家长确认，再用 `publish --confirmed-sha` 校验并发布。`validate_personal_roadmap.py` 检查课程范围、先修顺序、复习位置、引用和输入快照；建议来自 `learning_evidence.recommend`。校验不判断语义、教学质量或掌握，也不授予教学许可。正式题卡和证据由 Coach 及证据模块独立管理。儿童正式入口仍关闭。

## 收敛后的依赖

Sigma 读取上游 Skill 与儿童适配协议，通过会话存储保存逐轮记录，通过规划存储调用规划校验器；校验器读取课程生成器、Sigma 规划依据及正式证据。Coach 独立执行已审核题卡并在使用时检查发布和先修，证据模块采集 Coach 记录并处理家长掌握确认。旧 Tutor 状态机及独立 Planner 指令已移除；规划不再读取旧 Tutor 状态。运行记录目录中未发现旧 Tutor 会话，历史实验和验收报告作为历史证据保留。

## 虚构演示及复现

`examples/ai-roadmap/fiction-plan.json` 是本次由 AI 阅读现有 14 页后撰写的合成示例，不含真实儿童信息。画像：9 岁、喜欢图形，一次虚构诊断可延续给定图案但难区分观察与猜测，偏好具体物品及口述；无正式证据或家长确认。推荐 C01 巩固；先 C04 再 C03 是利用兴趣并为 C05 结合两者，C11/C14 在图中提前列入并在 C09 后回访；所有这些仅是条件性计划。C03—C14 没有发布题卡，不能实际教学；C02 虽有发布快照仍须 C01 达到既有条件和家长确认。C01 当前仅一张训练卡，不能形成现行跨题迁移候选。C06 对 C05 的必要性列为待审问题而非结论。复习无具体日期，因为不存在学习日期及足够的证据。

为复验，在 `pilot-c01-c02/records/fiction-demo/planner-profile.md` 放入以下**完全相同的 UTF-8 内容**，目录已被 Git 忽略：

```markdown
# 虚构画像（仅演示）
9岁；喜欢图形规律，一次诊断中口头表达理由时急于下结论。一次虚构起点诊断中能延续给定图案，但未能清楚区分观察与猜测。没有正式训练证据、没有家长掌握确认。偏好先用具体物品、简短口述。所有诊断观察只用于安排起点，不证明掌握。
```

保持该化名无事件、证据或确认文件，然后执行 `python3 scripts/validate_personal_roadmap.py validate --learner fiction-demo --plan examples/ai-roadmap/fiction-plan.json`。若 Wiki 等输入变更则摘要失效，须重新进行 AI 规划而不是修改摘要蒙混通过。验证通过只表示结构符合当前约束；样例理由和情境仍需人工审阅。`**/records/` 是 Git 忽略，不是安全隔离；勿提交真实画像或记录。
