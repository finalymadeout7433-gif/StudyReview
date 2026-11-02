# 本机源码预览与小组协作

本工具为 Windows 源码开发提供统一的启动、停止、检查和测试入口。运行包仍按首次启动文档使用，两者的数据目录和数据库应分开。

## 准备

1. 按 `02-开发环境与协作.md` 安装锁定依赖、准备独立开发/测试库，并完成迁移和合成数据初始化。
2. 把私人数据和数据库配置放在 Git checkout 之外。
3. 确保 MySQL 实例正在运行；本工具不安装、启动或停止系统 MySQL 服务。

`scripts/local-development.ps1` 必须显式接收 `-DataDir` 和 `-CredentialsFile`，只接受已经准备好的 `study_review_v2_dev_…`、`test_study_review_v2_…` 开发配置。

## 操作

以下变量由每位组员填写为自己的本机绝对路径，不在仓库保存真实配置：

```powershell
$dataDirectory = '本人 checkout 之外的开发数据目录'
$credentialFile = '本人私有数据库 JSON 的完整路径'
$pythonExecutable = '本人虚拟环境 Scripts\python.exe 的完整路径'

.\scripts\local-development.ps1 -Action start -DataDir $dataDirectory -CredentialsFile $credentialFile -PythonPath $pythonExecutable -OpenBrowser
.\scripts\local-development.ps1 -Action stop -DataDir $dataDirectory -CredentialsFile $credentialFile -PythonPath $pythonExecutable
.\scripts\local-development.ps1 -Action check -DataDir $dataDirectory -CredentialsFile $credentialFile -PythonPath $pythonExecutable
.\scripts\local-development.ps1 -Action test -DataDir $dataDirectory -CredentialsFile $credentialFile -PythonPath $pythonExecutable
```

默认预览地址为 `http://127.0.0.1:8001/`，可用 `-Port` 选择空闲端口。停止时也应使用对应的端口和数据目录。预览使用 Django/Waitress 的同一业务代码，静态资源在启动前重新收集。它不自动监测修改：编辑代码或样式后正常停止，再启动预览。

启动器只更改当前进程的环境变量；不会改全局 PATH，不打印密码，也不会初始化或删除数据库。服务器日志位于开发数据目录的 `private` 子目录中。

`check` 包含依赖一致性、Django 系统检查、迁移遗漏检查、发布边界扫描和 Git 空白检查。`test` 在独立测试库运行集成测试，再运行桌面单元测试；结果以当次输出为准。

## 每项修改的协作顺序

1. 开始前确认所在分支和工作区状态；从远端获取更新，检查队友是否修改了相同文件或迁移。
2. 一次围绕一个明确需求修改，保留用户隔离、历史保护和确认保存等约束。
3. 运行适用检查和测试，再实际预览效果。
4. 用 `git diff` 核对只包含源码、迁移、合成数据方案和说明。
5. 使用本人的作者身份提交，推送自己的分支，并通过 PR 与队友合并。无需覆盖或强制推送 `main`。

GitHub 登录与仓库写权限需要本人账号授权及仓库所有者确认；远端配置完成不等于已有推送权限。没有写权限时可以通过个人 fork 提交 PR。

数据库结构变更通过模型和迁移同步；本机数据库文件、账号密码、真实学习资料、窗口缓存和虚拟环境不进入 Git。发布新运行包与上传源码是两个步骤：修改源码后应重新构建并验收软件包。
