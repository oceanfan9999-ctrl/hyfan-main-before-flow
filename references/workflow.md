# 阶段操作及批次记录

## 1. 提取至候选分支

读取原区与候选区的 git status、branch、worktree、refs；存在 merge/rebase 等未完成操作则先暂停，不重置。
fetch origin main 和 hyfan-main-before，首次缺少远端候选分支时仅 fetch main。不要假设本地 origin 引用最新。候选与远端不一致时辨别已审核未推送提交和外来修改，不盲目 pull。
无待发布差异时用 `git merge --ff-only origin/main`；有本批次修改且 main 已更新时，普通 merge main，遇冲突暂停确认。需要 merge commit 时用 --no-commit，并走提交确认流程。
根据本次需求、源基准、暂存/未暂存/合格未跟踪文件和 pending 清单定位正式片段。源分支吸收的 main/dev 改动不自动归为用户代码；依赖 dev 独有功能时暂停划定依赖，不偷带 dev。
展示纳入/排除/待确认清单；审核通过后用补丁在候选区应用，不整文件覆盖混合改动。最终 diff 对 main 检查，明确路径/片段暂存，不盲目 add -A。
message 获准后提交。push 候选分支也需内容和目标授权，普通快进推送；远端候选分支首次不存在时记录 target_base=null，不能忽略后来出现的同名分支。

## 2. dev 集成测试

固定 candidate SHA 和 main 基线；进入 testing 后只接受本批次修复，其他改动记 pending。
fetch dev，在独立工作区从它创建 `hyfan/test-<batch_id>-r1`，冲突重做或下一次修复递增 r2，不覆盖旧分支。校验新分支名，禁止目录穿越和任意覆盖。
执行 `git merge --no-ff --no-commit <candidate_sha>`，冲突停下；审查相对 dev 基线的最终差异和 merge parents。dev 专属适配留在集成路径，必须单独确认；不得反向 merge 到候选分支。
经用户确认完整暂存差异和 Conventional Commit message 后提交集成结果。对已在 dev 的候选版本不要制造无意义提交。
用户明确授权 dev 发布后，记录 push approval，检查最新 dev 仍是集成基线，gate 通过后普通 push 指定集成 SHA 到 refs/heads/dev。发现远端变化立即停止，不强推。默认无直接授权则准备普通 merge 的合并请求，不 squash、不自动合并。
记录 dev 推送结果与实际部署 SHA；确认已测部署提交包含候选 SHA，再记录用户测试结论。不知道部署版本就先问，推送不是部署证据。

## 3. main 发布

核对双仓库本批次测试记录：candidate == tested_candidate_sha，已测部署包含 candidate，用户确认了对应版本；候选有本批次新修复则必须重测。
fetch main 后核对仍等于 tested_main_base_sha。发生更新时暂停，同步到候选（冲突须确认）并重新经过 dev 验证，不能直接沿用旧测试。
主分支发布前必须获得最终差异、候选完整 SHA、main 目标和推送动作的明确批准；通过 push gate 后只执行 `git push origin <tested_candidate_sha>:refs/heads/main`，不使用 HEAD/分支名替代已测试 SHA，不使用任何 force 参数。
即便远端更新仍可快进，也不能静默忽略审核基线变化；最后一次 fetch 与 push 尽量相邻，若观察到变化立即停止。普通 push 的拒绝不是需要强推的理由。
成功后读回远端引用核对，前后端分别记录，全部涉及仓库成功后关闭批次。任一失败保留状态，不能提前记 completed。
发布后不擅自 reset 候选或回同步 dev；下批提取再核对并快进 main。部署/迁移始终是另行授权步骤。

## 只读工具

```powershell
python <skill>/scripts/preflight.py snapshot --repo <工作区>
python <skill>/scripts/preflight.py snapshot --repo <源工作区> --paths apps/mall/scm/views.py
python <skill>/scripts/preflight.py gate --repo <候选或集成工作区> --record <批次JSON> --component backend --phase commit
python <skill>/scripts/preflight.py gate --repo <候选或集成工作区> --record <批次JSON> --component backend --phase verify-commit
python <skill>/scripts/preflight.py review-diff --repo <工作区> --base <目标基线SHA> --candidate <待推送完整SHA>
python <skill>/scripts/preflight.py gate --repo <候选或集成工作区> --record <批次JSON> --component backend --phase push
```

退出码 0 表示本次机械校验通过，不等于取得授权或业务测试通过；2 为阻塞，1 为检查错误。snapshot 无发布动作；它的结果可用于填入确认记录，但不得自动填 confirmed=true。
脚本只处理本地引用，不 fetch，不打印 diff/文件内容，不写 Git 对象。diff hash 使用固定无 textconv/ext-diff 的二进制完整 diff；这不是语义等价算法。校验失败不改 JSON 绕过，应重新查明并由用户确认。

## 个人批次记录

放在有效 CODEX_HOME 的 `release-state/hyfan-main-before/<batch_id>.json`（未设置时为 C:/Users/PC/.codex/release-state/hyfan-main-before）。不提交到业务仓库或技能目录。记录写入用 apply_patch 并遵守审批；不能通过编辑记录伪造用户确认。
全局 batch_id、scope、status（draft/testing/ready/partially_published/completed）、created_at；repos 下分别 backend/frontend。无改动一端为 involved=false。
每仓库记录 source_repo/source_branch/source_head、source_fingerprints、main_base_sha、candidate_sha、dev_integration_sha、tested_deployment_sha、tested_candidate_sha、tested_main_base_sha、test_confirmation、migration_compatibility（unknown/verified，verified 必须附实际核验依据）、checks、published_main_sha。
source 基准移动只表示审查位置前移，不表示旧内容全发布。维护 carried pending 列表：path、片段摘要、原因、内容指纹、处置（pending/excluded/extracted）；指纹变化重审，未提取项跨批次保留。不给每个文件永久忽略标签，不记录源码秘密。
提交与推送校验要求如下对象位于 repos.backend 或 repos.frontend 下（SHA/hash 为实际值，未确认字段用 null/false）：

```json
{
  "involved": true,
  "commit_approval": {
    "confirmed": false,
    "confirmation_ref": null,
    "head_sha": null,
    "merge_parents": [],
    "index_diff_sha256": null,
    "message": null
  },
  "push_approval": {
    "confirmed": false,
    "confirmation_ref": null,
    "target": "main",
    "base_sha": null,
    "candidate_sha": null,
    "diff_sha256": null
  },
  "candidate_sha": null,
  "tested_candidate_sha": null,
  "tested_deployment_sha": null,
  "tested_main_base_sha": null,
  "test_confirmation": null,
  "commit_history": []
}
```

确认依据包含用户本次消息的可追溯标识或时间及确认原意，不能仅写“自动批准”。commit_history 保存批准快照、真实 commit SHA、parents、message 和校验结果。每次批准替换之前先保留历史，禁止用同一个 approval 覆盖解释多个不同提交。
commit gate 只保护提交前状态；提交后需对 `HEAD^1..HEAD` 的 diff hash、parents、message 与批准逐项核对，hook 引入变化必须暂停。push gate 独立对最终提交和目标基线检查，不沿用模糊的文件列表批准。

## 检查边界

后端语法/安全隔离 check；模型变化时 makemigrations --check --dry-run。showmigrations/migrate --plan 可访问数据库，先确认范围；无安全环境记录未执行，禁止 migrate/fake。前端执行类型和相关文件静态检查，不自动 --fix 扩大修改。
首次易仓迁移与旧 dev 链兼容性未核实前记录 unknown 并阻塞涉及迁移的发布，不靠 Git 合并成功推断数据库可用。
