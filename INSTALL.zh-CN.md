# 在 Windows 安装 ArchScope

ArchScope 0.11.7 是 Windows x64 早期版本。插件服务已打包，打开工作台不需要另装 Python 或 Node.js；**运行 Python 目标项目**仍需要该项目可用的 Python 3.11+ 解释器。Hooks 可选，安装插件不会自动信任它们。

[English installation guide](INSTALL.md) · [功能与限制](README.zh-CN.md)

1. 正式 GitHub Release 可用时，从发行页下载 Windows marketplace ZIP。在此之前，登录 GitHub，打开 **Actions → Windows CI → 最新成功的 `main` 运行 → Artifacts → `ArchScope-v0.11.7-windows-x64`** 下载；Actions 产物 30 天后过期。解压到准备长期保留的目录，确认有 `.agents/plugins/marketplace.json` 和 `plugins/archscope/`，不要运行来源不明的程序。
2. 在 PowerShell 中把**解压目录**登记为插件来源，并安装：

   ```powershell
   codex plugin marketplace add "<解压后的 marketplace 目录>"
   codex plugin add archscope@archscope-local
   ```

3. 新建 Codex 任务，确认能发现 `archscope:archscope` Skill 和 ArchScope 工具。让 Codex 对 `mini_planner` 调用 `archscope_health`、`archscope_open_workbench`，打开返回的本机地址。界面默认英文，可切换中文并记住选择。

工作台只监听本机回环地址，不是云端服务。插件文件与项目数据分开；正常 Windows 安装下，示例和登记表初始化在 `%LOCALAPPDATA%\ArchScope\plugin-data`。升级插件时不要删除此目录。

示例架构图不需要 Python 就能打开。运行示例场景若提示 `TARGET_PYTHON_NOT_FOUND`，请选择自己信任的真实 Python 3.11+ 环境。已登记的 `mini_planner` 可使用以下命令配置，替换两个占位路径：

```powershell
& "<解压后的 marketplace 目录>\plugins\archscope\runtime\archscope.exe" configure-python mini_planner --python "<python.exe 的实际路径>" --registry "$env:LOCALAPPDATA\ArchScope\plugin-data\projects.json"
```

也可在启动 Codex 前设置 `ARCHSCOPE_TARGET_PYTHON`。配置后新建任务并重新打开工作台，使服务读取新登记表。Windows 应用执行别名不算可用的解释器；目标项目还可能需要在自己的环境安装依赖。插件健康检查通过不代表目标程序已成功运行。

升级时将新版解压到另一个保留目录。若 Codex 提示 `archscope-local` 已指向旧来源，依次执行 `codex plugin marketplace remove archscope-local`、`codex plugin marketplace add "<新版解压目录>"`、`codex plugin add archscope@archscope-local`，再新建任务。确认新版可用前保留旧包。不要为了升级而直接信任 Hooks。

`codex plugin remove archscope@archscope-local` 只卸载插件及其缓存，不是删除目标项目、`.arch` 或独立运行数据的命令。项目历史应另外备份与管理。源码开发步骤见 [README.md](README.md#local-development) 和 [贡献指南](CONTRIBUTING.md)。
