# 思维训练知识工作区

从本目录启动编码代理，要求它先读取这里的 `AGENTS.md` 和 `upstream/AGENTS.md`。此处是独立研究库，所有生成内容待人工审核，不是 Sigma 或儿童入口。上游版本、适配、已验证与局限见 [验收报告](reports/acceptance.md)，清单见 [manifest.json](imports/manifest.json)。

## 日常工作

1. 选择无儿童个人信息、具备处理权限的资料，保存到 `raw/` 的新版本路径；登记原始路径、来源类别、SHA-256 和排除范围。不要更改现有快照。
2. 让代理执行 `ingest raw/路径`；依工作区规则先对照索引、现有来源及概念身份，按上游工作流写来源页、更新概念与综述、标记冲突和缺口，再记录日志。引用原始材料不能等同证明其结论；不把新理论加入课程。
3. 让代理执行 `query: 问题`、`health`、`lint` 或 `build graph`。无需 Python API 的代理工作流仍依赖编码代理理解与执行，语义判断不是确定性程序。需要留存查询时明确要求保存综合页。
4. 本目录运行 `python3 tools/health.py --json`、`python3 tools/ingest.py --validate-only`、`python3 tools/build_graph.py --no-infer`。`graph/graph.html` 依赖网络加载 vis-network；无网络时可读取 `graph/graph.json`。上游脚本所需 Python 版本为 >=3.10,<3.14；网络和依赖、模型凭据按需准备。
5. PDF、DOCX 等经上游 `markitdown[all]` 转换（`pyproject.toml`），转换可能产生同名 `.md` 并覆盖，先在隔离临时副本转换，核查文字提取结果与授权再导入；扫描 PDF 的 OCR 能力取决于工具与环境，未验证。原生 Python API 工作流还需 `requirements.txt` 中的 LiteLLM、配置合适的 `LLM_MODEL` 和凭据；graph 社区检测需 networkx。当前环境均未安装，这些路径尚未端到端验证。
6. 增量修改前备份工作区，在隔离副本执行并比较来源、概念、索引、综述和日志；确认无重复、误覆盖与断链后再迁入。`refresh.py --dry-run` 没有缓存时会把所有来源标为待刷新，不能把它当去重证据。脚本不会保证原子恢复，失败后应还原备份并核对差异。
