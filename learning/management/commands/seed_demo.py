"""Re-runnable synthetic demo; creates new accounts only, never resets or deletes."""
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from django.conf import settings
from learning.models import Course, KnowledgePoint, Task, WrongQuestion, QuestionKnowledgePoint, ReviewRecord


class Command(BaseCommand):
    help = '在隔离库生成合成演示数据；已有同名账户和数据保持原样。'

    @transaction.atomic
    def handle(self, *args, **options):
        isolated_v2 = getattr(settings, 'V2_DEVELOPMENT_DATABASE', None)
        if connection.vendor == 'mysql' and connection.settings_dict['NAME'] not in {'study_review_dev', isolated_v2}:
            raise CommandError('演示数据只能写入隔离开发库 study_review_dev。')
        student, created = User.objects.get_or_create(username='demo_student', defaults={'first_name': '示例学生'})
        if not created:
            self.stdout.write('demo_student 已存在，保留其密码与数据；没有重复生成或重置。')
            return
        student.set_password('StudyDemo2026!')
        student.save(update_fields=['password'])
        empty, empty_created = User.objects.get_or_create(username='demo_empty', defaults={'first_name': '隔离验证账户'})
        if empty_created:
            empty.set_password('StudyEmpty2026!')
            empty.save(update_fields=['password'])
        today = timezone.localdate()
        database = Course.objects.create(owner=student, name='数据库系统原理', description='从关系模型到 SQL，把概念与实际查询联系起来。')
        maths = Course.objects.create(owner=student, name='高等数学', description='理解变化、极限与积分，记录容易忽略的条件。')
        structure = Course.objects.create(owner=student, name='数据结构', description='用清晰的结构组织数据，分析算法的时间与空间开销。')
        archived = Course.objects.create(owner=student, name='线性代数', description='已完成阶段课程，保留学习记录供回顾。', is_archived=True)
        points = {
            'keys': KnowledgePoint.objects.create(course=database, name='主键与外键'),
            'group': KnowledgePoint.objects.create(course=database, name='分组与聚合'),
            'transaction': KnowledgePoint.objects.create(course=database, name='事务与完整性'),
            'limit': KnowledgePoint.objects.create(course=maths, name='极限与连续'),
            'derivative': KnowledgePoint.objects.create(course=maths, name='导数与微分'),
            'stack': KnowledgePoint.objects.create(course=structure, name='栈与队列'),
            'complexity': KnowledgePoint.objects.create(course=structure, name='算法复杂度'),
        }
        task_data = [
            (database, '完成数据库约束练习', '对比主键、外键与唯一约束，写出建表语句。', 0, False),
            (database, '练习 SQL 分组查询', '练习 GROUP BY 与 HAVING 的区别。', 1, False),
            (maths, '整理极限计算方法', '整理等价无穷小的使用条件。', -1, False),
            (structure, '手写循环队列', '分别实现入队、出队和判满条件。', 2, False),
            (database, '复习关系模型基本概念', '区分候选键与主键。', -2, True),
            (maths, '完成导数基础题', '', -3, True),
            (archived, '整理矩阵运算笔记', '归档课程任务不会进入日常待办。', -7, False),
        ]
        for course, title, description, offset, done in task_data:
            Task.objects.create(course=course, title=title, description=description, due_date=today + timedelta(days=offset),
                status='done' if done else 'todo', completed_at=timezone.now() - timedelta(days=2) if done else None)
        question_data = [
            (database, '主键和外键分别有什么作用？', '说明主键与外键的作用。外键是否必须唯一？',
                '外键也必须唯一。', '主键唯一标识一行且不为空。外键引用另一表的候选键或主键，用来维护参照完整性；外键值可以重复。',
                '把行标识与引用关系混为一谈。', -1, ['keys', 'transaction'], False),
            (database, 'WHERE 与 HAVING 的区别', '在分组统计中，WHERE 与 HAVING 分别在何时筛选？',
                '两者都在分组后筛选。', 'WHERE 在分组前筛选行；HAVING 在分组后筛选组，可使用聚合条件。',
                '忽略了 SQL 查询逻辑处理顺序。', 0, ['group'], False),
            (maths, '连续是否一定可导？', '函数在一点连续，是否必然在该点可导？给出反例。',
                '连续就能求导。', '可导必连续，连续未必可导。f(x)=|x| 在 x=0 连续，但左右导数分别为 -1 与 1，因此不可导。',
                '把必要条件当成充分条件。', 0, ['limit', 'derivative'], False),
            (structure, '栈与队列的出入顺序', '栈与队列分别遵循什么出入顺序？', '栈先进先出，队列后进先出。',
                '栈后进先出（LIFO），队列先进先出（FIFO）。', '两个基本概念记反了。', 1, ['stack'], False),
            (structure, '嵌套循环的时间复杂度', '外层 n 次、内层 n 次且循环体 O(1)，总时间复杂度是多少？', 'O(n)',
                '总执行次数为 n×n，因此时间复杂度是 O(n²)。', '只计算了一层循环。', 3, ['complexity'], False),
            (database, '事务原子性的含义', '为什么复习记录与下次日期应在同一事务中保存？', '分别保存也不会有问题。',
                '原子性保证两项写入一起成功或一起回滚，避免历史与当前安排不一致。', '没有考虑第二步失败的情况。', 7, ['transaction'], False),
            (database, '已归档：候选键与主键', '一张表可以有多个主键吗？', '每个候选键都是主键。',
                '一张表选择一个候选键作为主键，其余候选键仍可用唯一约束表达。', '未区分候选键与被选定的主键。', -3, ['keys'], True),
            (archived, '矩阵乘法能否交换？', '一般情况下 AB 是否等于 BA？', '等于。',
                '矩阵乘法一般不满足交换律，且两个乘积可能不同时有定义。', '误用了实数乘法的交换律。', -4, [], False),
        ]
        questions = []
        for course, title, content, original, correct, reason, offset, keys, is_archived in question_data:
            question = WrongQuestion.objects.create(course=course, title=title, content=content, original_answer=original,
                correct_answer=correct, error_reason=reason, next_review_date=today + timedelta(days=offset), is_archived=is_archived)
            for key in keys:
                QuestionKnowledgePoint.objects.create(question=question, knowledge_point=points[key])
            questions.append(question)
        for index, (question, offset, rating, answer) in enumerate([
            (questions[0], -6, 'again', '未作答'), (questions[0], -3, 'hard', '主键标识一行，外键引用其他表'),
            (questions[3], -1, 'good', '栈后进先出，队列先进先出'), (questions[6], -2, 'good', '主键是选定的候选键'),
            (questions[7], -5, 'hard', '矩阵乘法一般不能交换'),
        ]):
            date = today + timedelta(days=offset)
            stamp = datetime.combine(date, time(19, 30), tzinfo=ZoneInfo('Asia/Shanghai'))
            ReviewRecord.objects.create(question=question, reviewed_at=stamp, review_date=date, answer=answer, rating=rating,
                note='合成演示历史；不是实际学习记录。', next_review_date=date + timedelta(days={'again': 1, 'hard': 3, 'good': 7}[rating]),
                title_snapshot=question.title, question_snapshot=question.content, original_answer_snapshot=question.original_answer,
                correct_answer_snapshot=question.correct_answer, error_reason_snapshot=question.error_reason,
                course_snapshot=question.course.name, knowledge_points_snapshot=list(question.knowledge_points.values_list('name', flat=True)),
                submission_key=uuid.uuid4())
        self.stdout.write(self.style.SUCCESS('合成演示数据已创建：2 个普通账户、4 门课程、7 个知识点、7 项任务、8 道错题、5 条复习历史。'))
        self.stdout.write('demo_student / StudyDemo2026!；空账户 demo_empty / StudyEmpty2026!（仅演示）')
