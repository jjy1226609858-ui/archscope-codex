# ArchScope Codex plugin

This directory is the plugin source. The portable layout uses `plugin.json` and
`mcp.json`; the Codex-compatible layout uses `.codex-plugin/plugin.json` and
`.mcp.json`. The `skills/archscope/SKILL.md` file guides architecture-driven
work. `scripts/start_mcp.ps1` starts the bundled Windows runtime when present,
or the source checkout's virtual environment during development.

The Windows candidate package bundles the ArchScope service and the minimal
observation SDK, but **not** a general Python interpreter. Running a registered
Python target project requires its own working Python 3.11+ executable. Use
`register-project --python <absolute path>` or set `ARCHSCOPE_TARGET_PYTHON`
before starting the plugin. Only allowlisted project profiles can run; the
source checker parses files without importing target modules.

Registry data, operations, tasks, and evidence live outside the plugin
installation directory. The first portable launch copies the bundled demo to
the separate plugin data directory. Architecture proposals and repair-task
scope require human review; a task completion declaration is independently
checked against file scope, architecture boundaries, tests, and the approved
baseline.

Hooks are optional. Installing the plugin does not make its Hooks trusted;
review their current contents and hash before enabling them in Codex.
External signed approval and CI attestation are supported as verification
inputs, but a protected external CI deployment is not bundled with this
candidate. Do not represent a local self-check as such an attestation.
