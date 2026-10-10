# 本地 AI 配置、主动上下文与持久预算网关

默认没有密钥、没有预算、没有外部调用。只允许用户本人在本地表单填写 DeepSeek 密钥、人民币预算并逐项确认后启用；本模块不会搜索环境变量、未知配置、系统凭据或现有模型服务 key。实现仅用既有 Django 和 Python/Windows 标准库，无新增依赖。

## 配置 API

全部路由在 `/ai/` 下，需现有会话登录，写请求受 CSRF 保护。`GET config/` 只返回安全状态和金额，不解密密钥，不返回密钥、密文、文件路径或 key_reference。

`POST config/` 必须完整提供：

```json
{
  "api_key": "用户本人填写，不预填",
  "budget_cny": "5.00",
  "confirm_local_storage": true,
  "confirm_budget": true,
  "confirm_destination": true,
  "enable": true
}
```

示例不是有效密钥。三项同意及 enable 都必须严格为布尔 true，预算必须明确填写、至少 0.01 元、最多 1000 元、最多两位小数，并且不能低于已计入的费用与未释放预留。金额内部保留六位小数；费用展示应标明保守估算，避免微小费用显示为零。

`DELETE config/` 或 `POST config/ {"action":"disable"}` 停用发送，不删除密钥引用、历史、费用或账本。重新配置需要本人重新填写 key，不读取旧 key 预填表单。配置及异常响应不回显 key，采用 Django sensitive decorators，重复 JSON 字段或非有限数值拒绝。

安全状态字段：`configured, connected, state, label, enabled, key_stored, budget_cny, spent_cny, reserved_cny, remaining_cny, uncertain_requests, provider, model, destination, cost_basis, online_connection_verified`。其中 `connected=true` 仅表示本地配置和额度满足入口条件；`online_connection_verified=false` 明确没有自动在线验证密钥或模型。默认 state 为 not_connected。停用为 disabled；无剩余额度为 budget_exhausted。

## 密钥存储

密钥使用已检查的 Windows 当前用户 DPAPI 加密，仅落随机 UUID 目录下的密文。位置为 `PRIVATE_DATA_ROOT/ai-credentials/<uuid>/key.dpapi`，没有该独立根时为 `BASE_DIR/private/ai/<uuid>/key.dpapi`。用户不能控制存储目录名或路径；拒绝符号链接/目录联接，限定根内路径和普通文件，使用独占创建、fsync 后发布，失败清理只触及本次生成的已知文件，不递归删除未知内容。

配置和密文写入同受控动作完成；数据库保存失败会回滚配置并清理本次密文。旧配置重新填写时创建新 UUID 密文，不读旧密钥；旧密文不自动删除。所有密钥目录必须从代码、ZIP、完整备份、导出、日志和前端存储中排除。DPAPI 绑定当前 Windows 用户，迁移到另一台机器或另一用户时必须重新手动配置，没有明文或非 Windows 回退。

factory/status 仅查询当前网站用户的 Account 元信息。只有 `GatewayProvider.respond` 在一次主动消息请求中读取此用户明确配置的当前 key_reference 并解密。Python 字符串无法保证内存擦除；不将其序列化、日志记录或浏览器回显。

## 主动上下文与受控草稿

`POST /assistant/sessions/<uuid>/messages/` 保留原有字段，新增可选字段：

```json
{
  "text": "请修改我明确选定题目的标题",
  "attachment_ids": [],
  "submission_key": "00000000-0000-4000-8000-000000000001",
  "context_message_ids": [],
  "selected_target": {
    "kind": "question",
    "id": 1,
    "expected_version": "从当前用户 target 接口取得的签名"
  },
  "selected_course_id": 1
}
```

默认只发送本次主动提交的文字/附图，历史保存在本机不等于全部发送或永久模型记忆。用户可显式选择同一会话最多 19 条 user/assistant 历史文字。图片仅发送本条显式 `attachment_ids`；历史消息或选定对象中的图片 UUID 不是自动发送图片字节的授权。图片再次检查 owner、私有路径、文件长度及 SHA256，并且只发送经过规范化的 PNG。

