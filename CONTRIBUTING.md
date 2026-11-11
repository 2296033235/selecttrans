# Contributing

欢迎提交问题和改进。

## 开发

1. Fork 仓库并克隆自己的副本。
2. 在 Windows 上安装 Python 3.11+，运行 `setup.bat`。
3. 创建分支并修改，尽量保持每次 Pull Request 只解决一类问题。
4. 运行下面的检查，并在目标应用中手动验证实际划词操作。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
.\start.bat
```

单元测试使用模拟 API 响应和临时配置，不应使用真实密钥，不应访问真实翻译服务或修改实际开机启动项。当前测试不覆盖全局快捷键与其他应用的真实交互、真实翻译接口及在线语音播放。

## 提交问题

请说明 Windows / Python 版本、源码运行还是 EXE、复现步骤、预期结果和实际结果。提供报错或截图前，请去掉密钥、用户名、个人路径和选中的敏感内容。

## 提交改动

Pull Request 中请说明改了什么、为什么修改、如何验证。新增依赖时同步更新依赖文件和安装文档，修改打包行为时验证 `build.bat`。

不要提交 `selecttrans_config.ini`、`.venv`、构建产物或私人笔记。提交前检查 `git diff --cached`；不要使用 `git add -f` 强制添加真实配置。

贡献到本仓库的代码应可按本项目的 MIT 许可证发布；引用第三方代码或资源时请标明来源，并遵守其原有许可证。
