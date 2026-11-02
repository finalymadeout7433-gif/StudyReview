# 课程示例与记忆分析

当前统计页由第一轮六类图表扩展为十个图表模块，另有模型辅助提示清单。继续使用本地Django模板、SVG与表格，不引入在线图表依赖。

## 可重复使用的课程示例

`learning/example_curriculum.py` 包含7门课的原创示例：每门4个知识点、4项任务、3道错题。题目含原答、参考答案、错因及知识点关联；不是学校教学大纲或真题。

导入命令只允许已配置的独立开发/测试库，必须显式指定已存在的账号：

```powershell
python manage.py seed_learning_examples --username YOUR_ACCOUNT --settings=config.v2_development_settings
```

默认只创建内容，不生成学习表现。只有显式增加 `--with-example-history`，才通过现有复习事务和FSRS调度流程生成63条示例历史及其调度事件。`--dry-run` 将整个演练回滚。

没有账号创建、密码设置、删除、覆盖或已有历史重放。稳定的creation_key防止重复创建任务和错题；同名知识点复用，非空课程说明保留。已有题目被用户编辑后不会因重跑恢复原状。已有归档课程导致本轮原子回滚，不会自动恢复。

## 示例与本人作答

新增迁移 `learning.0005_review_example_origin`，增加 `ReviewRecord.is_example`（默认False）。示例初始化显式设True；普通表单提交始终使用False。客户端传入同名字段不会覆盖来源。历史仍不可修改或删除。

统计页可选择全部、仅本人实际复习、仅示例演练。此选择影响复习趋势、活动日历、自评分布和课程自评矩阵。任务/错题内容及未来日程表示当前状态，不受复习历史来源选择影响。

模型若曾使用示例历史，会一直标明“含示例历史”；仅本人来源中不使用此类混合状态。实际提交的复习仍按本人记录计数。新建个人错题并完成真实复习，可建立纯个人状态。

## 记忆图的科学边界

- 教学示意：采用 `R(t)=exp(-t/S)` 说明衰减，示意复习日为1、3、7、14，每次假设回到100%并将S乘1.8。速度参数S为1.5、3或6天。这些是可调的教学设定，不是原实验拟合、原始重学节省率、个人正确率或保证效果。
- 当前错题预测：读取同用户、活跃课程、未归档错题的有效FSRS 6.3.2状态，通过该库的 `get_card_retrievability` 计算今天及未来30天的回忆概率。假设期间不再复习，使用固定默认参数，目标保留率90%，未进行个人参数优化。
- 显示最多24道到期最早的有效状态；风险分类对当前来源范围内所有有效状态计算。暂无状态、来源不匹配和无效状态不会被重置或伪造；辅助清单从可展示状态中选预测值最低的5道。

原始测量与模型预测应明确分开。参考：[艾宾浩斯原著第七章](https://psychclassics.yorku.ca/Ebbinghaus/memory7.htm)、[py-fsrs 6.3.2](https://github.com/open-spaced-repetition/py-fsrs/tree/v6.3.2)。

## 新增关联分析

- 课程自评矩阵：在相同日期、用户、归档与来源范围下按课程和rating分组；色深是该课程中的占比，不能视为答题正确率。
- 未来14天负荷：未完成任务的截止日与活跃错题的当前复习日联合计数，不等于时长。过期条目不混入未来日程。最多12门课程。
- 实例知识关联图：课程、知识点、错题节点来自当前用户数据；按课程切换并可点击进入记录。最多8门课，每门8个知识点、10道错题；属于实例关联展示，数据库ER设计仍见数据库课程说明。
- 课程卡片增加知识点、任务、活跃错题计数，使用distinct避免多表连接导致重复计数。

## 代码与验收

`learning/analytics.py` / `insights.py`：只读聚合、来源范围与预测；`static/js/insights.js` / `static/css/insights.css`：曲线切换、SVG和矩阵；`templates/partials/memory_lab.html` / `extended_charts.html`：统计布局。

`learning/tests/test_learning_insights.py` 覆盖示例来源、密码与人工编辑保护、重复导入、原子回滚、真实提交不被标成示例、混合状态排除、预测范围/单调性、坏状态不重置、用户/归档隔离及课程计数。

示例题目涉及的概念参考官方说明：[MySQL 8.4外键](https://dev.mysql.com/doc/refman/8.4/en/create-table-foreign-keys.html)、[PyTorch CrossEntropyLoss](https://docs.pytorch.org/docs/stable/generated/torch.nn.CrossEntropyLoss.html)、[MIT信号处理讲义](https://ocw.mit.edu/courses/2-161-signal-processing-continuous-and-discrete-fall-2008/pages/lecture-notes/)、[NIBIB fMRI说明](https://www.nibib.nih.gov/science-education/glossary/f)。课程内容按常见基础概念自拟，可按实际教材调整。
