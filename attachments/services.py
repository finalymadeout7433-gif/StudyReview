"""Private image ingest and ownership-scoped relationships; never accepts SQL or paths."""
import hashlib
import io
import logging
import os
from pathlib import Path
import re
import stat
import unicodedata
import uuid
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.http import Http404
from django.utils import timezone

from learning.models import Course, WrongQuestion, ReviewRecord
from .models import Attachment, ImageRole, QuestionImage, ReviewImageManifest, ReviewImageSnapshot

logger = logging.getLogger(__name__)
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 80 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_DIMENSION = 10_000
THUMBNAIL_SIZE = 720
ALLOWED_MIMES = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}
STORAGE_KEY = re.compile(r'\A[0-9a-f]{2}/[0-9a-f]{32}\Z')


class _BoundedBuffer(io.BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_OUTPUT_BYTES:
            raise ValidationError('规范化后的图片过大，请分成清晰的单页图片。')
        return super().write(data)


def _display_name(name):
    basename = unicodedata.normalize('NFKC', str(name or '')).replace('\\', '/').rsplit('/', 1)[-1]
    basename = ''.join(character for character in basename if unicodedata.category(character)[0] != 'C')
    basename = re.sub(r'[<>"&|:*?]', '_', basename).strip(' .')
    return basename[:200] or '学习图片.png'


def _read_upload(uploaded_file):
    if getattr(uploaded_file, 'size', 0) > MAX_INPUT_BYTES:
        raise ValidationError('每张图片不能超过 8 MB。')
    mime = str(getattr(uploaded_file, 'content_type', '')).lower().strip()
    if mime not in ALLOWED_MIMES.values():
        raise ValidationError('只支持静态 PNG、JPEG、WebP 图片。')
    data = bytearray()
    try:
        uploaded_file.seek(0)
        while chunk := uploaded_file.read(min(64 * 1024, MAX_INPUT_BYTES + 1 - len(data))):
            data.extend(chunk)
            if len(data) > MAX_INPUT_BYTES:
                raise ValidationError('每张图片不能超过 8 MB。')
    except (OSError, TypeError, AttributeError):
        raise ValidationError('无法读取图片，请重新选择文件。')
    if not data:
        raise ValidationError('图片文件为空。')
    return bytes(data), mime


def _check_image_header(image, mime):
    if image.format not in ALLOWED_MIMES or ALLOWED_MIMES[image.format] != mime:
        raise ValidationError('图片的真实格式与上传类型不符。')
    width, height = image.size
    if not (0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION) or width * height > MAX_PIXELS:
        raise ValidationError('图片不能超过 2000 万像素，单边不能超过 10000 像素。')
    if getattr(image, 'is_animated', False) or getattr(image, 'n_frames', 1) != 1:
        raise ValidationError('只支持静态图片，请选择单帧图片。')


def _normalise(uploaded_file):
    raw, mime = _read_upload(uploaded_file)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as header:
                _check_image_header(header, mime)
                header.verify()
            with Image.open(io.BytesIO(raw)) as source:
                _check_image_header(source, mime)
                source.load()
                upright = ImageOps.exif_transpose(source)
                alpha = upright.mode in ('RGBA', 'LA') or 'transparency' in upright.info
                converted = upright.convert('RGBA' if alpha else 'RGB')
                # A fresh image removes EXIF, PNG text, ICC profiles and every other source metadata entry.
                clean = Image.new(converted.mode, converted.size)
                clean.paste(converted)
                full = _BoundedBuffer()
                clean.save(full, format='PNG', compress_level=6)
                thumb = clean.copy()
                thumb.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.Resampling.LANCZOS)
                thumbnail = _BoundedBuffer()
                thumb.save(thumbnail, format='PNG', compress_level=6)
                result = (full.getvalue(), thumbnail.getvalue(), clean.width, clean.height)
                thumb.close()
                clean.close()
                converted.close()
                if upright is not source:
                    upright.close()
                return result
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError('图片损坏或无法安全解码，请重新导出 PNG、JPEG 或 WebP。')


def _reject_link(path):
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise ValidationError('图片存储路径不安全，请检查私有媒体目录。')


