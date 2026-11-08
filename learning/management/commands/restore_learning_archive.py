"""Explicit maintenance command; never imports into the running user's workspace."""
import json
from pathlib import Path
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from learning.archive import ArchiveError, inspect_archive, restore_account, target_report


class Command(BaseCommand):
    help = '预检账号学习资料包；仅显式确认后恢复到已初始化的空隔离空间，不改登录凭据。'

    def add_arguments(self, parser):
        parser.add_argument('--archive', required=True)
        parser.add_argument('--username', required=True)
        parser.add_argument('--expect-database')
        parser.add_argument('--confirm-empty-workspace', action='store_true')
        parser.add_argument('--report', required=True)

    def handle(self, *args, **options):
        report = Path(options['report'])
        if not report.is_absolute() or report.exists() or not report.parent.is_dir():
            raise CommandError('报告必须是现有目录中的全新绝对路径文件。')
        user = get_user_model().objects.filter(username=options['username']).first()
        if user is None:
            raise CommandError('请先由本人在新空间建立目标普通账号；工具不创建或更改登录凭据。')
        try:
            with Path(options['archive']).open('rb') as source:
                checked = inspect_archive(source)
                outcome = {'package': checked.summary(), 'target': target_report(user), 'restored': False}
                if options['confirm_empty_workspace']:
                    outcome.update(restore_account(source, user, expected_database=options['expect_database'], confirmed=True))
            with report.open('x', encoding='utf-8') as output:
                json.dump(outcome, output, ensure_ascii=False, indent=2)
            self.stdout.write('检查结果已保存；' + ('隔离恢复完成，登录凭据未改变。' if outcome['restored'] else '未执行恢复。'))
        except (ArchiveError, OSError) as exc:
            raise CommandError(str(exc)) from None