选定目标先核对 owner、类型、ID、签名版本及归档状态，锁顺序 course→object→session。选定课程必须为本人活跃课程；若同时选对象，课程需一致。其他对象不扫描。`MessageContext` 在本地保留明确选定的范围、快照和版本，关闭后历史仍能解释本条消息的范围。

给 provider 的单对象/单课程快照是明确标识的 UNTRUSTED DATA，放 user 数据而非系统指令，计入 12,000 字符预算。目标签名、确认 token 与 key 不给模型。超过边界拒绝发送，不静默替换系统规则。

模型 update 草稿必须匹配选定类型/对象；模型不得更换目标、课程或提供版本签名。真实 target_id、expected_version 和草稿防重 UUID 由服务端注入。未选目标时不生成修改草稿；create_question 必须先主动选定课程。仍须原有草稿预览及独立确认，所有权、版本、归档、知识点及附件会再次校验。模型不执行 SQL/代码/URL，也不能删除或批量覆盖。

消息响应及恢复历史新增 `selection`：`{target:{kind,id,title,course_id}|null, course:{id,name}|null, history_message_ids:[]}`，不含签名。未配置及停用时保存 user 消息与 role=system 的明确提示；异常/费用未知同样为 system，不假装答案。

## 预算事务

`Account` 保存 owner 唯一配置、预算、累计峰值费用估算、未释放预留、revision、key_reference、enabled 和 consent_at。

`RequestLedger` 仅保存 request UUID、owner/account、request_hash、状态/发送标记、价格快照、token 上限、原始预留、当前 held、费用估算、usage 及固定 failure_code；不保存 key、题目/图片或回答。消息提交 UUID 直接作为唯一请求 UUID。

流程：

1. 在任何网络调用前规范化主动数据和价格上限，按全部输入 cache miss 与输出上限预估峰值金额。
2. `SELECT FOR UPDATE` 锁 Account，检查预算与当前本人配置，提交唯一 RequestLedger 和 Account 预留额度。
3. 再次在 Account→ledger 锁下检查启用/密钥引用并提交 dispatched 标记。
4. 释放数据库事务后，直接 TLS 到唯一 `https://api.deepseek.com/chat/completions`。不跟随重定向、环境代理或备用服务；不重试。
5. 成功 usage 按价格快照保守估算并原子结算一次。明确拒绝释放未消费额度；超时、断线、未知响应、usage 超上限或结算失败保留预留/未知额度。

任何已登记 UUID 都不能取得可再次发送的 reservation，包括发送前进程中断。发送标记后崩溃或结算失败的账本可能保留 `reserved + dispatched=true`，也会保持额度并拒绝重发；需人工核对真实服务商账单后另做明确维护，不自动清零。停用不会释放正在等待核对的额度。

本地预算保护依赖明确的价格快照和保守上限，并非服务商账单或远端硬限额。超界用量会保持/增加未知占用，停止进一步调用，不宣称实际收费保证。

## 验证与审核入口

`ai_gateway/tests/test_gateway.py` 加上既有 assistant 和 provider 单元测试，共 104 项在实际 MySQL 专属聊天测试库通过。模拟 transport 验证网络发送前 ledger 标记已提交、发送时无数据库原子事务；Windows DPAPI 仅用合成密钥与测试临时目录。没有真实 key、外部 API 调用或主业务库写入。

测试包括本人勾选、预算缺失/金额边界、CSRF、owner、DPAPI 密文不含明文、状态/factory 不解密、文件及保存后数据库失败清理、并发预算及相同 UUID 防重、成功结算重放、超时/超界 usage/结算故障保留额度、含合成 key 的异常不泄露、主动历史/单目标签名与课程、防止模型更换作用范围。

迁移 `ai_gateway.0001_initial` 依赖 assistant.0001_initial 和用户模型；assistant 迁移不反向依赖 ai_gateway，无环。独立审核应关注：配置 JSON 与前端 key 不存 localStorage/日志；credential 目录确实排除打包；预算 callbacks 的 commit 顺序；默认无配置 failclosed；目标白名单及实际 UI 预览确认。尚未验证真实 DeepSeek 连通、计费或真实图片识别效果。
