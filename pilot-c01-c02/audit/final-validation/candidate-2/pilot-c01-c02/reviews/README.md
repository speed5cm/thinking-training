# 人工审核登记

每张卡在 `reviews/<题号>@<版本>.json` 中由成人自行填写，结构示例：

```json
{"card_id":"ST-C01-01","version":"1.0.0","content_sha256":"脚本 hash 命令输出的完整值","transitions":[{"state":"verified","actor_type":"human","actor":"审核者代号","time":"2026-11-04T09:00:00+08:00","note":"核对题面、答案、来源、年龄及三级提示"},{"state":"approved","actor_type":"human","actor":"审核者代号","time":"2026-11-04T09:05:00+08:00","note":"人工最终批准"},{"state":"published","actor_type":"human","actor":"发布者代号","time":"2026-11-04T09:10:00+08:00","note":"允许在家长陪同试点使用"}]}
```

依次为 draft → verified → approved → published。verified 可由 AI 检查后登记为 `actor_type: ai`，但 approved 和 published 必须由成人自行核对并填写 `human`；本工具不提供自动批准或发布命令。`content_sha256` 覆盖完整题卡，包括题干、答案、解释、全部提示、示范、来源、版本及草稿状态。各版本的题卡快照须保存在 `cards/archive/<题号>/<版本>.json` 并与 `cards/versions.json` 的版本散列一致；历史版本和审核记录不可覆盖。任何内容变化必须采用新版本并重新审核；hash 不符即停用，旧批准不继承。

记录只是本地人工声明，不具备身份认证或防篡改能力，项目目录写入者可伪造文件。正式陪同试教前，家长须核验作者、签名、时间及实际内容，确保只有可信成人维护本目录；此机制不构成权限边界。
