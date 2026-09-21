# ArchScope

ArchScope 是面向本地软件项目的架构工作台和 Codex 插件。用受限的 `.arch` 文件定义模块边界，在图上查看和编辑架构候选，运行项目白名单中的场景并查看真实事件证据，检查 Python 源码边界，协作处理需要人工审阅范围的局部修复任务。

[English](README.md) · [Windows 安装](INSTALL.zh-CN.md) · [贡献指南](CONTRIBUTING.md) · [MIT 许可](LICENSE)

## 当前状态

项目目前是 **Windows 优先的早期公开版**，并非功能全部完成的正式产品。0.11.7 支持在工作台增加、删除模块和端口，并拖线创建声明的数据流。结构编辑会生成待审 `.arch` 候选；人工查看差异并批准之前，正式架构不会改变。拖动节点仅调整当前画面布局。

运行 Python 场景前，插件会检查目标解释器是否真实可执行且为 Python 3.11+。工作台会在未找到候选解释器时提前显示配置命令；`configure-python` 仅更新指定项目的解释器，不清除其他登记信息。0.11.7 的浏览器写请求要求同源校验和进程内会话令牌，会话接口也拒绝跨站请求，且只允许本机地址；这不构成对同一 Windows 用户下恶意程序的强隔离。同版本完整 Codex 宿主修复闭环、Hooks 实际投递和外部受保护 CI 尚未验证。Linux 打包后置。

正式 GitHub Release 附件发布前，已登录 GitHub 的用户可到 **Actions → Windows CI → 最新成功的 `main` 运行 → Artifacts** 下载临时 Windows 包。CI 仅在测试、隐私扫描、打包验证和示例运行通过后上传；该产物 30 天后过期，不是永久 Release，也不是受保护的外部签名验收。

## 已知限制

- 预编译包只支持 Windows x64。打开本机工作台不需另装 Python；运行 Python 目标项目仍需该项目可用的 Python 3.11+ 环境，见 [安装说明](INSTALL.zh-CN.md)。
- 工作台在 Codex 外的本机浏览器打开，不会自动控制现有 Codex 会话。修复任务须由 Codex 明确领取。
- 本机架构与任务范围审阅是协作保护，不足以抵御同一 OS 用户权限下的恶意程序；受保护的外部批准和 CI 尚未随包部署。
- 中文界面可用，但并非每条后端诊断都有专门中文摘要。同版真实 Codex 完整修复闭环和 Hooks 投递仍待验证。

## 使用边界

- 工作台默认显示英文，可切换中文并记住选择。后端诊断以英文为基线，工作台在中文模式为常见诊断码提供中文说明并保留英文技术细节；并非所有诊断都有专门中文译文。项目自行编写的名称和内容保留原文。
- 运行只允许使用项目登记的白名单档案；网页不能提交任意命令。
- 插件携带独立服务运行时，不携带可运行用户 Python 项目的通用解释器。项目需提供真实 Python 3.11+ 路径，可通过 `register-project --python <绝对路径>` 登记，或在启动插件前设置 `ARCHSCOPE_TARGET_PYTHON`。
- 架构候选和任务范围不能由 Agent 自行批准。未运行、未观测、检查通过和正式验收是不同状态。
- Hooks 是可选功能；安装插件不等于信任 Hooks，需由用户审阅。

## 源码开发

需要 Python 3.11+ 和 Node.js。在源码目录创建虚拟环境、安装依赖并构建工作台：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
cd web
npm ci
npm run build
```

回到仓库根目录运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 参与和发布

项目采用 [MIT License](LICENSE)，版权署名 Archie。欢迎阅读[贡献指南](CONTRIBUTING.md)参与开发。公开发布时只使用经过允许清单和隐私扫描生成的源码包，不上传虚拟环境、缓存、个人插件数据、项目运行证据或本机路径。Windows 包已随附第三方许可清单和文本，但正式发布前仍需审阅。
