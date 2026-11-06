# Double Ctrl Translator

一个 Windows 桌面划词翻译小工具。选中文字后，快速按两次 `Ctrl`，在鼠标附近查看中英翻译。

A lightweight Windows selection translator, activated by a double tap of Ctrl.

## 功能

- 双击左侧或右侧 `Ctrl` 翻译选中的文字，普通 `Ctrl+C`、`Ctrl+V` 不作为翻译快捷键。
- 中译英、英译中，悬浮窗显示原文和译文，一键复制整段译文。
- 悬浮窗采用透明液态玻璃风格：背后的画面轻微模糊后透出来，边缘有折射和高光描边，文字按背景深浅自动变色。颜色、透明度、模糊等都能在“外观设置”里自己调。
- 点击朗读按钮收听原文。
- 系统托盘菜单支持修改 API Key、外观设置、管理开机自启和退出程序。
- Python 源码开放，可自行修改提示词、模型、快捷键参数和界面。

## 环境要求

- Windows 10 / 11。项目使用 Windows 注册表、剪贴板和音频接口，不支持直接在 macOS / Linux 上运行。
- Python 3.11 或更新版本，包含 Tkinter。当前本地验证环境为 Windows + Python 3.12。
- 可访问智谱 BigModel 和 Microsoft Edge 在线语音服务的网络。
- 自己的智谱 API Key。请在 [BigModel 开放平台](https://bigmodel.cn/)申请，模型权限、额度和计费以平台当前规则为准。

默认翻译模型为 `glm-4-flash-250414`，参考[模型官方文档](https://docs.bigmodel.cn/cn/guide/models/free/glm-4-flash-250414)。朗读使用 [edge-tts](https://github.com/rany2/edge-tts)，不是离线语音合成。

## 快速开始

1. 点击仓库页面的 `Code > Download ZIP` 并解压，或者使用 Git 克隆。
2. 安装 [Python](https://www.python.org/downloads/windows/)，建议安装时启用 Python Launcher。
3. 双击 `setup.bat` 安装依赖。脚本仅创建本项目下的 `.venv`，不要求 Conda，也不会自动接受第三方服务条款。
4. 双击 `start.bat` 启动，首次运行时在设置窗口填写自己的 API Key。
5. 在浏览器、编辑器等应用中选中可复制的文字，快速按两次 `Ctrl`。

命令行方式，在 PowerShell 中运行：

```powershell
git clone https://github.com/xintiaoStark/double-ctrl-translator.git
cd double-ctrl-translator
.\setup.bat
.\start.bat
```

日常需要隐藏命令行窗口时，双击 `start_hidden.vbs`。如果系统禁用 Windows Script Host，使用 `start.bat` 即可。

也可以不使用批处理，手动创建环境和运行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe translator.py
```

如果没有 `py` 命令，可用已安装的 Python 3.11+ 对应的 `python` 命令替代第一行。

## 使用与配置

翻译完成后，点击悬浮窗外部区域关闭窗口。复制按钮（或 `Ctrl+C`）复制整段译文，朗读按钮朗读原文，按住空白处可以拖动。退出请右键点击系统托盘中的翻译工具图标，选择“退出”。

右键托盘图标选择“外观设置”可以调整悬浮窗样式：先点一个预设（清透 / 磨砂 / 深色），再按需拖动滑块、点色块选颜色，旁边的预览框会实时变化。点“保存”后写入 `translator_config.ini` 的 `[glass]` 部分，下次启动仍然有效；点“取消”或关闭窗口则恢复打开前的样式。源码模式下也可以双击 `tools\glass_tuner.bat`，在几种测试背景上对比效果。

API Key 保存在脚本或 EXE 同目录的 `translator_config.ini` 中。通常由首次设置窗口自动创建；需要手动配置时，可以复制 `translator_config.ini.example`，重命名为 `translator_config.ini`，再填写 `api_key`。设置窗口和托盘菜单都支持修改密钥。

开机自启可通过托盘菜单管理。源码模式也可运行 `add_startup.bat` 开启，或运行 `remove_startup.bat` 关闭。当前 EXE 沿用原有行为：首次成功配置密钥后自动启用开机自启，可在托盘菜单取消。启动项位于当前用户注册表的 `Software\Microsoft\Windows\CurrentVersion\Run`，值名为 `Translator`。不要同时启用多个副本；迁移旧版本时，先关闭旧启动项。

## 隐私与安全

- API Key 以**明文**保存在本地 INI 文件，不是加密凭据存储。不要共享该文件，不要把已配置的整个运行目录打包发送给别人。
- 翻译时，选中的文本会发送到智谱 BigModel；点击朗读时，原文会通过 edge-tts 发送到 Microsoft Edge 在线语音服务。不要使用本工具处理未经授权发送到第三方的敏感内容。
- 获取选中文字依赖模拟 `Ctrl+C`，会临时清空和使用剪贴板，并尝试恢复之前的文本。图片、富文本和其他非文本剪贴板内容不保证恢复。
- 玻璃效果需要看到悬浮窗背后的画面：悬浮窗显示期间，程序会截取它背后那一小块屏幕（约每 0.6 秒一次，拖动时更频繁），只在内存中用来绘制玻璃，不保存、不上传。截取的一瞬间悬浮窗会把自己排除在屏幕截图之外，录屏或共享屏幕时它可能偶尔闪一下。
- 程序通过全局键盘监听识别快捷键。源码中的监听回调仅用于 Ctrl 手势判断，不实现键盘日志功能。
- 仓库忽略真实配置、虚拟环境、构建目录和日志。提交前仍应自行检查，`.gitignore` 不会撤回已经提交过的秘密。
- 如果密钥意外公开，请立即在服务商控制台撤销并更换，不要只删除文件。

## 自行修改

主要逻辑在 `translator.py`，不需要额外前端框架。

| 位置 | 可修改内容 |
| --- | --- |
| `MODEL` | 默认使用的智谱模型 ID |
| `DOUBLE_CLICK_INTERVAL` / `MAX_HOLD` | 双击时间间隔和长按过滤阈值 |
| `translate()` | API 地址、提示词、输出长度和请求参数 |
| `detect_lang()` | 语言判断规则 |
| `speak_text()` | 朗读声音 |
| `PopupManager` / 颜色常量 | 悬浮窗布局、颜色与交互 |
| `GLASS_*` 常量 / `GLASS_PRESETS` | 玻璃的默认样式和预设；用户在“外观设置”里保存的值会覆盖默认值 |
| `render_glass_background()` / `render_glass_popup()` | 玻璃的绘制方式：模糊、饱和度、边缘折射、高光和文字 |

换用其他服务商时，还需要调整接口地址、鉴权和请求/响应格式；仅修改模型名称并不能保证兼容。

安装依赖后可在 Windows 上运行不访问真实翻译接口的单元测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

## 打包为 EXE

先运行 `setup.bat`，再双击 `build.bat`。也可以在 PowerShell 运行：

```powershell
.\build.bat
```

PyInstaller 参数直接写在 `build.bat` 中，输出单文件 `releases\translator.exe`。构建缓存和自动生成的 spec 文件位于 `build-public\`，不会覆盖旧的 `dist\`。接收 EXE 的人不需要安装 Python，但仍需要网络和自己的 API Key。

分发时携带 `LICENSE` 并保留第三方依赖所需的许可声明，**不要携带 `translator_config.ini`**。自行构建的 EXE 未进行代码签名，Windows 可能显示未知发布者提示；请核实来源，不要关闭安全防护。

## 已知限制与排错

- 没有 OCR，不能直接翻译图片、扫描件或不可复制的文字。
- 语言判断是简单规则：含常用中文汉字时按中文处理，否则按英文处理；不是通用多语言检测器。
- 玻璃效果跟随“设置 > 个性化 > 颜色 > 透明效果”开关；关闭时悬浮窗使用不透明的深色主题，可以选中部分译文复制。Windows 10 2004 之前的版本无法在悬浮窗显示后重新截取背后画面，玻璃不会跟着背景变化。
- 当前接口输出上限为 512 tokens，悬浮窗高度也有限，适合短句和段落，不适合整篇长文。
- API 报错时检查密钥、模型权限、额度和网络；朗读无声时检查网络和系统音量，当前版本不会显示详细的朗读错误。
- 在管理员权限运行的应用中，普通权限的工具可能无法模拟复制。应优先在普通权限应用中使用，不建议为了翻译长期以管理员身份运行。
- 同时运行多个副本、连续快速发起多个翻译请求可能导致监听或弹窗冲突，请一次只运行一个副本。
- 启动失败时先使用 `start.bat` 查看报错，`debug_setup.bat` 可检查 Python 和依赖环境。

## 参与贡献

欢迎 Fork 后自行修改，也欢迎通过 Issue 反馈问题或提交 Pull Request。请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，提交时不要包含真实密钥、个人选中文本或配置文件。

## 许可证

项目源码采用 [MIT License](LICENSE)，允许使用、修改和分发，需保留版权及许可声明。第三方依赖和在线服务分别遵循各自的许可及服务条款。
