"""Versioned account learning data. No SQL, credentials, arbitrary extraction or merge."""
from collections import Counter, deque
from dataclasses import dataclass
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import tempfile
import uuid
import zipfile

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

from attachments.services import attachment_path, _root, STORAGE_KEY
from config.version import BUILD_VERSION

FORMAT = 'studyreview-account-learning-v1'
MAX_ZIP = 128 * 1024 * 1024
MAX_EXPANDED = 256 * 1024 * 1024
MAX_RECORDS = 50000
MAX_JSON = 32 * 1024 * 1024
TRIGGERS = set('''att_image_no_update att_image_no_delete att_manifest_no_update att_manifest_no_delete
att_snapshot_no_update att_snapshot_no_delete study_chapter_insert study_chapter_update
study_course_owner_immutable study_focus_owner_insert study_focus_task_insert study_focus_owner_update
study_focus_task_update study_point_chapter_insert study_knowledgepoint_no_move study_point_chapter_update
study_point_same_course_insert study_point_same_course_update study_review_no_update study_review_no_delete
study_task_no_move study_wrongquestion_no_move study_schedule_no_update study_schedule_no_delete'''.split())
OWNER_PATHS = {
    'learning.course': 'owner_id', 'learning.chapter': 'course__owner_id',
    'learning.knowledgepoint': 'course__owner_id', 'learning.task': 'course__owner_id',
    'learning.wrongquestion': 'course__owner_id', 'learning.questionknowledgepoint': 'question__course__owner_id',
    'learning.reviewrecord': 'question__course__owner_id', 'learning.focussession': 'owner_id',
    'learning.focusinterval': 'session__owner_id', 'attachments.attachment': 'owner_id',
    'attachments.questionimage': 'question__course__owner_id',
    'attachments.reviewimagemanifest': 'review__question__course__owner_id',
    'attachments.reviewimagesnapshot': 'review__question__course__owner_id',
    'assistant.chatsession': 'owner_id', 'assistant.message': 'session__owner_id',
    'assistant.messageattachment': 'message__session__owner_id', 'assistant.draft': 'owner_id',
    'scheduling.schedulingstate': 'user_id', 'scheduling.scheduleevent': 'state__user_id',
    'ai_gateway.account': 'owner_id', 'ai_gateway.requestledger': 'owner_id',
    'ai_gateway.messagecontext': 'owner_id',
}


class ArchiveError(ValueError):
    pass


def models():
    result = {m._meta.label_lower: m for m in apps.get_models()
              if m._meta.app_label in ('learning', 'attachments', 'assistant', 'scheduling', 'ai_gateway')}
    if set(result) != set(OWNER_PATHS):
        raise ArchiveError('当前模型与备份清单不一致，请更新备份工具；未忽略任何新增表。')
    return result


def fields(model):
    return [f for f in model._meta.local_fields if not f.primary_key and not f.generated]


class ArchiveJSONEncoder(DjangoJSONEncoder):
    def default(self, value):
        if isinstance(value, datetime):
            # Preserve all six microsecond digits; DjangoJSONEncoder truncates to milliseconds.
            return value.isoformat(timespec='microseconds')
        return super().default(value)


def dump_json(value):
    return json.dumps(value, cls=ArchiveJSONEncoder, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def schema_signature():
    specs = {label: [(f.name, f.get_internal_type(), f.null, f.max_length,
                      f.related_model._meta.label_lower if f.is_relation else None)
                     for f in fields(model)] for label, model in models().items()}
    return hashlib.sha256(dump_json(specs)).hexdigest()


def required_migrations():
    return sorted([list(node) for node in MigrationLoader(None).graph.leaf_nodes()])


def dependency_errors():
    errors = []
    if connection.vendor != 'mysql' or connection.mysql_version < (8, 0, 16):
        errors.append('需要MySQL 8.0.16或更新版本及当前应用模型。')
    try:
        loader = MigrationLoader(connection)
        if any(tuple(node) not in loader.applied_migrations for node in required_migrations()):
            errors.append('目标数据库尚未完成当前版本迁移。')
        if not {m._meta.db_table for m in models().values()} <= set(connection.introspection.table_names()):
            errors.append('目标缺少业务表，不能恢复。')
        if connection.vendor == 'mysql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()')
                if not TRIGGERS <= {row[0] for row in cursor.fetchall()}:
                    errors.append('目标缺少当前版本的数据库保护触发器。')
                cursor.execute('SELECT TABLE_NAME,COLUMN_NAME,REFERENCED_TABLE_NAME,REFERENCED_COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL')
                actual = set(cursor.fetchall())
                expected = {(model._meta.db_table, field.column, field.related_model._meta.db_table, field.target_field.column)
                    for model in models().values() for field in model._meta.local_fields if field.is_relation and field.db_constraint}
                if not expected <= actual:
                    errors.append('目标缺少当前版本的业务外键，无法保证关联完整性。')
    except Exception:
        errors.append('无法核对目标数据库结构，请先完成环境检查。')
    return errors


