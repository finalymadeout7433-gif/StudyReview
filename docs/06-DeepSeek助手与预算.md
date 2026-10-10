# 咪助手：动作、上下文、Key与预算

无Key/预算/启用确认时没有外部调用，基础学习功能仍可用，会话本机保存且明确提示未连接；手动单题草稿可预览确认。模块不会扫描环境或别的应用寻找Key。

## 实际适配器

Python标准库http.client/ssl，无额外SDK。固定HTTPS https://api.deepseek.com/chat/completions 和 deepseek-flash，严格allowlist，不接受代理/转发/重定向/远程图URL/自动重试/工具执行。

模型/视觉/价格会变。代码价格快照日期2026-10-03：输入未命中2元/百万token、输出8元，命中保守按未命中估计；不是当前价格保证或服务商账单。启用前本人核对 [官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) 与 [视觉说明](https://api-docs.deepseek.com/zh-cn/guides/vision/)。本轮官方页读取超时，未修改快照，也没做真实付费调用。

## 配置与私有Key

本人登录后在连接设置填写Key、累计预算并确认本地存储/预算/目的地/外发范围。数据库只存随机引用，Key由当前Windows用户DPAPI保护，密文在私有目录，不在源码/浏览器存储/状态响应。

GET /ai/config/只返安全状态和金额，不解密或回显Key、密文、路径、引用；POST需登录/CSRF。DPAPI不能用来跨机器/用户共享Key，Linux/macOS存储及桌面未验收。队友各配自己的Key，不把private放Git。

## 主动上下文

最多19条主动选定历史加当前消息、文字12,000字符；最多4张本次选定图片、8MiB。只解析授权当前图，不外发整库/整个聊天/图片目录。课程/对象也必须本人选定。

候选按本人可写活跃对象的名称/课程搜索及分页，不交给模型猜；同名或仅一条结果仍要明确点选。

## 草稿修改

任务点“让咪编辑/整理笔记”，错题点“用咪整理”；使用当前对象或按名选目标后输入要求，直接生成结构化预览，无需复制进表单。任务可改title/description/due_date/status；笔记只允许Task.description，没有独立笔记表。

模型text与至多一个白名单draft经服务再次验证范围、归属、归档、签名；不能换owner/课程/编号/令牌，不能执行SQL/代码/DOM或替人确认。无效结构不会写学习记录。

核对目标及字段修改前/确认后 → 点击确认 → 根事务保存 → 重新读取页面并恢复当前会话/预览/当前未发文本。先处理主页面未保存表单，避免刷新丢编辑。取消服务器持久保存且不写学习记录；另一窗口修改后旧草稿409冲突，需重新生成。确认UUID/全局忙状态防重和会话串入。

## 预算账本

Account以Decimal保存budget/spent/reserved、revision和启用确认；RequestLedger UUID唯一，含hash、价格快照、token上限、reservation/dispatched。先锁账户检查剩余额度、预留、持久发送标记，才联网；成功/确定失败结算，不确定则uncertain保留额度，禁止自动重试或增预算绕过核对。

本地估算不是服务商账单/预付款；网络不能被MySQL回滚，因此与本地事务分阶段。测试全部mock/合成数据，没有真实Key/付费请求。

代码：assistant/services、deepseek_provider、provider_security；ai_gateway/services、keystore、models；static/js/assistant.js。请求字段和API细节另见 ai_gateway/README.md 与接口导航。
