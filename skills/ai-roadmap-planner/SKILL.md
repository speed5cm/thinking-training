---
name: ai-roadmap-planner
description: 根据本仓库 Wiki、诊断及化名学习记录生成或更新个人思维训练 Roadmap；仅提供规划，不执行教学。
---

# AI Roadmap Planner

本仓库工作流可由 Codex 直接读取本文件执行；它是仓库内 Skill，未安装到用户全局技能目录。全程仅在本仓库工作，不调用外部模型 API。

1. 确认化名，使用 `pilot-c01-c02/records/<化名>/`；遵守现有 coach 的化名规则。只在该目录读写画像 `planner-profile.md`、当前 `personal-roadmap.json` 及可选的历史副本；这些文件均不进 Git。不要收集姓名、学校或位置。个人文件不等于加密或访问控制。首次无画像时，依据家长提供的诊断/偏好记录必要信息，不自行编造；未知明确写未知。诊断不能证明掌握。
2. 从项目根运行 `python3 scripts/validate_personal_roadmap.py context --learner <化名>`。失败则停止；读取输出中的基础课程、证据聚合、即时建议及三个摘要。重新完整读取 `wiki/index.md`、全部 14 个概念页、`curriculum/12-week-plan.md`、`references/pedagogy.md`、`references/sources.md`；本仓库没有 overview，以索引、概念页和课程计划的叙事为适配，不假称存在 overview。阅读该化名画像、已有 roadmap、coach 事件和证据（如有），遵循 `docs/minimal-evidence-design.md`。若记录或来源冲突，标出并停止受影响部分；不从常识补造概念。
3. AI 实际分析定义、教学动作、误区、目标、新情境、能力、来源、硬先修和可穿插关系，以及诊断、不同机会的证据、提示和家长反馈。推理学习顺序、跨概念联系、复习与穿插，明确区分观察、推测和缺失。覆盖所有现有概念；不以单次回答、诊断、路线中的先后、或 AI 的判断宣布掌握/跳过先修。复习安排说清触发条件；无证据支持具体日期就不虚构。需要新增概念、修改依赖或材料时只列审校建议，不修改 Wiki、正式元数据或题卡。
4. 输出 JSON 到该化名目录的临时文件，字段及示例见 `examples/ai-roadmap/fiction-plan.json`：`schema_version`、`learner`、context 的 `curriculum_digest`、`evidence_digest`、`learner_digest`、`steps`、`gaps`、`revision_suggestions`。每步 `kind` 为 `introduce`（未来概念首次列入）、`review` 或 `interleave`，另含 `concept`、非空 `reason` 和 `wiki_pages`（至少本概念 Wiki 路径）。每个概念恰有一次 introduce；所有硬先修的 introduce 在其之前；复习/穿插仅在该概念列入之后。顺序仅是条件性的未来安排，不表示完成、掌握或教学授权。引用相关概念页说明跨概念理由；来源编号回查来源登记。允许记录资料不足和待审建议。
5. 运行 `python3 scripts/validate_personal_roadmap.py validate --learner <化名> --plan <临时文件>`。通过后才替换个人 `personal-roadmap.json`，保留必要的旧版本于同一私有目录；失败修正或停止。结果中的 `current_recommendation` 来自现有证据模块，不由 AI 改写。验证器只检查结构、引用路径和快照，不证明文本推理正确；AI 和家长仍须核查依据、顺序和教学适当性。
6. 每次诊断、学习事件、证据、家长确认或 Wiki 变化后重新读取、分析并校验更新，避免覆盖已有记录；恢复时再次 survey。进入或恢复正式教学始终通过原 coach 的 Wiki 和已发布题卡门禁及家长陪同流程；无法取得适合的已发布材料就等待，不临时生成正式题卡。规划可列未来概念，不能把它们当作当前可教。现有证据模块尚不能评定 C03—C14 的掌握或对其授权。
