# Windows 新电脑：从下载到首次登录

适用于本人控制的新电脑和不存在 study_review_dev 的 MySQL 实例。已有同名库（即使空库）一律拒绝初始化；先确认旧安装，不覆盖。

## 下载与校验

从 https://github.com/finalymadeout7433-gif/StudyReview/releases/latest 下载 StudyReview-Windows-x64-v2.0.0-rc7-collab.2.zip 和 SHA256SUMS.txt。完整解压，例如 C:\Apps\StudyReview，保留 Windows程序及所有 _internal 文件，不能只复制 EXE。

    Get-FileHash -Algorithm SHA256 '下载 ZIP 的完整路径'

与清单比较。软件无代码签名；若提示未知发布者，先核对来源与哈希，再由本人决定，不关闭系统安全软件。

## 必需系统组件

| 组件 | 作用与官方入口 |
| --- | --- |
| Windows 10/11 x64 | 当前桌面目标 |
| MySQL Community 8.4 LTS | [下载](https://dev.mysql.com/downloads/mysql/) / [Windows 安装](https://dev.mysql.com/doc/refman/8.4/en/windows-installation.html)；本机验证 8.4.11 |
| WebView2 Evergreen Runtime | [微软下载](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) / [分发说明](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution) |
| 兼容 .NET Framework，建议 4.8 | [微软入口](https://dotnet.microsoft.com/en-us/download/dotnet-framework)；WinForms/pythonnet |
| Visual C++ x64 Redistributable | [微软入口](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)；MySQL及部分二进制依赖 |
| DBeaver（可选） | [官方入口](https://dbeaver.io/download/)；查看数据库，不是网站后台 |

按 MySQL MSI/Configurator 设置本机服务、管理员口令与端口，通常 127.0.0.1:3306。不需要开放公网端口，不卸载/覆盖已有数据目录。软件不会安装或启停共享 MySQL 服务。

**软件 ZIP 已包含 Python 和应用依赖，运行不需要另装 Python/Git/pip。** 开发源码才需要这些工具。

## 本人准备应用账户

网站账号与数据库账号不同。初始化用已有管理员做 DDL；日常使用独立应用账号。由本人在本机管理工具执行以下模板，口令必须自己替换，已有账户不重建/重置：

    CREATE USER 'study_app'@'localhost' IDENTIFIED BY 'REPLACE_WITH_YOUR_OWN_LOCAL_PASSWORD';

初始化仅向这个已有 localhost 用户授 SELECT、INSERT、UPDATE、DELETE，不创建账号/长期口令，不授 ALL。管理员和应用账户必须不同。

## 私有配置

建议数据目录 %LOCALAPPDATA%\StudyReview\data，在程序目录之外。本人新建 private 子目录，把 database-config.example.json 复制为 private\database-credentials.json，填写：

- host/port：本机实际连接；database 固定 study_review_dev。
- application_user/application_password：已有独立应用账户。
- administrator_user/administrator_password：本人已有的初始化/维护管理员。

JSON 必须合法；不要把配置放程序目录或 Git checkout，不发给队友。每人使用自己的数据库身份。此文件没有 AI Key；Key 由本人在应用“连接设置”填写。

## 首次新空库初始化

双击“首次初始化.cmd”，选择数据与配置的完整路径。输入 NEW-EMPTY 才确认建新空库及四项 DML 授权，可选合成演示数据。只有本次操作确实新建了库才 seed；正常启动不会 seed。

流程：本机/独立账户/库不存在检查 → CREATE DATABASE → 最小 GRANT → Django 全部迁移 → 可选合成数据 → 保存配置路径引用。DDL 不能整体事务回滚；失败保留现场，不自动删库或覆盖。

CLI 参数为 --initialize-new-empty-database、--confirm-existing-account-dml-grant，明确 --data-dir 与 --credentials-file；可选 --seed-synthetic-demo。完整脚本见 scripts/initialize-new.ps1。无秘密结果可写入全新 --initialization-output 文件。

## 打开与登录

双击“启动拾习.cmd”。未就绪时向导出现：选程序外数据目录 → 选本人配置 → “只读检查” → 勾选保存路径 → “确认保存路径” → “打开拾习”。向导只保存引用，不展示/复制密码，也不建库；替换已有引用需另行确认并保存旧引用。

选择了合成数据时：demo_student / StudyDemo2026!；空账户 demo_empty / StudyEmpty2026!。未 seed 时点击注册建立自己的网站账号。

成功判据：中文登录和导航正常；新任务关闭重开仍保存；合成安装有 4 门课程、7 知识点、7任务、8错题、5条标记为合成的历史；无 DeepSeek Key 也能完成基础学习。停止入口仅退出本数据目录的应用，不停 MySQL。

软件只监听随机 127.0.0.1 端口，不是公网网站/手机共享服务。升级先保存表单、正常关闭旧窗，保留私人数据和旧程序，在另一目录解压新版，不初始化当前库。

2026-10-10已在同一台 Windows 的全新隔离 MySQL 实例与新配置完成基础验收，准确范围以 [发行验收记录](12-发行验收记录.md) 为准；第二台干净电脑的完整系统组件安装、Linux/macOS 桌面尚未验证。