def target_report(user, *, own_restore=False):
    errors = dependency_errors()
    if not own_restore and (Path(settings.DATA_DIR) / 'private' / 'archive-restore.pending.json').exists():
        errors.append('目标存在未完成的恢复标记，需先人工核验；不能重复导入。')
    if not errors:
        occupied = sum(m._base_manager.count() for m in models().values())
        if occupied:
            errors.append('目标学习空间已有业务数据，拒绝合并、覆盖或清空。')
        if get_user_model().objects.exclude(pk=user.pk).exists():
            errors.append('目标存在其他账号；当前恢复仅支持一个已有空账号的独立学习空间。')
        if user.is_staff or user.is_superuser:
            errors.append('请使用普通空学习账号，恢复工具不处理管理员权限。')
    try:
        root = _root()
        if root.exists() and any(root.iterdir()):
            errors.append('目标媒体目录非空，拒绝覆盖文件。')
    except (ValidationError, OSError):
        errors.append('目标媒体路径不可安全访问。')
    return {'ready': not errors, 'errors': errors,
            'credentials_changed': False, 'requires_closed_app': True}


def _json(raw):
    if len(raw) > MAX_JSON:
        raise ArchiveError('备份清单或记录文件超过32MB上限。')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ArchiveError('JSON含重复字段，拒绝歧义内容。')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ArchiveError('JSON数值不合法。')))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ArchiveError('备份JSON无效或嵌套过深。') from exc


def _key(model, pk):
    return model._meta.label_lower, str(model._meta.pk.to_python(pk))


