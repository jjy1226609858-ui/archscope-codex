# Contributing to ArchScope

Thanks for helping improve ArchScope. The project is Windows-first today; Linux
packaging is intentionally deferred. Please keep contributions small, testable,
and safe for projects that users register with the plugin.

## Set up a source checkout

Use Python 3.11+ and a supported Node.js version. Follow the commands in the
[README](README.md#local-development), then run the Python suite and frontend
build before submitting a change:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd web
npm ci
npm run build
```

Do not commit `.venv`, `node_modules`, `web/dist`, `.archscope` project state,
runtime evidence, local credentials, or generated packages. The
`tools/build_public_source.py` script creates an allowlisted source archive and
rejects personal paths and private-key markers; it is a safety check, not a
replacement for reviewing the files in a pull request.

## What to include in a pull request

- Explain the user-visible behavior, the technical change, and how it was tested.
- Add regression tests for parser, governance, runtime, and safety changes.
- Update English UI strings and their Chinese equivalents for workbench changes.
- Keep the `.arch` file as the architecture source of truth. Browser layout and
  run overlays must not silently rewrite it.
- Preserve pending review for architecture proposals and human approval for task
  scope. Do not turn a draft, a missing observation, or a self-check into a pass.
- Avoid arbitrary command execution, broad filesystem access, and unattended
  execution of untrusted target projects.

Please open an issue to discuss a large interface or architecture change before
implementing it. Do not include private project files or raw user run evidence
in issues or pull requests; use a minimal synthetic reproduction.

The included Windows CI workflow runs on pull requests with a read-only token
and no repository secrets. It checks the Python suite, browser build, public
source privacy gate, and isolated packaged demo run. It does not publish a
release, sign trust attestations, or replace maintainer review. The workflow
has not yet run on GitHub for this candidate.

## License

By contributing, you agree that your contribution is licensed under the
project's [MIT License](LICENSE). Submit only work you have the right to share.
