# Sigma Session: sigma-sim

语言：中文；路线版本：1；成人隔离模拟，家长陪同（用户声明）。

## Wiki Context
适配层 integration/ADAPTER.md 优先。已完整读取根索引、全部14概念、12周计划及试点C01、来源和相关教法。根Wiki无overview及类型标记，依适配纳入14教学单元。generate_roadmap.py --check通过：14概念、2试点快照。

## Concept Map
| ID | 名称 | Wiki Pages（相对项目根） | 硬先修 | Status | Score | 复习 |
|---|---|---|---|---|---|---|
| C01 | C01 观察事实与推测 | wiki/concepts/observation-vs-inference.md | 无 | in-progress（仅诊断） | unknown | 未安排 |
| C02 | C02 多属性比较 | wiki/concepts/attribute-comparison.md | C01 | not-started | unknown | 未安排 |
| C03 | C03 分类与反例 | wiki/concepts/classification-counterexample.md | C02 | not-started | unknown | 未安排 |
| C04 | C04 规律识别与检验 | wiki/concepts/pattern-rule.md | C02 | not-started | unknown | 未安排 |
| C05 | C05 系统枚举 | wiki/concepts/systematic-enumeration.md | C03, C04 | not-started | unknown | 未安排 |
| C06 | C06 条件推理及逆推陷阱 | wiki/concepts/conditional-reasoning.md | C01, C05 | not-started | unknown | 未安排 |
| C07 | C07 证据可靠性与替代解释 | wiki/concepts/evidence-and-alternatives.md | C01, C06 | not-started | unknown | 未安排 |
| C08 | C08 结构化论证与倾听 | wiki/concepts/structured-argument.md | C07 | not-started | unknown | 未安排 |
| C09 | C09 复杂问题与约束分解 | wiki/concepts/constraint-decomposition.md | C05, C06 | not-started | unknown | 未安排 |
| C10 | C10 多视角与方案权衡 | wiki/concepts/perspectives-tradeoffs.md | C08, C09 | not-started | unknown | 未安排 |
| C11 | C11 创造性发散 | wiki/concepts/divergent-ideas.md | 无 | not-started | unknown | 未安排 |
| C12 | C12 原型测试与迭代 | wiki/concepts/prototype-testing.md | C09, C11 | not-started | unknown | 未安排 |
| C13 | C13 跨情境策略选择 | wiki/concepts/strategy-transfer.md | C05, C07, C09 | not-started | unknown | 未安排 |
| C14 | C14 计划、监控与反思 | wiki/concepts/plan-monitor-reflect.md | 无 | not-started | unknown | 未安排 |

## 路线与门禁
personal-roadmap.json：v1，校验通过。按课程叙事与硬先修排序，全部14项覆盖；规划不授权。
recommend：collect_or_reinforce C01；零正式证据。C01只有一张发布训练卡，不能满足不同卡与陌生迁移门槛。C02正式教学需C01证据及家长确认；C03—C14未发布，仅未来路线。无已掌握概念，无到期复习，不虚构日期。
coach diagnosis start/show已通过实时资料与发布散列门禁；家长手册旧draft文案不作为现时发布判断，依适配层以即时coach门禁为准。

## Misconceptions
无。尚无作答；假设、能力、偏好、自评均unknown。

## Session Log
2026-11-08T10:51:28.000315+00:00: Survey完成；无旧Sigma会话。C01进入前重读根索引、根C01、试点overview/index、C01和project-research及相关资料；coach保存gate_reads。
路线v1的推理：
- C01：先从无先修的观察事实与推测取得起点线索；尚无作答，不判掌握。
- C02：事实辨析后再比较稳定属性；须先取得C01证据与家长确认。 仅为未来候选，进入前必须重新校验发布和先修。
- C03：比较属性后才确定分类标准并检验反例。 仅为未来候选，进入前必须重新校验发布和先修。
- C04：沿W03叙事在属性比较后检验生成规则。 仅为未来候选，进入前必须重新校验发布和先修。
- C05：结合分类与规律，用有序列表避免遗漏。 仅为未来候选，进入前必须重新校验发布和先修。
- C06：在事实与枚举基础上检查条件方向。 仅为未来候选，进入前必须重新校验发布和先修。
- C07：基于事实与条件推理审查证据和替代解释。 仅为未来候选，进入前必须重新校验发布和先修。
- C08：证据判断后组织理由并公平倾听。 仅为未来候选，进入前必须重新校验发布和先修。
- C09：枚举与条件推理后分解目标和限制。 仅为未来候选，进入前必须重新校验发布和先修。
- C10：论证与约束基础上比较不同需求和取舍。 仅为未来候选，进入前必须重新校验发布和先修。
- C11：沿W09叙事，在明确约束后产生不同方案；索引关系为穿插关系。 仅为未来候选，进入前必须重新校验发布和先修。
- C12：约束与发散之后按标准测试原型。 仅为未来候选，进入前必须重新校验发布和先修。
- C13：整合枚举、证据与约束，选择跨情境策略。 仅为未来候选，进入前必须重新校验发布和先修。
- C14：沿W11—12集中规划反思；可贯穿的元认知不视为提前授权。 仅为未来候选，进入前必须重新校验发布和先修。