def validate_records(records, source_owner):
    allowed = models()
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ArchiveError('记录结构无效或超过50000条上限。')
    objects = {}; dependencies = {}; raw_rows = {}
    try:
        for row in records:
            if not isinstance(row, dict) or set(row) != {'model', 'pk', 'fields'}:
                raise ArchiveError('记录结构不完整。')
            model = allowed.get(row['model'])
            if model is None or not isinstance(row['fields'], dict):
                raise ArchiveError('包含当前工具不支持的表；没有忽略该表。')
            if set(row['fields']) != {f.name for f in fields(model)}:
                raise ArchiveError('记录字段与当前版本不一致，不能丢弃或补造字段。')
            key = _key(model, row['pk'])
            if row['pk'] is None or key in objects:
                raise ArchiveError('存在空主键或重复记录。')
            obj = next(serializers.deserialize('python', [row])).object
            objects[key] = obj; raw_rows[key] = row; dependencies[key] = set()
            for field in model._meta.local_fields:
                if field.generated:
                    continue
                value = getattr(obj, field.attname)
                if field.is_relation:
                    if value is None:
                        if not field.null:
                            raise ArchiveError('必需的关联为空。')
                    elif field.related_model is get_user_model():
                        if value != source_owner:
                            raise ArchiveError('记录包含其他账号归属。')
                    else:
                        dependencies[key].add(_key(field.related_model, value))
                else:
                    if value is None and not field.null:
                        raise ArchiveError('必需字段为空。')
                    field.validate(value, obj); field.run_validators(value)
                    if field.get_internal_type() == 'DateTimeField' and value and timezone.is_naive(value):
                        raise ArchiveError('时间戳缺少时区。')
        for refs in dependencies.values():
            if refs - objects.keys():
                raise ArchiveError('记录存在缺失的依赖，不能恢复不完整资料。')
    except ArchiveError:
        raise
    except Exception as exc:
        raise ArchiveError('记录类型、字段值或关联标识不合法。') from exc

    def related(obj, field):
        fk = obj._meta.get_field(field)
        value = getattr(obj, fk.attname)
        return objects.get(_key(fk.related_model, value)) if value is not None else None

    snapshot_counts = Counter(obj.review_id for obj in objects.values() if obj._meta.label_lower == 'attachments.reviewimagesnapshot')
    unique_values = {}
    for obj in objects.values():
        groups = [(field.name,) for field in obj._meta.local_fields if field.unique and not field.generated]
        groups += [constraint.fields for constraint in obj._meta.constraints if getattr(constraint, 'fields', ()) and not getattr(constraint, 'condition', None)]
        for group in groups:
            values = tuple(getattr(obj, obj._meta.get_field(name).attname) for name in group)
            if None in values:
                continue
            signature = (obj._meta.label_lower, tuple(group))
            seen = unique_values.setdefault(signature, set())
            if values in seen:
                raise ArchiveError('资料包中存在重复的唯一标识或业务关系。')
            seen.add(values)
    # Cache only package-local relationships; model.clean must not query the target database.
    for obj in objects.values():
        for field in obj._meta.local_fields:
            if field.is_relation:
                value = getattr(obj, field.attname)
                field.set_cached_value(obj, get_user_model()(pk=source_owner) if field.related_model is get_user_model() else related(obj, field.name))
    for obj in objects.values():
        label = obj._meta.label_lower
        if label == 'learning.chapter' and obj.parent_id:
            parent = related(obj, 'parent')
            if parent.pk == obj.pk or parent.course_id != obj.course_id or parent.parent_id:
                raise ArchiveError('章节存在跨课程、循环或超出两层的关系。')
        if label == 'learning.knowledgepoint' and obj.chapter_id and related(obj, 'chapter').course_id != obj.course_id:
            raise ArchiveError('知识点与章节不属于同一课程。')
        if label == 'learning.questionknowledgepoint' and related(obj, 'question').course_id != related(obj, 'knowledge_point').course_id:
            raise ArchiveError('错题与知识点不属于同一课程。')
        if label == 'learning.focussession':
            if obj.status == 'running':
                raise ArchiveError('包含仍在运行的专注；请先暂停或结束后重新导出，避免恢复时虚增时长。')
            if obj.task_id and related(obj, 'task').course_id != obj.course_id:
                raise ArchiveError('专注任务与课程不一致。')
        if label == 'learning.focusinterval' and obj.ended_at is None:
            raise ArchiveError('专注有效区间未关闭，请先暂停或结束后重新导出。')
        if label == 'scheduling.scheduleevent' and related(obj, 'state').question_id != related(obj, 'review_record').question_id:
            raise ArchiveError('调度事件与复习题目不一致。')
        if label == 'learning.task' and ((obj.status == 'done') != (obj.completed_at is not None)):
            raise ArchiveError('任务状态与完成时间不一致。')
        if label == 'learning.reviewrecord' and obj.next_review_date <= obj.review_date:
            raise ArchiveError('复习安排日期不合法。')
        if label == 'attachments.reviewimagesnapshot':
            attachment = related(obj, 'attachment')
            if (obj.sha256_snapshot, obj.width_snapshot, obj.height_snapshot) != (attachment.sha256, attachment.width, attachment.height):
                raise ArchiveError('历史图片快照与不可变图片内容不一致。')
        if label == 'attachments.reviewimagemanifest':
            count = snapshot_counts[obj.pk]
            if obj.image_count != count:
                raise ArchiveError('复习图片清单数量与快照不一致。')
        if label.startswith('scheduling.'):
            try:
                obj.clean()
            except ValidationError as exc:
                raise ArchiveError('复习调度状态或算法版本无效。') from exc

    intervals = {}
    for obj in objects.values():
        if obj._meta.label_lower == 'learning.focusinterval':
            intervals.setdefault(obj.session_id, []).append(obj)
    for session_id, rows in intervals.items():
        session = objects[('learning.focussession', str(session_id))]
        previous_end = session.started_at
        for interval in sorted(rows, key=lambda item: item.started_at):
            if interval.started_at < previous_end or interval.ended_at < interval.started_at or (session.ended_at and interval.ended_at > session.ended_at):
                raise ArchiveError('专注有效区间重叠、逆序或超出会话范围。')
            previous_end = interval.ended_at

    incoming = {key: len(refs) for key, refs in dependencies.items()}
    dependents = {key: [] for key in objects}
    for key, refs in dependencies.items():
        for ref in refs:
            dependents[ref].append(key)
    ready = deque(key for key, degree in incoming.items() if not degree)
    ordered = []
    while ready:
        key = ready.popleft(); ordered.append(objects[key])
        for child in dependents[key]:
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
    if len(ordered) != len(objects):
        raise ArchiveError('记录关联存在循环，不能安全按依赖恢复。')
    return ordered


