# ArchScope

An architecture-first workbench and Codex plugin for local software projects. Define module boundaries in a constrained `.arch` file, inspect them as a graph, run explicitly allowlisted scenarios with real event evidence, check Python source boundaries, and coordinate scoped repair tasks that require human review.

[简体中文](README.zh-CN.md) · [Windows install](INSTALL.md) · [Contributing](CONTRIBUTING.md) · [MIT License](LICENSE)

## Current status

This repository is a Windows-first **early release**, not a feature-complete product. Version 0.11.7 supports visual editing of modules, ports, and declared flows, but edits create a pending `.arch` proposal; they do not alter the formal architecture until a person reviews and approves the diff. Dragging nodes changes only the current layout. It also checks that a target Python interpreter can actually run before creating a scenario operation, avoiding misleading `observation_lost` results from Windows app execution aliases.

The 0.11.7 Windows package has not yet completed the full real-host repair loop, trusted Hook delivery, or external protected CI. Hooks are optional and untrusted by default. Linux packaging is deferred until the Windows experience is stable. The Windows package includes third-party license notices; they are an inventory of redistributed components, not a substitute for release review.

Check [GitHub Releases](https://github.com/jjy1226609858-ui/archscope-codex/releases) for a versioned Windows ZIP and its SHA-256 checksums. If no Release is available yet, a signed-in GitHub user can download the temporary package from **Actions → Windows CI → latest successful `main` run → Artifacts**. CI uploads only after tests, privacy audit, package validation, and demo runs pass. Actions artifacts expire after 30 days; neither download route is a protected external attestation.

## Known limits

- The prebuilt package is Windows x64 only. The local workbench opens without a separate Python install, but running a Python target requires that project's working Python 3.11+ environment; see the [installation guide](INSTALL.md).
- The browser workbench opens outside Codex. It does not control an existing Codex conversation automatically. A repair task remains waiting until Codex explicitly claims it.
- Local architecture and task-scope review is a collaborative safeguard, not strong protection against a malicious program running as the same OS user. Protected external approval and CI are not bundled.
- Chinese UI is available, but not every backend diagnostic has a custom Chinese summary. Full same-version Codex end-to-end repair and Hook delivery remain to be verified.

## What works

- Read and validate a restricted `.arch` architecture, inspect modules and interfaces, and browse historical revisions.
- Use the local browser workbench in English by default, with a persistent Chinese UI switch. Backend diagnostic details are English-first; the workbench supplies Chinese summaries for common diagnostic IDs while retaining the original detail. Project-authored names retain their source language.
- Edit modules, ports, source bindings, and declared flows visually; submit a validated candidate for explicit human review.
- Run only registered profiles against a separate target Python environment. Event overlays distinguish actual failures, missing observation, and not-run states.
- Check Python source boundaries without importing application modules.
- Prepare evidence-bound repair tasks with file scope, lease ownership, independent tests, and explicit scope approval.

## Local development

Requires Python 3.11+ and Node.js. In this source checkout, install the pinned Python requirements into a virtual environment and build the web UI:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
cd web
npm ci
npm run build
```

Then return to the repository root and run the tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The portable Windows plugin has a bundled service runtime but does **not** include an interpreter for a user's Python project. For an existing registered project, run `archscope.exe configure-python <project-id> --python <absolute path to python.exe> --registry <projects.json path>`; the workbench shows a command with the correct registry path when none is found. Start a new Codex task and reopen the workbench afterward so the service reloads the registry. The command validates Python 3.11+ and changes only the interpreter setting. You can also set `ARCHSCOPE_TARGET_PYTHON` before launching the plugin. A Windows Store app execution alias is not a usable Python interpreter.

## Architecture and safety model

The graph, checks, runs, proposals, and repair tasks share one backend model. Browser layout is not a second architecture source. The local server binds to loopback, restricts Host and Origin, rejects cross-site writes, and requires a per-process browser session token for HTTP writes. The token stays in page memory rather than a URL or local storage. This mitigates browser cross-site requests, **not** malicious programs running as the same OS user; local approval is still a collaborative boundary. Runtime profiles are allowlisted; the workbench does not accept arbitrary shell commands. A proposal or repair declaration cannot self-approve. A passing source check alone is not a release gate; an approved architecture baseline and, where configured, external CI attestation remain separate requirements.

## Contributing and release

ArchScope is released under the [MIT License](LICENSE), with copyright attributed to Archie. Contributions are welcome; read [CONTRIBUTING.md](CONTRIBUTING.md). Do not upload a development tree, personal `PLUGIN_DATA`, virtual environment, cache, run evidence, or local paths as a release artifact. Build an allowlisted source archive with `tools/build_public_source.py`, then inspect it and the reproducible Windows package before a GitHub release.

The workbench and plugin metadata are English-first. The [Chinese overview](README.zh-CN.md) is also maintained; Chinese diagnostic summaries are not yet exhaustive. The Windows binary package includes `THIRD_PARTY_NOTICES.md` and copied dependency license texts.
