# 本地助手后端接口与安全边界

此模块使用现有 Django 会话认证、CSRF 和 MySQL 事务，不执行模型返回的代码或 SQL。未配置时 `get_provider()` 为 `DisconnectedProvider`，仅保存本地消息和系统记录。只有当前用户在连接设置中本人填写新 API 密钥、累计预算，并逐项确认本机加密保存、额度与 DeepSeek 官方目的地，才由 `ai_gateway` 启用 provider；工厂只读取 owner 配置元信息，实际响应阶段才解密人工配置的密钥。测试中的合成 provider 仅通过 Python 参数注入，HTTP、用户文字不能选择它。

聊天记录保存在本机数据库，不自动删除；关闭面板后仍可读取同一会话。历史保存和提供给 AI 的上下文是两个概念：上下文最多 20 条、12,000 字符和当前主动提交的 4 张图片、8 MB，仅该用户该会话。图片进入上下文时只有受控 UUID 和尺寸等元信息，无磁盘路径、网址或图片字节。默认未连接状态不会解析图片、识别试卷或声称回答问题。

## JSON 路由

所有路由都在 `/assistant/` 下，需登录。写请求必须正常带 CSRF token 与 `Content-Type: application/json`。未登录返回 401、跨用户/未知对象返回 404、非法字段返回 400、过期/变更/提交冲突返回 409。内容为纯 JSON 文字，前端应使用 `textContent`，不可当 HTML 注入。

| 路由 | 用途 |
| --- | --- |
| `GET status/` | AI 明确未连接、本地历史与上下文限制 |
| `GET context/` | 仅当前用户活跃课程/知识点，用于本地手动草稿表单；不自动送给 provider |
| `GET/POST sessions/` | 会话列表/创建；创建需 `submission_key` UUID，可选 `title` |
| `GET/PATCH sessions/<uuid>/` | 历史、草稿；PATCH 只可改 `title` |
| `POST sessions/<uuid>/messages/` | `{text, attachment_ids: [uuid], submission_key: uuid}`；返回用户消息及明确标注 `role=system,status=not_connected` 的系统提示 |
| `GET targets/question/<int>/` | 当前错题字段快照和带用户/对象/版本的 `expected_version` 签名 |
| `GET targets/task/<int>/` | 当前任务快照及签名版本 |
| `GET/POST sessions/<uuid>/drafts/` | 草稿列表/创建；只预览，不改学习记录 |
| `GET drafts/<uuid>/` | 原值、提议值、有效期和确认 token |
| `POST drafts/<uuid>/confirm/` | `{confirmation_token, submission_key: uuid}`；显式原子提交，重复只返回首次结果 |

会话、历史与草稿每批最多 100 条，通过 `before=<older_cursor>` 读取更早记录，不删除旧记录；会话/草稿列表返回 `has_more`，消息历史返回 `has_older`。所有附件 URL 都指向带会话认证的本地图片路由。

## 草稿格式

```json
{
  "operation": "create_question",
  "submission_key": "00000000-0000-4000-8000-000000000001",
  "payload": {
    "course_id": 1,
    "title": "合成例题",
    "content": "合成题干",
    "original_answer": "合成原作答",
    "correct_answer": "合成参考答案",
    "error_reason": "合成错因",
    "next_review_date": "2026-10-04",
    "knowledge_point_ids": [],
    "attachment_ids": []
  }
}
```

该例仅说明结构，非真实资料。`create_question` 需要显式课程和上述六个文本/日期字段。`update_question` 允许这些文本、复习日期、知识点及题干附件；`update_task` 仅允许标题、说明和截止日期。修改操作还需顶层 `target_id` 和从 target 接口取得的 `expected_version`。不支持跨课程移动、归档、删除、状态批量更改、任意模型字段、SQL/代码或 URL 执行。

课程→对象→草稿的锁顺序与原有业务服务一致。确认时再次验证 owner、课程/题目归档、白名单字段、日期、同课程知识点、图片 owner、签名和当前字段快照；任务完成状态和错题其他角色图片的改变也使旧预览失效。课程/知识点名称变动导致提议预览不再准确时同样拒绝确认。草稿有效期 24 小时，过期保留原内容但不能写入。

生成预览不会创建半道错题；实际题目创建、知识点关联、图片关联及草稿状态在同一事务提交。任一失败全部回滚。新增错题的防重键由草稿 UUID 派生，数据库唯一约束最终防重。原有复习记录与不可修改的历史快照均不被更改。

## 检查与限制

`assistant/tests/test_assistant.py` 覆盖未连接无 provider 调用、权限、CSRF、图片 owner、会话恢复、防重、纯文字、上下文预算、provider 不可信输出、白名单、预览、确认、附件原子写入、回滚、过时/过期/归档和字段保留。必须在 root 明确创建的隔离 MySQL 测试库运行，使用 `--keepdb`；不得用真实用户数据库运行。

DeepSeek 适配与本地预算账本已在 `ai_gateway` 接入：固定官方目的地、当前主动附图再次 owner 验证、持久预留、发送标记和失败不确定额度。默认仅当前消息；`context_message_ids`、`selected_target` 和 `selected_course_id` 都须用户主动选择。模型不能选择或更换目标、课程、签名或提交 UUID。真实识别质量、在线连通与服务商实际账单尚未验证；当前验收均为本地或模拟请求。系统不提供永久模型记忆、自动删除或批量改写。请一并阅读 `ai_gateway/README.md`。