@dataclass
class CheckedArchive:
    manifest: dict
    records: list
    objects: list
    warnings: list
    restore_blockers: list

    def summary(self):
        return {'format': FORMAT, 'build': self.manifest['build'],
                'created_at': self.manifest['created_at'], 'records': len(self.records),
                'models': len(self.manifest['models']), 'images': self.manifest['attachment_count'],
                'media_files': len(self.manifest['files']) - 1, 'warnings': self.warnings,
                'restore_blockers': self.restore_blockers, 'credentials_included': False,
                'kind': '账号学习资料包，不是整库备份'}


def inspect_archive(stream):
    try:
        stream.seek(0, 2)
        if stream.tell() > MAX_ZIP:
            raise ArchiveError('压缩包超过128MB上限；未读取或导入数据。')
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or len(names) > 100002:
                raise ArchiveError('压缩包有重复或过多条目。')
            if sum(entry.file_size for entry in entries) > MAX_EXPANDED:
                raise ArchiveError('展开大小超过256MB上限。')
            if 'manifest.json' not in names:
                raise ArchiveError('缺少版本清单，不能识别为当前账号学习资料包。')
            for entry in entries:
                name = entry.filename
                if entry.is_dir() or name.startswith('/') or '\\' in name or ':' in name or any(p in ('', '.', '..') for p in name.split('/')) or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ArchiveError('压缩包包含不安全路径或链接。')
                if entry.flag_bits & 1 or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ArchiveError('不支持加密或特殊压缩格式。')
            if archive.getinfo('manifest.json').file_size > 1024 * 1024:
                raise ArchiveError('版本清单过大。')
            manifest = _json(archive.read('manifest.json'))
            if not isinstance(manifest, dict) or manifest.get('format') != FORMAT:
                raise ArchiveError('旧账号包、SQL整库备份或其他格式不能直接导入；需完整迁移验证，不能忽略章节或专注资料。')
            if manifest.get('schema') != schema_signature() or manifest.get('migrations') != required_migrations():
                raise ArchiveError('备份版本与当前模型/迁移不一致，请使用匹配版本；没有自动丢弃字段。')
            if set(manifest.get('models', {})) != set(models()):
                raise ArchiveError('业务表清单不完整，必须覆盖当前22类业务数据。')
            if manifest.get('credentials_included') is not False or type(manifest.get('source_owner_id')) is not int or manifest['source_owner_id'] <= 0:
                raise ArchiveError('账号归属或凭据边界声明无效。')
            file_map = manifest.get('files')
            if not isinstance(file_map, dict) or set(names) != {'manifest.json', *file_map} or 'records.json' not in file_map:
                raise ArchiveError('文件清单存在遗漏或额外内容。')
            for name, spec in file_map.items():
                if archive.getinfo(name).file_size != spec['bytes']:
                    raise ArchiveError('文件大小与清单不一致。')
                digest = hashlib.sha256()
                with archive.open(name) as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        digest.update(chunk)
                if digest.hexdigest() != spec['sha256']:
                    raise ArchiveError('文件校验和不一致，备份可能损坏。')
            if archive.getinfo('records.json').file_size > MAX_JSON:
                raise ArchiveError('记录文件超过32MB上限。')
            records = _json(archive.read('records.json'))
            objects = validate_records(records, manifest['source_owner_id'])
            counts = Counter(row['model'] for row in records)
            if manifest['models'] != {name: counts[name] for name in models()}:
                raise ArchiveError('记录数量与业务表清单不一致。')
            expected = {'records.json'}; attachment_count = 0; warnings = []; blockers = []
            for obj in objects:
                label = obj._meta.label_lower
                if label == 'attachments.attachment':
                    attachment_count += 1
                    key = obj.storage_key
                    if not STORAGE_KEY.fullmatch(key) or key[:2] != key[3:5]:
                        raise ArchiveError('媒体存储标识不合法。')
                    for filename, size in [('full.png', obj.byte_size), ('thumbnail.png', obj.thumbnail_bytes)]:
                        name = 'media/' + key + '/' + filename; expected.add(name)
                        if name not in file_map or file_map[name]['bytes'] != size:
                            raise ArchiveError('图片原件或缩略图缺失/大小不符。')
                        from PIL import Image
                        with archive.open(name) as media, Image.open(media) as picture:
                            if picture.format != 'PNG' or min(picture.size) < 1 or max(picture.size) > 10000:
                                raise ArchiveError('媒体文件不是受支持的 PNG 图片。')
                            if filename == 'full.png' and picture.size != (obj.width, obj.height):
                                raise ArchiveError('图片尺寸与数据库记录不一致。')
                            picture.verify()
                    if file_map['media/' + key + '/full.png']['sha256'] != obj.sha256:
                        raise ArchiveError('图片与数据库内容哈希不一致。')
                if label == 'ai_gateway.account' and (obj.enabled or obj.key_reference):
                    blockers.append('包含依赖本机密钥的AI配置；密钥未打包，当前恢复拒绝自动清空或替换该配置。')
                if label == 'assistant.draft' and obj.status == 'pending':
                    warnings.append('待确认草稿会原样保留，但旧确认签名不保证跨环境可用，需要重新生成操作预览。')
            if expected != set(file_map) or manifest.get('attachment_count') != attachment_count:
                raise ArchiveError('媒体清单与记录不完整对应。')
            return CheckedArchive(manifest, records, objects, sorted(set(warnings)), sorted(set(blockers)))
    except ArchiveError:
        raise
    except Exception as exc:
        raise ArchiveError('备份格式损坏或字段无效，未执行导入。') from exc