def _root(create=False):
    configured = getattr(settings, 'PRIVATE_MEDIA_ROOT', None)
    if not configured:
        raise ImproperlyConfigured('PRIVATE_MEDIA_ROOT 必须指向独立的私有媒体目录。')
    raw = Path(configured)
    if not raw.is_absolute():
        raise ImproperlyConfigured('PRIVATE_MEDIA_ROOT 必须是绝对路径。')
    for parent in [raw, *raw.parents]:
        _reject_link(parent)
    if create:
        raw.mkdir(mode=0o700, parents=True, exist_ok=True)
    base = raw.resolve(strict=False)
    if base.exists() and not base.is_dir():
        raise ValidationError('私有媒体目录不可用。')
    return base


def _safe_child(base, *parts):
    candidate = base.joinpath(*parts)
    if not candidate.resolve(strict=False).is_relative_to(base):
        raise ValidationError('图片存储路径不安全。')
    current = candidate
    while current != base:
        _reject_link(current)
        current = current.parent
    _reject_link(base)
    return candidate


def attachment_path(attachment, thumbnail=False):
    key = str(attachment.storage_key)
    if not STORAGE_KEY.fullmatch(key) or key[:2] != key[3:5]:
        raise ValidationError('图片存储标识不安全。')
    return _safe_child(_root(), *key.split('/'), 'thumbnail.png' if thumbnail else 'full.png')


def open_attachment_file(attachment, thumbnail=False):
    path = attachment_path(attachment, thumbnail=thumbnail)
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    try:
        descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise Http404('图片暂不可读。')
        return os.fdopen(descriptor, 'rb')
    except OSError:
        raise Http404('图片暂不可读。')


def _write_file(path, data):
    with path.open('xb') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def _remove_new_directory(base, directory):
    if directory is None:
        return
    try:
        directory = _safe_child(base, *directory.relative_to(base).parts)
        for filename in ('full.png', 'thumbnail.png'):
            _safe_child(base, *directory.relative_to(base).parts, filename).unlink(missing_ok=True)
        directory.rmdir()
    except (OSError, ValueError, ValidationError):
        # Never recursively delete unknown content or follow a changed path.
        logger.warning('本次失败的图片文件需要本地维护检查；未删除未知目录。')


def upload_attachment(user, uploaded_file):
    """Independent upload transaction; call before business atomic blocks.

    Durable atomic prevents a later outer rollback leaving a published but unreferenced file.
    Bytes are canonical PNG; sha/quota cover full image and its thumbnail, not source metadata.
    """
    if not getattr(user, 'is_authenticated', False) or not user.pk:
        raise Http404()
    full, thumbnail, width, height = _normalise(uploaded_file)
    digest = hashlib.sha256(full).hexdigest()
    base = _root(create=True)
    stage = published = None
    try:
        with transaction.atomic(durable=True):
            owner = get_user_model().objects.select_for_update().get(pk=user.pk)
            existing = Attachment.objects.filter(owner=owner, sha256=digest).first()
            if existing:
                return existing
            usage = Attachment.objects.filter(owner=owner).aggregate(full=Sum('byte_size'), thumb=Sum('thumbnail_bytes'))
            quota = int(getattr(settings, 'ATTACHMENT_USER_QUOTA_BYTES', 500 * 1024 * 1024))
            if quota <= 0 or (usage['full'] or 0) + (usage['thumb'] or 0) + len(full) + len(thumbnail) > quota:
                raise ValidationError('本地图片空间额度已用完，请联系本机维护者增加额度。')
            key_uuid = uuid.uuid4().hex
            key = f'{key_uuid[:2]}/{key_uuid}'
            shard = _safe_child(base, key_uuid[:2])
            shard.mkdir(mode=0o700, exist_ok=True)
            stage = _safe_child(base, key_uuid[:2], f'.pending-{uuid.uuid4().hex}')
            stage.mkdir(mode=0o700)
            _write_file(_safe_child(base, key_uuid[:2], stage.name, 'full.png'), full)
            _write_file(_safe_child(base, key_uuid[:2], stage.name, 'thumbnail.png'), thumbnail)
            destination = _safe_child(base, *key.split('/'))
            if destination.exists():
                raise ValidationError('图片存储冲突，请重试。')
            stage.rename(destination)
            published, stage = destination, None
            attachment = Attachment(owner=owner, display_name=_display_name(uploaded_file.name),
                width=width, height=height, sha256=digest, storage_key=key,
                byte_size=len(full), thumbnail_bytes=len(thumbnail))
            attachment.full_clean()
            attachment.save()
        return attachment
    except BaseException:
        _remove_new_directory(base, stage)
        _remove_new_directory(base, published)
        raise


