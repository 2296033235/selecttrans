# SelectTrans

选中文字，按下快捷键，在鼠标旁直接读译文。

一个 Windows 桌面划词翻译工具：不占屏幕、不需要切换窗口，翻译结果以液态玻璃悬浮窗贴在光标附近。

## 特性

- **划词即译**：选中任意可复制的文字，默认快速按两次 `Ctrl` 触发，中英互译。普通 `Ctrl+C`、`Ctrl+V` 不会误触发。
- **快捷键可自定义**：托盘菜单里改成双击 `Ctrl` / `Alt` / `Shift` / `Win`，或任意组合键（`Ctrl+Shift+T`），也支持单键（`F2`）。
- **液态玻璃悬浮窗**：截取窗口背后的画面做模糊、提饱和度和边缘折射，文字颜色按背景明暗自动切换；系统关闭透明效果时自动回退为不透明深色主题。
- **字号与配色可调**：原文、译文分别设字号，文字颜色可选自动 / 深色 / 浅色或直接指定色值，玻璃的模糊、折射、圆角、高光也都能调，改完实时预览。
- **朗读**：一键用 `edge-tts` 朗读原文。
- **任意 OpenAI 兼容接口**：默认智谱 GLM，可换成 DeepSeek、OpenAI 或自建网关。
- **托盘常驻**：没有主窗口，不占任务栏。

## 环境要求