问题原文：桌上有红笔和蓝书。有人说：“一定有人刚写过作业。”哪部分是看到的，哪部分是猜测？
回答原话：未收到。提示：无（H0）。分析：unknown。假设：无。动作：等待实际回答。原因：诊断先行，不预测或代答。家长观察：只有陪同声明，其余unknown。

## 恢复检查点
读取state.json、turns.jsonl和personal-roadmap.json。重新Survey、检查结构、recommend和实时发布/先修门禁，再coach progress/show恢复未答原题；不自动跳过。先保存原答再分析并更新状态与路线。正式测评完成后capture，动态练习不能记作审核卡。疲劳、拒绝或挫败立即停止并保存。无80%掌握结论，无固定能力标签。

## 2026-11-08T10:52:51.984596+00:00 回答与下一检查点
- 孩子原话：看到的是红笔和蓝书；有人刚写作业是猜的，因为我没看见有人写。
- 提示H0。AI临时评价correct/valid：正确区分材料与对过去事件的推测。本题理由有效，无具体误区证据；不推断其他情境或掌握。
- coach attempt保存原答；complete完成C01题，诊断会话仍active。未capture，等待整个测评结束。
- C02进入仅作起点诊断：重读根index、attribute-comparison及试点overview/index、C02、project-research；结构检查通过，coach show即时门禁通过。正式教学先修仍未满足。
- recommend仍collect_or_reinforce C01。路线v1顺序保持，诊断不改掌握。家长观察unknown。
- 当前未答原题：甲卡有一个红圆形；乙卡有一个蓝圆形。说一个相同点和一个不同点。
- 提示无；回答未收到；分析unknown；动作等待；恢复先核门禁并恢复此原题。

## 2026-11-08T10:53:33.539436+00:00 C02诊断本题追问
- 原答：它们形状相同，因为颜色不一样。
- coach即时门禁通过，attempt保存correct/invalid；会话仍active，不complete、不capture、不升级。
- 分析：形状判断正确，但颜色不同不足以支持该判断；可能混用维度或只是连接词表达不清，待验证，无稳定能力结论。
- 提示：无；家长观察unknown。路线v1保持，C02正式教学未授权。
- 当前待答追问：我们再看看你的理由，你愿意用另一种方式说明吗？
- 原测评题保持不变；恢复先核对progress及门禁，不跳题。

## 2026-11-08T10:54:05.244362+00:00 暂停
- 孩子原话：我累了，不想再想了。
- 动作：coach pause成功，status paused；立即停止，不提问。
- 未答理由追问和原题保留；疲劳不作为错误或0分，不推断稳定能力。路线v1及掌握unknown保持。家长观察unknown。
- 恢复：由孩子愿意继续时重新survey和门禁，resume/progress后恢复当前题；不跳过、不结束测评、不capture未完成测评。

## 2026-11-08T10:54:54.916976+00:00 恢复
- 用户原话：继续学习。
- 重读根index、全部14概念、12周计划及试点overview/index、C02、project-research。结构检查通过；coach resume/progress/show已核验当前题版本发布，status active。
- 当前仍为PILOT-DIAG-C02@1.1.0，原答与待验证假设保留；未将继续当跳过或新作答。
- 推荐仍C01 collect_or_reinforce；无已掌握概念，不插入复习，C02正式教学未授权。路线v1保持，仅刷新快照。
- 原题：甲卡有一个红圆形；乙卡有一个蓝圆形。说一个相同点和一个不同点。
- 待答追问：我们再看看你的理由，你愿意用另一种方式说明吗？
- 提示无；回答待收；家长观察unknown；动作等待，不预测。

## 2026-11-08T10:55:42.148560+00:00 不理解分支
- 原话：我还是不明白，我不会。
- coach attempt已记录unknown/none；当前题仍active，未完成，不capture。提示未增加。
- 分析：本次无法理解原因unknown；原跨维度/表达不清假设保留待验证，无能力标签。
- 动作及原因：再次不理解且曾疲劳，停止重复追问，提供不同平行例子或休息；不编造或泄漏原题解析。
- 待答选择：你想看看一个不同的小例子，还是先休息？
- 路线版本1保持；家长观察unknown。恢复保留当前题和选择，选例子用coach demo，选休息立即pause。
