"""Pinned, deterministic FSRS adapter. No I/O, replay, optimizer or training."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone as datetime_timezone
from importlib.metadata import PackageNotFoundError, version
import json
import math
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError

ALGORITHM = 'fsrs'
ALGORITHM_VERSION = '6.3.2'
CONFIG_VERSION = 'shanghai-daily-v1'
SHANGHAI = ZoneInfo('Asia/Shanghai')
UTC = datetime_timezone.utc
RATING_DESCRIPTIONS = {
    'again': '未能独立答对，或看答案后才会',
    'hard': '独立答对，但回忆费力',
    'good': '独立正确作答',
}
CARD_KEYS = {'card_id', 'state', 'step', 'stability', 'difficulty', 'due', 'last_review'}


class ScheduleStateError(ValidationError):
    """Corrupt or unsupported state must be repaired explicitly, never reset."""

    def __init__(self, message='复习算法状态无效，请保留数据并联系维护者；本次未保存。'):
        super().__init__(message, code='schedule_state_invalid')


def utc_datetime(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError('复习时间必须包含时区。', code='schedule_time_invalid')
    return value.astimezone(UTC)


def _stored_datetime(value):
    if not isinstance(value, str):
        raise ScheduleStateError()
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ScheduleStateError() from exc
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ScheduleStateError('复习算法状态的时间必须为 UTC；本次未保存。')
    return result.astimezone(UTC)


def _positive_number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value > 0)


def validate_card_state(payload, card_id=None):
    """Validate before Card.from_dict, which otherwise coerces invalid values."""
    if not isinstance(payload, dict) or set(payload) != CARD_KEYS:
        raise ScheduleStateError()
    if type(payload['card_id']) is not int or payload['card_id'] <= 0:
        raise ScheduleStateError()
    if card_id is not None and payload['card_id'] != card_id:
        raise ScheduleStateError('复习算法状态与题目不匹配；本次未保存。')
    if type(payload['state']) is not int or payload['state'] not in (1, 2):
        raise ScheduleStateError('当前日级算法配置不支持此学习状态；本次未保存。')
    due = _stored_datetime(payload['due'])
    last_review = payload['last_review']
    if payload['state'] == 1:
        if (type(payload['step']) is not int or payload['step'] != 0
                or payload['stability'] is not None or payload['difficulty'] is not None
                or last_review is not None):
            raise ScheduleStateError()
    else:
        if (payload['step'] is not None or not _positive_number(payload['stability'])
                or not _positive_number(payload['difficulty'])
                or not 1 <= payload['difficulty'] <= 10 or last_review is None):
            raise ScheduleStateError()
        if due <= _stored_datetime(last_review):
            raise ScheduleStateError()
    return deepcopy(payload)


def make_scheduler():
    try:
        installed = version('fsrs')
    except PackageNotFoundError as exc:
        raise ScheduleStateError('智能复习依赖未安装；请按固定依赖说明配置，勿重置数据。') from exc
    if installed != ALGORITHM_VERSION:
        raise ScheduleStateError('智能复习依赖版本不匹配；需要 fsrs 6.3.2，本次未保存。')
    from fsrs import Scheduler
    scheduler = Scheduler(desired_retention=0.9, learning_steps=(), relearning_steps=(),
                          enable_fuzzing=False)
    if len(scheduler.parameters) != 21:
        raise ScheduleStateError('智能复习参数数量不匹配；本次未保存。')
    return scheduler


def scheduler_config():
    return make_scheduler().to_dict()


def validate_metadata(algorithm, algorithm_version, config_version, config_snapshot):
    try:
        snapshot_json = json.dumps(config_snapshot, sort_keys=True, allow_nan=False)
        current_json = json.dumps(scheduler_config(), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ScheduleStateError() from exc
    if (algorithm != ALGORITHM or algorithm_version != ALGORITHM_VERSION
            or config_version != CONFIG_VERSION or snapshot_json != current_json):
        raise ScheduleStateError('复习算法或配置版本不匹配；请先执行明确的数据迁移，本次未保存。')


def initial_card(card_id, reviewed_at):
    if type(card_id) is not int or card_id <= 0:
        raise ValidationError('请先保存题目。', code='schedule_question_unsaved')
    make_scheduler()
    from fsrs import Card
    return Card(card_id=card_id, due=utc_datetime(reviewed_at)).to_dict()


@dataclass(frozen=True)
class EngineResult:
    before_state: dict
    after_state: dict
    review_log: dict
    due_utc: datetime
    due_date: date
    reviewed_at: datetime
    config_snapshot: dict


def calculate(card_state, card_id, rating, reviewed_at):
    scheduler = make_scheduler()
    from fsrs import Card, Rating
    reviewed_at = utc_datetime(reviewed_at)
    mapping = {'again': Rating.Again, 'hard': Rating.Hard, 'good': Rating.Good}
    if rating not in mapping:
        raise ValidationError({'rating': '请选择未能独立答对、独立答对但费力或独立答对。'})
    before = validate_card_state(card_state, card_id)
    if before['last_review'] is not None and reviewed_at < _stored_datetime(before['last_review']):
        raise ValidationError('复习时间早于已保存的复习时间，本次未保存。', code='schedule_time_reversed')
    try:
        card, review_log = scheduler.review_card(
            Card.from_dict(before), mapping[rating], review_datetime=reviewed_at,
            review_duration=None)
    except (ValueError, OverflowError, ArithmeticError, AssertionError) as exc:
        raise ScheduleStateError('复习算法计算失败；原数据已保留，本次未保存。') from exc
    after = validate_card_state(card.to_dict(), card_id)
    due_utc = _stored_datetime(after['due'])
    review_date = reviewed_at.astimezone(SHANGHAI).date()
    # Daily workflow: retain exact FSRS due separately, never schedule for today.
    due_date = max(due_utc.astimezone(SHANGHAI).date(), review_date + timedelta(days=1))
    return EngineResult(before, after, review_log.to_dict(), due_utc, due_date,
                        reviewed_at, scheduler.to_dict())
