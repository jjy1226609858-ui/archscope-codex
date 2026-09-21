# ArchScope 0.11.7 — Windows early release

ArchScope is an architecture-first Codex plugin for local Python projects. The workbench is English by default and has a persistent Simplified Chinese UI switch.

This early release includes a Windows x64 plugin package and an audited source archive. The plugin opens the architecture graph without a separate Python installation. Running a Python target project requires that project's working Python 3.11+ interpreter and dependencies. See [INSTALL.md](INSTALL.md) or [INSTALL.zh-CN.md](INSTALL.zh-CN.md) before installing.

The workbench can edit modules, ports, source bindings, and declared flows. Submitting an edit creates a pending `.arch` proposal; only explicit human review can make it the formal architecture. Dragged node positions affect only the current view. Scoped repair tasks require a claimed lease and independent verification.

Known limits: the full repair loop in a fresh Codex 0.11.7 task, actual Hook delivery, and the visual approval round-trip have not yet been verified. Hooks are optional and untrusted by default. The local approval UI is a collaboration safeguard, not protection against malicious software running as the same OS user. Linux packaging and protected external CI/approval are later work. Do not interpret a successful plugin health check as evidence that a target Python scenario ran successfully.

Download `ArchScope-v0.11.7-windows-x64.zip`, verify it against `SHA256SUMS.txt`, and follow the installation guide. The package includes the marketplace directory, bundled service executable, English/Chinese guides, MIT license, and third-party notices. `ArchScope-v0.11.7-source.zip` is the allowlisted source archive for review and contributions.
