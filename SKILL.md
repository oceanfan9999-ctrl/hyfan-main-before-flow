---
name: hyfan-main-before-flow
description: 从海洋 ERP 的混合调试分支 haiyangtest 审核提取正式修改到 hyfan-main-before，以单批次经 dev 测试后发布 main；包含提交信息确认、增量记录和发布版本校验。用于替代旧 promote-clean-branch 精选流程，不用于 hyfan/feat-* 干净功能开发。
---

# Hyfan 发布候选分支流程

## 最高优先级安全规则

**永远不得把未经用户明确确认的任何代码、文件推送到 main 或 dev，普通推送同样受此限制。即使内容已确认，也禁止任何强制推送，包括 --force、--force-with-lease 和带 + 的 refspec。**

批准必须对应实际最终内容、目标分支和完整 SHA；文件清单获准不代表同一文件的所有未来修改获准。含歧义、新文件、冲突处理、额外代码、版本变化时必须停下重新确认。分支权限或用户笼统说“推吧”不等于未展示内容已获准。
不要用先推送后回滚补救未确认发布。不自动覆盖远端更新、不自动解冲突、不绕过 Git hooks。直接推送需明确授权，否则只准备审核/合并请求；合并请求也不得自动合并未经确认内容。
当前技能只按用户指定阶段执行：提取、发布 dev、发布 main；不因调用技能而连跑到 main。

## 项目与分支

| 仓库 | 原调试工作区 | 默认候选工作区 |
|---|---|---|
| backend | D:/codesSpace/qinglin/standalone_website_erp_django | D:/codesSpace/qinglin/hyfan-worktrees/main-before |
| frontend | D:/codesSpace/qinglin/standalone_website_erp_web | D:/codesSpace/qinglin/hyfan-worktrees/main-before-web |

- 原分支 `进销存系统26-08-26-haiyangtest` 保留日志/Mock/未提交修改；不得切换、stash、清理、重置或提交原工作区。
- `hyfan-main-before` 仅是 main 加已审核正式修改的候选集。不得 merge dev、haiyangtest、haiyang-clean-for-dev 进来；不以混合源分支整体 squash/cherry-pick 代替审核。
- 现有工作区先核对 Git 归属、分支和状态再复用。仅在确实不存在且用户授权初始化时，从最新 origin/main 建立。不覆盖已有目录/分支。
- 不在候选区日常开发或加调试代码。为适配 main、整理迁移和处理冲突所需改动可在候选区进行，但必须单独展示、确认、记录和验证。
- 前后端独立 Git 仓库，不能假定同一状态；无改动的一边标记不涉及。两边发布非原子，部分成功必须如实报告，不自动回滚另一边。

## 批次、入口与低成本检查

每个需求批次使用唯一 `YYYYMMDD-主题-序号` ID。前后端共享批次 ID、各自记录 SHA。一次仅一个活动批次；进入 dev 测试后冻结，只纳入该批次修复并重测，其他需求保留在源区待处理。
先读各仓库 AGENTS，检查两原区及候选区状态；只阅读相关业务规则，不加载全仓库历史。接着读 [流程与记录](references/workflow.md) 中本阶段及记录部分。
使用 `scripts/preflight.py snapshot --repo <路径>` 获取只读摘要；更多接口见该参考及 `--help`。脚本不 fetch、不写文件、不提交、不推送；本地 origin 引用不是远程实时状态。
第一次完整审核与本需求相关的候选差异；后续用上次源 SHA、相关文件指纹和待处理清单缩小范围。SHA 以前未提取的修改不能遗漏；指纹只是变化检测，不能替代批准。最终仍审查候选相对 main 的完整正式差异。
不保存完整请求体、密钥、未脱敏业务数据或全量源 patch。日志候选按文件/行定位后只读相关片段。不用 patch-id 自动认定批准，不把老源文件覆盖 main 新内容。

## 提取边界

逐文件/片段列 Include、Exclude、Needs decision，用户确认后才应用。已确认范围可复用，但内容变化需重审。
默认排除临时 info/debug/print/console 跟踪、Mock/测试数据/本地测试脚本、环境文件、运行产物、依赖与构建输出；不要因 main 已有这些文件而删除它们。必要 warning/error/exception 和接口审计保留；用途不明的 info 日志先问。测试文件是否纳入遵循用户当次范围，不机械删正规的已有测试。
迁移按 main 依赖链检查，不直接复制源分支旧链。特别注意旧 dev/个人库可能使用与 2026-09 main 首次易仓建表不同的迁移历史；需核对实际历史与表结构，禁止默认 fake 或删除历史迁移。

## 提交阶段：每个业务或集成提交都适用

1. 根据已确认且实际暂存的 diff 自动生成 commit message 候选；不得根据需求名称猜测内容。
2. 使用 Conventional Commits：`type(scope): description`，scope 可省略。前后端分别描述真实纳入内容，未执行的测试/部署不能写成已完成。
3. 向用户展示候选 message、暂存摘要及需审查的片段，记录确认依据。**用户确认后才能执行 git commit。** 发布授权不替代 message 确认。
4. 确认绑定 HEAD、暂存 diff SHA-256、merge parents（如有）及完整 message；提交前只读 gate 检查全部匹配。任何变化需重确认。
5. 成功后核对实际父提交、内容和 message 与确认一致，将完整 commit SHA 写入 batch record。hook 改变内容或 message、提交失败时停止，不自动 amend 或跳过 hook。
6. dev 集成用 `git merge --no-ff --no-commit <候选完整SHA>`，先审查结果并确认 Conventional Commit message，再执行 commit，不能未经确认自动创建 merge commit。

## 验证和交付

Python 语法、相关前端类型/静态检查、迁移模型一致性按变更范围执行。Django 命令先确认加载配置和数据库访问范围；无安全环境就列未验证，不能为通过检查改业务配置。
不调用正式易仓/YY、不生成业务 Mock、不执行数据库迁移或 --fake、不重启/部署。迁移/部署需要另行授权。
最终只报批次、每仓库 commit/目标/结果、验证和未验证项、排除/待处理项。技能是操作约束和校验辅助，不是服务器端分支保护；JSON 和脚本通过不替代真实用户确认。
