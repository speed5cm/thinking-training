# Sigma 隔离续测报告

对象为合成化名 `test-startup-01`，含测试者生成的虚构回答，不使用真实儿童数据。未变更题卡、审核或儿童正式入口。

## 通过

1. 模拟家长明确确认候选摘要 `4af2fbdecf352b253e12ec3936f0b2b8e76577b4d641bd277829315c65f97f7e`，`publish` 成功，路线 v1 初始状态 current。见 `publish.json`。
2. 独立的新 Agent 会话核验路线 v1、课程结构及 C01 门禁，从 revision 5/6 恢复唯一未答题 `fresh-001` 的原文。该 Agent 会话没有继承此前对话。见 `session-final.json`；父 Agent 日志快照保留跨 Agent 交互。
3. 针对新的虚构错误回答进行追问、提示和降低难度；保存四轮动态问答及逐题分析。首次平行题存在歧义：未说明杯子拿来时是否有水。测试回答指出歧义后，Agent 承认并修正题设；不能把该次平行题设计计为通过。
4. 根据 `fresh-001` 安排 C01 动态复习任务 `470ba207-7877-49c8-bd3e-bc3112db1567`，暂停后恢复时能读回任务，状态 pending，尚未到期；未提前完成。见 `plan-final.json`。
5. Coach C01 门禁通过，正式训练会话 `6a157a1f-d9e4-4c34-805f-d67fe7fe638c` 已完成，采集一条明确标注虚构的正式训练记录。采集前正式证据机会为 0；采集后 C01 为 1 次机会、1 个会话、1 张卡。核对唯一证据的原答来自 Coach，动态问答没有计入正式证据。mastery 仍 pending_confirmation，未确认迁移。见 `evidence-before-coach.json`、`evidence-final.json` 和 `coach-final.json`。

## 失败和限制

- 实际运行 `codex exec --ephemeral` 启动独立操作系统进程时，在应用服务器初始化阶段因只读文件系统失败，见 `agent-resume.stderr`；随后使用全新独立 Agent 会话恢复成功。后者不能冒称独立 OS 进程启动通过。该独立 Agent 会话没有可导出的原始工具调用日志；会话持久化事件和父 Agent 日志可供审计，但不能代替其完整原始日志。
- 第一个低难度平行例子题意含糊；受测试者指出后才发现并纠正。
- Agent 第一次 capture 遗漏 session 和输入，脚本拒绝；补足参数后成功。不能称为一次无错误完成。
- 采集正式证据后路线 v1 因证据摘要变化显示 stale；原动态复习任务仍 pending、未到期。受影响复习必须在按协议核验并更新路线之后才能推进。Coach、Sigma、证据和规划是独立存储，不是跨文件原子事务。

## 未执行

- 未模拟到期或完成动态复习，也未验证完成后自动安排下一次；本次只验证安排与暂停后的任务恢复。
- 未验证 C02 真实晋级、新 C01 题卡或发布维护；未确认 C01 掌握。
- 没有重规划或发布新版本；本轮模拟确认只绑定原候选 v1。

`parent-agent-log-snapshot.jsonl` 是实际父 Agent 当前运行日志的中途快照，包含复制时之前的执行与交互，可能含环境和工具输出，应限制传播。`agent-resume.jsonl` 和 `.stderr` 保留独立进程失败的原始输出。`session-final.json`、`plan-final.json`、`evidence-final.json` 和 `coach-final.json` 是各自接口的真实读回，不是人为编造的 Agent 执行日志。