def export_account(user):
    errors = dependency_errors()
    if errors:
        raise ArchiveError('；'.join(errors))
    if connection.in_atomic_block:
        raise ArchiveError('请在独立请求中导出，以取得一致的数据快照。')
    output = tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024, mode='w+b')
    try:
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        with transaction.atomic():
            rows = []; counts = {}; attachments = []
            for label, model in models().items():
                query = model._base_manager.filter(**{OWNER_PATHS[label]: user.pk}).order_by('pk')
                batch = serializers.serialize('python', query, fields=[f.name for f in fields(model)])
                counts[label] = len(batch); rows.extend(batch)
                if len(rows) > MAX_RECORDS:
                    raise ArchiveError('超过50000条记录上限，未生成不完整备份。')
                if label == 'attachments.attachment':
                    attachments = list(query)
            raw = dump_json(rows)
            if len(raw) > MAX_JSON:
                raise ArchiveError('记录文件超过32MB上限，未截断导出。')
            normal = _json(raw)
            validate_records(normal, user.pk)
            files = {}; total = len(raw)
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('records.json', raw)
                files['records.json'] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                for item in attachments:
                    for thumbnail in (False, True):
                        path = attachment_path(item, thumbnail)
                        name = 'media/' + item.storage_key + '/' + ('thumbnail.png' if thumbnail else 'full.png')
                        digest = hashlib.sha256(); size = 0
                        with path.open('rb') as source, archive.open(name, 'w') as dest:
                            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                                size += len(chunk); total += len(chunk)
                                if total > MAX_EXPANDED:
                                    raise ArchiveError('展开数据超过256MB上限，未生成截断备份。')
                                digest.update(chunk); dest.write(chunk)
                        if size != (item.thumbnail_bytes if thumbnail else item.byte_size) or (not thumbnail and digest.hexdigest() != item.sha256):
                            raise ArchiveError('图片文件缺失或与记录不一致，导出已中止。')
                        files[name] = {'bytes': size, 'sha256': digest.hexdigest()}
                manifest = {'format': FORMAT, 'build': BUILD_VERSION, 'schema': schema_signature(),
                    'migrations': required_migrations(), 'created_at': timezone.now().isoformat(),
                    'source_owner_id': user.pk, 'credentials_included': False, 'models': counts,
                    'attachment_count': len(attachments), 'files': files}
                archive.writestr('manifest.json', dump_json(manifest))
        if output.tell() > MAX_ZIP:
            raise ArchiveError('压缩包超过128MB上限，未返回不完整备份。')
        output.seek(0)
        inspect_archive(output)
        output.seek(0)
        return output
    except Exception:
        output.close()
        raise


