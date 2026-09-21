# Install ArchScope on Windows

ArchScope 0.11.7 is an early Windows x64 release. The plugin service is bundled; you do not need Python or Node.js to open the workbench. Running a Python **target project** still requires a working Python 3.11+ interpreter for that project. Hooks are optional and are not trusted automatically.

[简体中文安装说明](INSTALL.zh-CN.md) · [Features and limitations](README.md)

## Install the prebuilt plugin

1. Check [GitHub Releases](https://github.com/jjy1226609858-ui/archscope-codex/releases) for `ArchScope-v0.11.7-windows-x64.zip` and verify its SHA-256 value against `SHA256SUMS.txt`. If no Release is available yet, sign in to GitHub and open **Actions → Windows CI → latest successful `main` run → Artifacts → `ArchScope-v0.11.7-windows-x64`**; Actions artifacts expire after 30 days. Extract the ZIP to a directory you intend to keep, and check that the extracted directory contains `.agents/plugins/marketplace.json` and `plugins/archscope/`. Do not run an executable from a source you do not trust.
2. In PowerShell, register that **extracted directory** and install the plugin:

   ```powershell
   codex plugin marketplace add "<extracted marketplace directory>"
   codex plugin add archscope@archscope-local
   ```

3. Open a **new Codex task**. Confirm that the `archscope:archscope` Skill and ArchScope tools are available. Ask Codex to call `archscope_health` for `mini_planner`, then `archscope_open_workbench` and open the returned local address. The workbench defaults to English; its language switch persists a Chinese UI choice.

The workbench listens only on your computer's loopback address. It is not a remote or cloud service. Installed plugin files and writable project data are separate: on a normal Windows installation the demo and registry are initialized under `%LOCALAPPDATA%\ArchScope\plugin-data`. Do not delete that data directory when updating the plugin.

## Run the bundled Python demo

The demo's architecture graph opens without Python. To run a scenario, ArchScope must find a real Python 3.11+ executable. If the workbench reports `TARGET_PYTHON_NOT_FOUND`, use a Python interpreter you trust. For the already registered `mini_planner` demo, PowerShell can configure it as follows, replacing both placeholders with the paths on your own machine:

```powershell
& "<extracted marketplace directory>\plugins\archscope\runtime\archscope.exe" configure-python mini_planner --python "<path to python.exe>" --registry "$env:LOCALAPPDATA\ArchScope\plugin-data\projects.json"
```

Alternatively, set `ARCHSCOPE_TARGET_PYTHON` before launching Codex. Reopen the workbench in a new task after changing the interpreter so its service reads the updated registry. The command validates the interpreter; a Windows app execution alias is not sufficient. Python targets may also need their own project dependencies installed in that interpreter. A successful plugin health check does not imply a target run succeeded.

## Update or remove

For an update, extract the newer package to a different retained directory. If Codex reports that `archscope-local` already points to another source, run `codex plugin marketplace remove archscope-local`, then `codex plugin marketplace add "<new extracted marketplace directory>"`, then `codex plugin add archscope@archscope-local`. Start a new task to pick up the new Skill and MCP server. Keep the old extracted package until the new installation works. Do not trust Hooks just to complete an update.

`codex plugin remove archscope@archscope-local` removes the plugin installation/cache, not your target project or ArchScope's separate writable data. Historical runs and `.arch` files should be backed up and managed separately. Never delete a project directory as a plugin-uninstall step.

For source development, follow [README.md](README.md#local-development) and [CONTRIBUTING.md](CONTRIBUTING.md). Source development requires Python and Node.js; the prebuilt Windows plugin does not.
