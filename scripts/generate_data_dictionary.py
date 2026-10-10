"""Generate the data dictionary from model metadata without opening a database."""
from __future__ import annotations
import argparse
from importlib.metadata import version
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def escape(value):
    return str(value).replace('|', '\\|').replace('\n', ' ')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'docs' / '数据库数据字典.md')
    args = parser.parse_args()
    from django.conf import settings
    settings.configure(SECRET_KEY='metadata-only-no-server', USE_TZ=True,
        TIME_ZONE='Asia/Shanghai', DEFAULT_AUTO_FIELD='django.db.models.BigAutoField',
        INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes',
                        'learning', 'attachments', 'assistant', 'ai_gateway', 'scheduling'],
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}})
    import django
    django.setup()
    from django.apps import apps
    labels = {'learning', 'attachments', 'assistant', 'ai_gateway', 'scheduling'}
    models = sorted((m for m in apps.get_models() if m._meta.app_label in labels),
                    key=lambda m: m._meta.db_table)
    lines = ['# 数据库数据字典', '',
        f'由当前 Django {version("Django")} 模型元数据生成；共 {len(models)} 张业务表。生成过程不读取安全配置、不连接 MySQL，也不读取真实记录。', '',
        '数据库另有 Django 账户、权限、会话和迁移系统表。完整 SQL、触发器及数据库课程说明见 [04-数据库课程说明.md](04-数据库课程说明.md)。迁移文件是结构演进的执行依据，结构 SQL 供课程阅读。', '',
        '下面的 ER 图展示业务表外键；auth_user 为 Django 用户表。', '', chr(96)*3 + 'mermaid', 'erDiagram']
    for model in models:
        for field in model._meta.local_fields:
            if field.is_relation and field.remote_field:
                lines.append('    ' + field.remote_field.model._meta.db_table + ' ||--o{ ' +
                             model._meta.db_table + ' : ' + field.name)
    lines.extend([chr(96)*3, ''])
    for model in models:
        meta = model._meta
        lines.extend(['## ' + meta.db_table, '',
            '模型：' + meta.label + '。' + str(meta.verbose_name) + '。', '',
            '| 字段 | Django 类型 / 长度 | 空值 / 主键 / 唯一 | 外键及删除规则 | 默认 / 选项 |',
            '|---|---|---|---|---|'])
        for field in meta.local_fields:
            type_name = field.get_internal_type()
            if field.max_length:
                type_name += ' / ' + str(field.max_length)
            if hasattr(field, 'max_digits'):
                type_name += f' / ({field.max_digits}, {field.decimal_places})'
            flags = f'NULL={field.null}, PK={field.primary_key}, UNIQUE={field.unique}'
            relation = ''
            if field.is_relation and field.remote_field:
                relation = field.remote_field.model._meta.db_table + '.' + field.target_field.name
                relation += ' / ' + field.remote_field.on_delete.__name__
            default = ''
            if field.has_default():
                default = getattr(field.default, '__name__', str(field.default))
            if field.choices:
                default += '；选项 ' + repr(list(field.choices))
            lines.append('| ' + ' | '.join(map(escape, [field.name, type_name, flags, relation, default])) + ' |')
        lines.extend(['', '模型声明的约束：', ''])
        if meta.constraints:
            for constraint in meta.constraints:
                details = list(getattr(constraint, 'fields', ())) or str(getattr(constraint, 'condition', ''))
                lines.append('- ' + constraint.name + '：' + type(constraint).__name__ + ' ' + escape(details))
        else:
            lines.append('无额外模型级约束；主键、字段唯一性与外键仍生效。')
        lines.extend(['', '模型声明的索引：', ''])
        if meta.indexes:
            lines.extend('- ' + index.name + '：' + ', '.join(index.fields) for index in meta.indexes)
        else:
            lines.append('无额外模型级索引；数据库自动为主键、唯一字段与外键建立相应索引。')
        lines.append('')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Data dictionary generated: {len(models)} business models; no database connection.')

if __name__ == '__main__':
    main()