def restore_account(stream, user, *, expected_database, confirmed=False):
    """Only an explicitly named, initialized, empty isolated workspace. No DDL or merge."""
    database = connection.settings_dict['NAME']
    if not confirmed or expected_database != database or database not in getattr(settings, 'AUTHORIZED_MIGRATION_SCHEMAS', ()) or not database.startswith(('study_review_v2_dev_', 'test_study_review_v2_')):
        raise ArchiveError('恢复只允许明确确认且名称完全匹配的授权隔离库。')
    if (Path(settings.DATA_DIR) / 'private' / 'desktop-state.json').exists():
        raise ArchiveError('目标应用仍在运行，请先正常关闭；未进行恢复。')
    checked = inspect_archive(stream)
    if checked.restore_blockers:
        raise ArchiveError('；'.join(checked.restore_blockers))
    report = target_report(user)
    if not report['ready']:
        raise ArchiveError('；'.join(report['errors']))
    root = _root(); root.parent.mkdir(parents=True, exist_ok=True)
    stage = root.parent / ('.restore-stage-' + uuid.uuid4().hex)
    marker = root.parent / 'archive-restore.pending.json'
    with marker.open('x', encoding='utf-8') as output:
        json.dump({'database': database, 'stage': stage.name, 'created_at': timezone.now().isoformat()}, output)
    stage.mkdir()
    try:
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            for name, spec in checked.manifest['files'].items():
                if not name.startswith('media/'):
                    continue
                target = stage.joinpath(*name.split('/')[1:])
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                with archive.open(name) as source, target.open('xb') as dest:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        digest.update(chunk); dest.write(chunk)
                if digest.hexdigest() != spec['sha256']:
                    raise ArchiveError('备份在检查后发生变化；未写数据库。')
        with transaction.atomic():
            get_user_model().objects.select_for_update().get(pk=user.pk)
            report = target_report(user, own_restore=True)
            if not report['ready']:
                raise ArchiveError('；'.join(report['errors']))
            for obj in checked.objects:
                for field in fields(type(obj)):
                    if field.is_relation and field.related_model is get_user_model():
                        setattr(obj, field.attname, user.pk)
                # raw inserts preserve immutable history timestamps and never update an existing row.
                obj.save_base(raw=True, force_insert=True)
            connection.check_constraints(table_names=[m._meta.db_table for m in models().values()])
            for label, model in models().items():
                expected = serializers.serialize('python', [obj for obj in checked.objects if obj._meta.label_lower == label], fields=[f.name for f in fields(model)])
                actual = serializers.serialize('python', model._base_manager.order_by('pk'), fields=[f.name for f in fields(model)])
                order = lambda row: str(row['pk'])
                if dump_json(sorted(expected, key=order)) != dump_json(sorted(actual, key=order)):
                    raise ArchiveError('恢复后字段核对不一致，数据事务回滚。')
            if root.exists():
                root.rmdir()  # Only a verified empty directory; never recursive deletion.
            stage.rename(root)
        marker.unlink()
        return {'restored': True, 'records': len(checked.records), 'images': checked.manifest['attachment_count'],
                'credentials_changed': False, 'merged': False, 'warnings': checked.warnings}
    except Exception as exc:
        # Do not remove unknown files or retry a possibly committed transaction.
        raise ArchiveError('恢复未完成。数据库写入使用事务；本次暂存或媒体目录保留供检查，禁止直接重复恢复或清空目标。') from exc