- Windows 10 / 11。程序使用 Windows 注册表、剪贴板和音频接口，不支持 macOS / Linux。
- Python 3.11 或更新版本，需包含 Tkinter。
- 能访问你配置的翻译接口；朗读需要访问 Microsoft Edge 在线语音服务。
- 一个可用的 API Key（默认走[智谱 BigModel](https://bigmodel.cn/)，模型权限与计费以平台规则为准）。

默认模型 `glm-4-flash-250414`，接口 `https://open.bigmodel.cn/api/paas/v4`。朗读使用 [edge-tts](https://github.com/rany2/edge-tts)，不是离线合成。

## 快速开始

1. 下载仓库或 `git clone` 到本地。
2. 安装 [Python](https://www.python.org/downloads/windows/) 3.11+。
3. 双击 `setup.bat`，脚本会在项目内创建 `.venv` 并安装依赖。
4. 双击 `start_hidden.vbs`（无控制台窗口）或 `start.bat`（保留控制台便于排错）。
5. 首次启动会弹出设置窗口，填入 API Key 即可。

命令行方式：

```powershell
git clone https://github.com/2296033235/double-ctrl-translator.git
cd double-ctrl-translator
.\setup.bat
.\start.bat
```

不使用批处理时也可以手动创建环境：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe selecttrans.py
```

## 使用

选中文字后按快捷键，悬浮窗出现在光标附近。点击窗口外部关闭；复制按钮或 `Ctrl+C` 复制整段译文；喇叭按钮朗读原文；按住空白处可以拖动。

托盘图标右键菜单：

| 菜单项 | 作用 |
| --- | --- |
| 接口设置（API Key / 模型） | 填写或修改密钥、接口地址、模型 |
| 外观设置（字体 / 颜色） | 调字号、文字颜色和玻璃样式，带实时预览 |
| 快捷键设置 | 录制新的组合键，或选择双击某个修饰键 |
| 开机自启 | 开关当前用户的开机启动项 |
| 退出 | 结束程序 |

### 快捷键

默认是双击 `Ctrl`。在“快捷键设置”里点“按下新快捷键”，然后直接按组合键即可（按 `Esc` 取消录制）；也可以用预设按钮改成双击 `Alt` / `Shift` / `Win`。

三种模式互斥，同时只有一种生效：

- `double-ctrl`：双击修饰键，要求短按（不超过 0.35 秒）且期间没按其他键，两次间隔 0.4 秒内。
- `ctrl+shift+t`：组合键，最后一个键按下时触发一次，按住不放不会重复。
- `f2`：单个按键。

把 `Ctrl+C` 设为触发键也能用，但每次复制都会弹出翻译窗——程序本身也靠模拟 `Ctrl+C` 取走选中文字，两者会叠加。`Ctrl+V` 更不建议：粘贴时触发翻译会动到剪贴板。

### 接口

默认智谱 GLM。“更多设置”里可填任意 OpenAI 兼容接口：地址写到版本号即可（程序自动补 `/chat/completions`），也可填完整地址；点“测试连接”会用 `Hello` 试译一次。接口地址和模型保持默认时，配置文件里留空，以后默认值更新会自动生效。

## 配置

配置保存在程序同目录的 `selecttrans_config.ini`，首次配置后自动创建：

```ini
[settings]
api_key =
base_url =
model =
hotkey = double-ctrl

[glass]
# 外观设置保存的样式项
```

`base_url` 和 `model` 留空表示使用内置默认值。需要手动创建时，复制 `selecttrans_config.ini.example` 改名后填写。

## 隐私与安全

- **API Key 以明文保存在本地 INI 文件**，不是加密凭据存储。不要共享该文件，也不要把已配置的运行目录打包发给别人。
- 翻译时选中的文本会发送到你配置的接口；点朗读时原文会经 `edge-tts` 发送到 Microsoft Edge 在线语音服务。不要用它处理未经授权外发的敏感内容。
- 取词依赖模拟 `Ctrl+C`，会临时清空并尝试恢复剪贴板。图片、富文本等非文本内容不保证恢复。
- 玻璃效果需要截取悬浮窗背后的画面：显示期间约每 0.6 秒截取一次（拖动时更频繁），只在内存中绘制，不保存、不上传。录屏时窗口可能偶尔闪一下。
- 程序通过全局键盘监听识别快捷键，回调只做手势判断，不记录按键内容。
- 仓库用 `.gitignore` 排除了真实配置、虚拟环境和构建产物，但已提交过的内容不会被自动撤回，提交前请自查。
- 密钥若意外公开，请在服务商控制台撤销并更换，而不是只删文件。

## 开发

主要逻辑集中在 `selecttrans.py`，没有前端框架，界面用 Tkinter 和 Pillow 绘制。

| 位置 | 可修改内容 |
| --- | --- |
| `APP_NAME` | 托盘名称、窗口标题、启动项名称 |
| `MODEL` / `DEFAULT_BASE_URL` | 默认模型与接口地址 |
| `DEFAULT_HOTKEY` / `HotkeyMatcher` | 默认快捷键与触发判定 |
| `key_name()` / `parse_hotkey()` | 按键名归一规则与快捷键文本语法 |
| `DOUBLE_CLICK_INTERVAL` / `MAX_HOLD` | 双击间隔与长按阈值 |
| `request_translation()` | 提示词、输出长度与请求参数 |
| `detect_lang()` | 语种判断规则 |
| `speak_text()` | 朗读音色 |
| `PopupManager` / 颜色常量 | 悬浮窗布局与交互 |
| `GLASS_*` 常量 / `GLASS_PRESETS` | 玻璃默认样式与预设，`[glass]` 配置会覆盖 |
| `GLASS_FONT_ORIG` / `GLASS_FONT_TEXT` | 原文与译文字号（100% 缩放下的像素） |
| `render_glass_background()` / `render_glass_popup()` | 玻璃绘制：模糊、折射、高光与文字 |

接口部分只支持 OpenAI 兼容的 Chat Completions 格式（`Authorization: Bearer`，返回 `choices[0].message.content`），其他格式需要改 `request_translation()`。

运行单元测试（不访问真实接口）：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
```

玻璃样式也可以在源码模式下双击 `tools\glass_tuner.bat` 调整，它用合成背景打开同一个外观窗口，方便对比不同背景下的效果。

## 打包

先运行 `setup.bat`，再双击 `build.bat`：

```powershell
.\build.bat
```

PyInstaller 参数写在 `build.bat` 里，输出单文件 `releases\selecttrans.exe`；构建缓存和 spec 放在 `build-public\`。接收 EXE 的人不需要装 Python，但仍需网络和自己的 API Key。

分发时带上 `LICENSE` 和 `assets/fonts/OFL.txt`，并保留第三方依赖的许可声明，**不要带 `selecttrans_config.ini`**。自行构建的 EXE 没有代码签名，Windows 可能提示未知发布者。

## 已知限制

- 没有 OCR，图片、扫描件、不可复制的文字无法翻译。
- 语种判断是简单规则：含常用中文汉字按中文处理，否则按英文处理。
- 接口输出上限 512 tokens，悬浮窗高度也有限，适合短句和段落。
- 系统关闭“透明效果”时悬浮窗使用不透明深色主题，可以选中部分译文复制；Windows 10 2004 之前无法在窗口显示后重新截屏，玻璃不会跟随背景刷新。
- 朗读失败不会弹出详细错误，检查网络和系统音量。
- 在管理员权限运行的应用中，普通权限的实例可能无法模拟复制。
- 同时运行多个副本会导致键盘监听和弹窗冲突，一次只运行一个。
- 启动异常时改用 `start.bat` 查看报错，`debug_setup.bat` 可检查 Python 与依赖环境。

## 许可

源码采用 [MIT License](LICENSE)。第三方依赖和在线服务遵循各自的许可与服务条款。

设置窗口使用的字体是[站酷快乐体（ZCOOL KuaiLe）](https://github.com/googlefonts/zcool-kuaile)，位于 `assets/fonts/`，采用 [SIL Open Font License 1.1](assets/fonts/OFL.txt)，打包时会一并放进 EXE。