def owned_attachment(user, identifier):
    try:
        key = uuid.UUID(str(identifier))
        return Attachment.objects.get(pk=key, owner=user)
    except (Attachment.DoesNotExist, ValueError, TypeError, AttributeError):
        raise Http404()


def _attachment_ids(identifiers):
    if not isinstance(identifiers, (list, tuple)):
        raise ValidationError('图片标识必须是列表。')
    try:
        ids = [uuid.UUID(str(identifier)) for identifier in identifiers]
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('图片标识无效。')
    if len(ids) != len(set(ids)):
        raise ValidationError('同一位置列表不能重复添加图片。')
    return ids


@transaction.atomic
def sync_question_images(user, question, attachment_ids, role=ImageRole.QUESTION):
    if role not in ImageRole.values:
        raise ValidationError('图片用途无效。')
    ids = _attachment_ids(attachment_ids)
    limit = int(getattr(settings, 'ATTACHMENT_MAX_PER_ROLE', 12))
    if len(ids) > limit or not 1 <= limit <= 64:
        raise ValidationError('同一用途的图片过多，请分成多道错题。')
    try:
        course_id = WrongQuestion.objects.filter(pk=question.pk, course__owner=user).values_list('course_id', flat=True).get()
        course = Course.objects.select_for_update().get(pk=course_id, owner=user)
        locked = WrongQuestion.objects.select_for_update().get(pk=question.pk, course=course)
    except (WrongQuestion.DoesNotExist, Course.DoesNotExist):
        raise Http404()
    if course.is_archived or locked.is_archived:
        raise ValidationError('已归档内容只读，请先恢复后再修改图片。')
    owned = {attachment.pk: attachment for attachment in Attachment.objects.filter(pk__in=ids, owner=user)}
    if len(owned) != len(ids):
        raise Http404()
    other_count = locked.image_links.exclude(role=role).count()
    if other_count + len(ids) > int(getattr(settings, 'ATTACHMENT_MAX_PER_QUESTION', 24)):
        raise ValidationError('这道错题的图片过多，请拆分错题。')
    current = list(locked.image_links.filter(role=role).order_by('position'))
    if [link.attachment_id for link in current] == ids:
        return current
    locked.image_links.filter(role=role).delete()
    links = [QuestionImage(question=locked, attachment=owned[identifier], role=role, position=index)
             for index, identifier in enumerate(ids)]
    QuestionImage.objects.bulk_create(links)
    locked.updated_at = timezone.now()
    locked.save(update_fields=['updated_at'])
    question.updated_at = locked.updated_at
    # MySQL does not populate AutoField values for bulk_create; return persisted objects.
    return list(locked.image_links.filter(role=role).order_by('position'))


@transaction.atomic
def snapshot_question_images(question, review_record):
    """Call immediately after a new record is saved, in its enclosing review transaction.

    A separate immutable manifest freezes even an empty image list; replay never appends images.
    """
    try:
        course = Course.objects.select_for_update().get(pk=question.course_id)
        locked = WrongQuestion.objects.select_for_update().get(pk=question.pk, course=course)
        record = ReviewRecord.objects.get(pk=review_record.pk, question=locked)
    except (WrongQuestion.DoesNotExist, Course.DoesNotExist, ReviewRecord.DoesNotExist):
        raise ValidationError('复习记录与错题不匹配。')
    existing = ReviewImageManifest.objects.filter(review=record).first()
    if existing:
        return list(record.image_snapshots.all())
    links = list(locked.image_links.select_related('attachment').all())
    if any(link.attachment.owner_id != course.owner_id for link in links):
        raise ValidationError('错题图片归属不一致，无法保存历史。')
    ReviewImageManifest.objects.create(review=record, image_count=len(links))
    snapshots = [ReviewImageSnapshot(review=record, attachment=link.attachment, role=link.role,
        position=link.position, name_snapshot=link.attachment.display_name,
        width_snapshot=link.attachment.width, height_snapshot=link.attachment.height,
        sha256_snapshot=link.attachment.sha256) for link in links]
    ReviewImageSnapshot.objects.bulk_create(snapshots)
    return list(record.image_snapshots.all())
