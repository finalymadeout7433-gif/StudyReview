# 拾习 / StudyReview

数据库课程项目：把课程、任务、错题、复习历史和统计连起来，提供 Windows 独立窗口及本地学习助手。

本次更新：v2.1.0，2026-11-02。新增简洁界面、十个统计模块、七门课程内容模板、聊天式学习助手与截图粘贴，修复普通图片答疑返回格式及开发预览异常退出恢复。此版本的运行包需由仓库维护者上传至 Release；下方 latest 链接可能仍指向旧版。

**下载软件：[GitHub Releases](https://github.com/finalymadeout7433-gif/StudyReview/releases/latest)。Windows ZIP 内含 Python 应用运行时，仍需本机 MySQL 8.4、WebView2、兼容 .NET Framework/VC++；不是无需环境的解压即用。** 按 [Windows 首次启动](docs/01-Windows首次启动.md) 从下载完成配置。

## 当前功能

- 注册登录、用户隔离；课程/知识点管理，归档只读。
- 任务、截止日期、完成状态、任务说明/笔记，筛选与统计。
- 图文错题，区分题干、原答、参考答案、错因图片用途；保存独立历史快照。
- 先作答后看答案、自评和复习历史；新复习使用 FSRS 6.3.2，可人工调整日期。
- 咪助手持久会话，人工配置 DeepSeek 密钥、预算和外发范围后联网；自然语言建议形成草稿，明确选对象、查看字段差异、确认后保存并刷新。
- **无 DeepSeek Key 时，课程、任务、错题、图片、复习、统计和手动草稿仍可用。**

没有教师端、同步/推送、公网部署、邮箱找回、模型任意 SQL/工具执行或可靠 OCR 保证。笔记是 Task.description，不是独立笔记应用。桌面包仅 Windows x64；其他系统没有完整桌面验收。

普通体验：下载 Windows ZIP → 准备系统依赖与本人私有配置 → 仅新空库首次初始化（可选合成数据）→ 双击启动。

协作开发：克隆 → Python 3.13 独立环境 → 锁定依赖 → 全新具名开发/测试库 → 迁移、测试、运行，见 [开发与协作](docs/02-开发环境与协作.md)。

演示账号只在选择合成数据且本次确实新建了库后产生：demo_student / StudyDemo2026!；空账户 demo_empty / StudyEmpty2026!。这些是公开演示口令，不是数据库密码或 API Key。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [01 Windows 首次启动](docs/01-Windows首次启动.md) | 官方下载、系统依赖、账户、配置、初始化、成功判据 |
| [02 开发与协作](docs/02-开发环境与协作.md) | 安装、隔离库、运行、构建、分支 PR |
| [03 架构与数据流](docs/03-架构与数据流.md) | 模板、桌面、HTTP、ORM、事务和模块职责 |
| [04 数据库课程说明](docs/04-数据库课程说明.md) | ER、表关系、约束、索引、触发器 |
| [模型数据字典](docs/数据库数据字典.md) | 直接从当前模型生成的字段、外键、约束和索引 |
| [05 图片与历史](docs/05-图片与历史快照.md) | 私有文件、规范化、权限与快照 |
| [06 DeepSeek 助手](docs/06-DeepSeek助手与预算.md) | 主动上下文、草稿确认、DPAPI、预算和外发 |
| [07 复习与时区](docs/07-复习算法与时区.md) | FSRS、旧历史、上海日期与人工改期 |
| [08 测试与 CI](docs/08-测试与CI.md) | 隔离测试、边界、CI及发行门禁 |
| [09 备份与故障](docs/09-备份恢复与故障.md) | 备份组合、恢复、版本回退及排错 |
| [10 工具与版权](docs/10-工具依赖与版权.md) | 每个工具/依赖的作用、版本与许可证 |
| [11 接口导航](docs/11-接口与代码导航.md) | 页面/API 和主要实现定位 |
| [12 发行验收](docs/12-发行验收记录.md) | 本轮实际结果、哈希及未覆盖项目 |
| [13 本机开发与协作](docs/13-local-development.md) | 源码预览、停止、检查、测试与分支协作 |
| [14 界面与统计图表](docs/14-interface-and-charts.md) | 本分支的布局优化、六类真实数据图表及修改位置 |
| [15 课程示例与记忆分析](docs/15-learning-examples-and-memory.md) | 十个统计模块、示例来源、遗忘示意、FSRS预测及实例关联图 |

## 技术栈与代码

Python 3.13.x（本次构建为3.13.5）、Django 5.2.17、mysqlclient 2.3.0、MySQL 8.4；Django 模板与本地 CSS/JS；Pillow 12.3.0、FSRS 6.3.2；Waitress 3.0.2、WhiteNoise 6.12.0、pywebview 6.2.1、pythonnet 3.2.0、WinForms/WebView2。没有 React 双栈或 GPU/训练依赖。

learning、attachments、assistant、scheduling、ai_gateway 分别负责基础学习、图片、草稿/会话、调度、AI预算；desktop 是窗口和本机服务；config 是环境与迁移授权；templates/static 是离线界面。

源码包含全套迁移、无用户行的结构参考和合成数据命令。凭据、真实 SQL/图片/聊天、DPAPI、窗口缓存、日志不入 Git；大型二进制在 Release。使用功能分支和 PR，由所有者核实成员后赋写权限。

未新增整体开源许可；参见 [版权](COPYRIGHT.md) 和 [第三方许可](THIRD_PARTY_NOTICES.md)。公开仓库不自动代表对所有内容的任意再许可。
