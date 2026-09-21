---
name: archscope
description: Use installed ArchScope tools to discuss .arch architecture, inspect modules and interfaces, observe real runs, recover and claim scoped repair tasks, and verify results. Never self-approve architecture or run unapproved commands.
---

# ArchScope: architecture-driven development

This skill guides use of the 14 installed ArchScope tools. First confirm that the current Codex host actually exposes `archscope_health`, `archscope_get_project`, `archscope_get_module`, `archscope_run_profile`, `archscope_get_operation`, `archscope_cancel_run`, `archscope_check`, `archscope_propose_arch`, `archscope_prepare_task`, `archscope_get_task`, `archscope_resume_task`, `archscope_update_task`, `archscope_read_evidence`, and `archscope_open_workbench`. Reading this file or finding source code does not prove the plugin is installed or connected.

## Start from current facts

Identify the project and worktree; do not infer them from a previous session. Read the current architecture, approval status, code digest, and available tool capabilities. If a tool is missing, say so rather than inventing a call. In a source checkout, follow its README and contribution guidance before making implementation changes.

## Architecture and proposals

Clarify requirements, domains, module boundaries, and inputs/outputs in natural language. Save a candidate `.arch` and show the structural diff and open questions. A draft is not an approved baseline. `archscope_propose_arch` saves only a pending proposal; it cannot approve or overwrite the formal architecture. Human architecture review is deliberately not exposed as an MCP tool. The workbench visual editor likewise submits a candidate; moving a node only adjusts the current layout.

## Scoped repair tasks

For an existing task, call `archscope_resume_task(project_id, task_id)` before acting. It rechecks the current snapshot, lease, and evidence. Claim only after a human has approved scope and the task is claimable. Use `archscope_update_task` with `claim` and a stable session actor ID. For an expired lease taken over by a new session, pass the returned `freshness.snapshot_digest` as `expected_snapshot_digest`; if files change again, resume afresh. Never claim `needs_realign` without new human review or a replacement task.

Respect the exact file scope, unchanged interfaces, neighboring modules, and required tests. Use `archscope_read_evidence` for bounded evidence when needed. A start declaration is not verification. After implementation, submit `declare_complete`; ArchScope independently compares file snapshots and runs the architecture checker, required tests, and approval-baseline check. Only `verified` means verified. Investigate `verification_blocked` and `verification_failed` from evidence. Do not alter the specification, remove assertions, or widen ignores to make an error disappear. After bounded failed retries, report the cause and a proposed next step.

For `archscope_check`, supply both current architecture and code digests. A passing source check alone is not acceptance; the report must also match a current human-approved baseline.

## Graph and real execution

Open the workbench through the tool and describe the actual connection state. The graph comes from architecture; run overlays come from real emitted events. Distinguish not-run from not-observed. A task shown on the graph is not in progress until Codex has actually claimed it. Do not imply that the browser controls an unconnected Codex session.

Run only project-defined, allowlisted profiles, never arbitrary commands. Supply the current architecture digest and a fresh idempotency key, then query the operation by ID. If `observation_enabled=false`, the program ran with probes off: missing events prove neither module success nor failure. Attribute a failure only to real `module.failed` evidence. Cancellation applies only to the precise process owned by the current service. Separate a root-cause inference from an observed exception. Keep evidence reads bounded; do not put entire repositories or large logs in context. Event payloads have sensitive-field redaction and size limits, but do not proactively place raw secrets, full inputs, or user-file contents in summaries.

## Handoff and authority

Record project ID, task ID, version, actual edits, evidence, open items, and next action. A new session should resume by project and task ID, then recheck current facts rather than trusting old digests or requiring the old chat transcript. If the plugin is disabled or lacks a capability, describe the reduced mode without fabricating tool records. This skill is guidance; enforcement comes from independent tools and trusted review. Only a person may approve architecture or broaden task permissions.

## 中文参考

状态：开发包已实现十四个工具：`archscope_health`、`archscope_get_project`、`archscope_get_module`、`archscope_run_profile`、`archscope_get_operation`、`archscope_cancel_run`、`archscope_check`、`archscope_propose_arch`、`archscope_prepare_task`、`archscope_get_task`、`archscope_resume_task`、`archscope_update_task`、`archscope_read_evidence`、`archscope_open_workbench`。只有当前宿主实际列出这些工具时才可调用；不要把阅读本文件或源码中的实现当作安装成功。

## 开始

核对工具能力、目标项目和工作树。读取当前架构、批准状态和代码摘要。缺工具时明确指出，不编造调用；本项目开发中遵循根目录启动任务书。多个项目时不可根据上次会话猜当前目标。

## 需求和结构

用自然语言澄清目标、领域输入输出、模块和边界，保存候选 `.arch`。讨论中允许疑问和未决事项；展示草案图，不把草案当批准基线。向用户展示结构差异，不能直接批准自己的候选。

## 模块任务

先用 `archscope_resume_task` 按项目 ID 和任务 ID 恢复任务；它会重新核对当前快照、租约与证据。确认范围已由人批准且任务可领取后，用 `archscope_update_task` 的 `claim` 动作和稳定的会话 actor ID 原子领取。过期租约由新会话接手时，必须把恢复结果中的 `freshness.snapshot_digest` 作为 `expected_snapshot_digest` 提交；若期间文件又变化，重新恢复，不能沿用旧摘要。`needs_realign` 不能领取，需请用户审阅新范围或重建任务。核对版本、授权文件、不变接口、相邻模块和必需测试；需要时用 `archscope_read_evidence` 读取类型化证据。任务开始是声明，不是验证通过。

完成内部修改后以 `declare_complete` 提交声明；ArchScope 会独立比较文件快照、执行架构检查、必需测试和批准基线核对。只有返回 `verified` 才能称为已验证；`verification_blocked` 或 `verification_failed` 必须按证据处理。不得改规约、删除断言或扩大忽略范围来消除错误。有限重试后仍失败则报告原因与候选方案。

调用 `archscope_check` 时同时携带当前架构摘要和代码摘要。Checker 运行成功不等于验收通过：报告还必须绑定当前人工批准基线。`archscope_propose_arch` 只能保存待审候选，不能批准或覆盖正式架构；人工审阅入口不作为 MCP 工具暴露。

## 图与真实运行

用工具打开工作台并说明实际连接状态。图来自架构，运行来自真实接口事件；未观测和未运行分别显示。图创建任务后，只有 Codex 已领取才说明任务开始；不能声称浏览器控制了没有接通的会话。

读取证据时限制范围，不把大型日志和整个仓库一次性塞入上下文。根因推测与实际异常分开。运行仅调用项目内白名单 profile，不执行任意来源命令。启动时携带当前架构摘要和新的幂等键；用操作 ID 读取结果和事件。`observation_enabled=false` 代表业务运行但探针关闭，不可把缺失事件解读为模块成功或失败。异常只按真实 `module.failed` 归因；取消只针对当前服务拥有的精确进程。事件负载有敏感字段脱敏和大小限制，但不要把原始密钥、完整输入或用户文件内容主动写入摘要。

## 交接与边界

保存项目 ID、任务 ID、版本、实际修改、证据、未决项和下一步。新会话凭这两个 ID 调用恢复工具，不要求用户粘贴旧聊天；仍须重查当前事实，不直接信旧摘要。插件停用/能力不足时说明模式，不用人工伪造工具记录。

Skill 是工作指引；硬检查来自独立工具及可信验收部署。批准架构与扩大权限须由人处理，本 Skill 不能替代。
