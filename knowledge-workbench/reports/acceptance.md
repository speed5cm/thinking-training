# 第一阶段验收与限制（2026-11-09）

## 版本和范围
上游 https://github.com/orionpax1997/llm-wiki-sigma-agent ，检出 commit `4bc20999ac502ea4899bdf144dc539f6f9ef015f`。`tools/`、`CLAUDE.md`、依赖文件为该提交的原件；`upstream/` 保留原始指令、许可与依赖，新增本地 AGENTS 边界、知识库、清单和报告。未引入上游 Sigma 教学 skill。Python 工具按脚本位置决定根目录，因而引用本工作区。图谱只识别不含路径的唯一页面名，工作区按此适配 WikiLink。保留上游 MIT 许可文件。

## 实际完成
先生成清单再复制 23 个资料快照：正式索引、14 个概念、课程、两份参考、5 个试点 Wiki 文件；原路径与摘要见 `imports/manifest.json`。题卡和题卡审计是历史样例/测试而非研究，记录排除；没有导入学习记录。按上游编码代理 Ingest 工作流建立 23 来源页、14 个原编号概念页、总览、索引、日志和证据综合页；每个概念页保留原始 R 编号及先修，来源映射属于项目关联而非效果证明。参考来源均为项目整理，原始外部研究未逐篇读取；未核查外部链接现状，所有内容待人工审核。

## 检查（命令在工作区内）
- `python3 tools/health.py --json`：退出 0，39 页，无空页、索引缺失和日志缺口，见 `health.json`。
- `python3 tools/ingest.py --validate-only`：退出 0，无断链、未索引页面；验证器只按文件名匹配，不能证明语义正确。
- `python3 tools/build_graph.py --no-infer`：退出 0，39 节点、122 边（最后重建结果见 `graph-run.txt`）；仅显式链接，未运行 LLM 推断；未安装 networkx，社区检测不可用；HTML 通过 CDN 加载 vis-network，不是离线自包含，浏览器交互未验证。
- `python3 tools/lint.py`：实际执行，结构检查见 `lint-cli.txt`；语义检查因未安装 litellm 退出 1，不能称完整 Lint 通过。代理按上游 Lint 流程另行检查证据、冲突及缺口，结果见 `wiki/syntheses/evidence-boundaries.md`；这不是系统化研究综述。
- `python3 tools/query.py 'C07 和 C14 的来源及其证据边界是什么？'`：定位 4 页后因缺 litellm 退出 1，见 `query-cli.txt`。编码代理按上游 Query 流程查询并留存 `reports/query-agent.md`，已执行；API 模式未通过。
- `python3 tools/refresh.py --dry-run`：首次无缓存报告 23 个待刷新，不意味着全部发生变化，见 `refresh-dry-run.txt`。

## 增量与故障测试
在 `/tmp` 中复制工作区进行原生 `tools/ingest.py` 测试，使用本地模拟 LiteLLM 响应（不是真实模型，不验证模型判断）：同一资料两次导入及追加标记后再次导入，固定 slug 的来源页为 1 个，但索引重复 3 条；修改后来源页变为模拟返回的新内容。模拟响应不更新概念，所以未证明相关概念可自动更新。去掉模拟依赖后脚本因缺 litellm 退出 1，调用前后 Wiki 字节哈希相同；这只覆盖 API 调用前失败，不能证明写入中途失败可回滚。详见 `incremental-test.txt`。上游直接覆盖模型返回路径，缺乏事务、去重保证和自动恢复；不得直接在正式工作区运行脚本，见 README。

## 待验证和不处理
真实模型 API 的 Ingest、Lint、Query、语义图谱、PDF/Word 转换、networkx 社区检测、浏览器交互和真实增量更新未验证。当前 Python 3.14.4 超出上游声明范围（>=3.10,<3.14），已运行的无依赖命令成功不代表完整兼容。没有改变教学资产、真实儿童入口、课程或授权；无新增教学 Agent、无自动接入 Sigma。建议人工审查内容和来源，使用受支持的 Python、安装依赖并配置模型后先在隔离副本验收。
