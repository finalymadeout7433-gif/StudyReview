"""Fail-closed manual configuration, database budget reservations and provider bridge."""
import hashlib
from decimal import Decimal, InvalidOperation
import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from assistant.deepseek_provider import (BudgetReservation, DeepSeekConfiguration,
    DeepSeekProvider, PeakPricing, PreparedImage, ProviderError, ProviderRequest,
    prepare_request, RequestQuote)
from assistant.provider_security import SecretProtectionError, validate_api_key
from assistant.providers import DisconnectedProvider
from attachments.services import owned_attachment, open_attachment_file
from .models import Account, RequestLedger
from . import key_store

ZERO = Decimal('0')
CONFIG_FIELDS = {'api_key', 'budget_cny', 'confirm_local_storage', 'confirm_budget', 'confirm_destination', 'enable'}
SAFE_FAILURE_CODES = frozenset({
    'request_timeout', 'connection_lost', 'invalid_response', 'invalid_usage', 'usage_exceeded_bound',
    'unusable_answer', 'authentication_failed', 'provider_balance_insufficient', 'provider_rate_limited',
    'provider_http_error', 'response_too_large', 'ledger_write_failed', 'configuration_changed',
    'not_connected', 'budget_exhausted', 'request_already_dispatched', 'key_not_configured',
    'invalid_image', 'invalid_context', 'invalid_request', 'invalid_reservation', 'provider_failure',
})


def _budget(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 20:
        raise ValidationError('预算必须为明确填写的人民币金额文字。')
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValidationError('请填写有效人民币预算。') from None
    if not result.is_finite() or result < Decimal('0.01') or result > Decimal('1000') or result != result.quantize(Decimal('0.01')):
        raise ValidationError('本地预算须为 0.01 至 1000.00 元，最多两位小数。')
    return result


@sensitive_variables('data', 'api_key')
def configure(user, data):
    if not isinstance(data, dict) or set(data) != CONFIG_FIELDS:
        raise ValidationError('请完整填写密钥、预算并逐项确认。')
    if any(data[field] is not True for field in ('confirm_local_storage', 'confirm_budget', 'confirm_destination', 'enable')):
        raise ValidationError('必须本人明确确认本机保存、预算上限和发送目的地后才能启用。')
    try:
        api_key = validate_api_key(data['api_key'])
    except SecretProtectionError:
        raise ValidationError('请本人手动填写有效的 DeepSeek API 密钥。') from None
    budget = _budget(data['budget_cny'])
    reference = None
    try:
        with transaction.atomic(durable=True):
            get_user_model().objects.select_for_update().get(pk=user.pk)
            account, _ = Account.objects.select_for_update().get_or_create(owner=user)
            if _billing_review_required(account):
                raise ValidationError('用量曾超过安全上限，需核对服务商账单与本地不确定账本；当前不能重新启用，额度不会自动清零。')
            if budget < account.spent_cny + account.reserved_cny:
                raise ValidationError('预算不能低于已计入的估算费用和仍保留的额度。')
            reference = key_store.write_new(api_key)
            account.key_reference = reference
            account.budget_cny = budget
            account.enabled = True
            account.consent_at = timezone.now()
            account.revision += 1
            account.full_clean()
            account.save()
            safe_status = configuration_status(user)
    except BaseException:
        if reference is not None:
            # Clean only ciphertext created by this failed action, never old data.
            try:
                key_store.remove_new(reference)
            except (OSError, SecretProtectionError):
                pass
        raise
    return safe_status


@transaction.atomic
def disable(user):
    account = Account.objects.select_for_update().filter(owner=user).first()
    if account:
        account.enabled = False
        account.revision += 1
        account.save(update_fields=['enabled', 'revision', 'updated_at'])
    return configuration_status(user)


def _billing_review_required(account):
    return account.requests.filter(state='uncertain', failure_code='usage_exceeded_bound').exists()


def configuration_status(user):
    """Metadata only, no decryption or key/file-path disclosure."""
    account = Account.objects.filter(owner=user).first()
    status = {'configured': False, 'connected': False, 'state': 'not_connected',
        'label': 'AI 尚未连接', 'enabled': False, 'key_stored': False,
        'budget_cny': None, 'spent_cny': '0.000000', 'reserved_cny': '0.000000',
        'remaining_cny': '0.000000', 'uncertain_requests': 0,
        'provider': 'DeepSeek', 'model': 'deepseek-flash', 'destination': 'https://api.deepseek.com',
        'cost_basis': '本地按峰值价格保守估算，非服务商账单',
        'online_connection_verified': False,
        'detail': '尚未配置；文字和图片只在本机保存，不会发送给 AI。'}
    if account is None:
        return status
    complete = bool(account.key_reference and account.consent_at and account.budget_cny > 0)
    remaining = max(ZERO, account.budget_cny - account.spent_cny - account.reserved_cny)
    review_required = _billing_review_required(account)
    enabled = bool(account.enabled and complete and not review_required)
    status.update({'configured': complete, 'enabled': account.enabled, 'key_stored': bool(account.key_reference),
        'budget_cny': str(account.budget_cny), 'spent_cny': str(account.spent_cny),
        'reserved_cny': str(account.reserved_cny), 'remaining_cny': str(remaining),
        'uncertain_requests': account.requests.filter(state='uncertain').count(),
        'connected': enabled and remaining > 0, 'billing_review_required': review_required})
    if review_required:
        status.update(state='billing_review_required', label='AI 已停用 · 需核对账单', enabled=False,
            detail='返回用量超过预留安全上限，已停止后续调用；不确定账本及占用额度保留，请本人核对服务商账单，不会自动清零或重新启用。')
    elif enabled and remaining > 0:
        status.update(state='configured', label='DeepSeek 已配置',
            detail='仅主动发送的消息、图片和选定上下文会发送到 DeepSeek；按本机预算预留额度，服务尚未在线验证。')
    elif enabled:
        status.update(state='budget_exhausted', label='AI 预算不可用', detail='本机预算已使用或预留完毕；本次不会发送资料。')
    elif complete:
        status.update(state='disabled', label='AI 已停用', detail='历史和预算账本保留，当前不发送资料。')
    return status


def _pricing_snapshot(pricing):
    return {'version': pricing.version, 'currency': 'CNY', 'cache_miss_per_million': str(pricing.cache_miss),
        'cache_hit_per_million': str(pricing.cache_hit), 'output_per_million': str(pricing.output),
        'basis': 'peak_upper_estimate_not_provider_invoice'}


@transaction.atomic
def reserve(user, quote, pricing, *, key_reference):
    """A unique committed ledger and held amount precede every network attempt."""
    if not isinstance(quote, RequestQuote):
        raise ProviderError('invalid_reservation', '请求预留无效，未发送资料。')
    account = Account.objects.select_for_update().filter(owner=user).first()
    if account and _billing_review_required(account):
        raise ProviderError('usage_exceeded_bound', '用量曾超过安全上限，需核对账单；后续资料未发送。')
    if not account or not account.enabled or not account.consent_at or account.key_reference != key_reference:
        raise ProviderError('configuration_changed', 'AI 配置已变化，未发送本次资料。')
    existing = RequestLedger.objects.filter(request_id=quote.request_id).first()
    if existing:
        # No replay returns a reusable reservation; even pre-dispatch crashes hold.
        uncertain = existing.owner_id == user.pk and (existing.state == 'uncertain' or (existing.state == 'reserved' and existing.dispatched))
        raise ProviderError('request_already_dispatched', '该请求已经登记，不会自动再次发送。', outcome_uncertain=uncertain)
    reservation = BudgetReservation.reserve(quote, approved_limit_cny=account.budget_cny,
        spent_cny=account.spent_cny, outstanding_cny=account.reserved_cny, pricing=pricing)
    ledger = RequestLedger(owner=user, account=account, request_id=quote.request_id,
        request_hash=quote.request_hash, input_token_ceiling=quote.input_token_ceiling,
        output_token_ceiling=quote.output_token_ceiling, pricing_snapshot=_pricing_snapshot(pricing),
        reserved_cny=reservation.reserved_cny, held_cny=reservation.reserved_cny)
    ledger.full_clean()
    ledger.save()
    account.reserved_cny += reservation.reserved_cny
    account.revision += 1
    account.save(update_fields=['reserved_cny', 'revision', 'updated_at'])
    return reservation


@transaction.atomic
def persist_state(user, reservation, *, key_reference):
    """Account->ledger lock order; dispatch must commit before socket I/O."""
    account = Account.objects.select_for_update().filter(owner=user).first()
    if account is None:
        raise ProviderError('ledger_write_failed', '本地额度账本暂不可用，未自动重试。')
    ledger = RequestLedger.objects.select_for_update().filter(owner=user, account=account, request_id=reservation.request_id).first()
    if not ledger or ledger.request_hash != reservation.request_hash or ledger.reserved_cny != reservation.reserved_cny or ledger.pricing_snapshot != _pricing_snapshot(reservation.pricing):
        raise ProviderError('ledger_write_failed', '本地额度账本不一致，未自动重试。')
    if reservation.state == 'reserved' and reservation.dispatched:
        if ledger.state != 'reserved' or ledger.dispatched:
            raise ProviderError('request_already_dispatched', '此请求已登记发送，不会重复发送。', outcome_uncertain=ledger.state == 'uncertain')
        if not account.enabled or not account.consent_at or account.key_reference != key_reference or _billing_review_required(account):
            raise ProviderError('configuration_changed', '配置已变化，本次资料未发送。')
        ledger.dispatched = True
        ledger.dispatched_at = timezone.now()
        ledger.save(update_fields=['dispatched', 'dispatched_at', 'updated_at'])
        return
    if reservation.state not in ('succeeded', 'failed', 'uncertain'):
        raise ProviderError('ledger_write_failed', '请求结算状态无效，额度暂时保留。')
    metadata = reservation.ledger_metadata()
    failure = reservation.failure_code if reservation.failure_code in SAFE_FAILURE_CODES else ('provider_failure' if reservation.failure_code else '')
    estimated = reservation.actual_cost_cny_peak
    if ledger.state in ('succeeded', 'failed', 'uncertain'):
        if (ledger.state == reservation.state and ledger.estimated_cost_cny_peak == estimated
                and ledger.failure_code == failure and ledger.usage == metadata['usage']):
            return
        raise ProviderError('ledger_write_failed', '请求已经结算，不会再次计费。', outcome_uncertain=ledger.state == 'uncertain')
    if reservation.state in ('succeeded', 'uncertain') and not ledger.dispatched:
        raise ProviderError('ledger_write_failed', '请求缺少持久发送标记，额度暂时保留。')
    new_hold = reservation.committed_cny if reservation.state == 'uncertain' else ZERO
    if account.reserved_cny < ledger.held_cny:
        raise ProviderError('ledger_write_failed', '额度账本不一致，暂时保留。')
    account.reserved_cny = account.reserved_cny - ledger.held_cny + new_hold
    if reservation.state in ('succeeded', 'failed') and estimated is not None:
        account.spent_cny += estimated
    if reservation.state == 'uncertain' and failure == 'usage_exceeded_bound':
        account.enabled = False
    account.revision += 1
    account.save(update_fields=['spent_cny', 'reserved_cny', 'enabled', 'revision', 'updated_at'])
    ledger.state = reservation.state
    ledger.held_cny = new_hold
    ledger.estimated_cost_cny_peak = estimated
    ledger.usage = metadata['usage']
    ledger.failure_code = failure
    ledger.settled_at = timezone.now()
    ledger.full_clean()
    ledger.save(update_fields=['state', 'held_cny', 'estimated_cost_cny_peak', 'usage', 'failure_code', 'settled_at', 'updated_at'])


def _image(user, identifier):
    image = owned_attachment(user, identifier)
    if image.byte_size > 8 * 1024 * 1024:
        raise ProviderError('invalid_image', '主动选择的图片过大，未发送本次资料。')
    with open_attachment_file(image) as source:
        data = source.read(8 * 1024 * 1024 + 1)
    if len(data) != image.byte_size or hashlib.sha256(data).hexdigest() != image.sha256:
        raise ProviderError('invalid_image', '本机图片完整性检查未通过，未发送本次资料。')
    prepared = PreparedImage(data, 'image/png', image.width, image.height)
    prepared.validate()
    return prepared


class GatewayProvider:
    """One human submission UUID -> one durable reservation -> at most one send."""
    def __init__(self, user, submission_key, *, transport=None):
        self.user = user
        self.request_id = uuid.UUID(str(submission_key))
        # Only test/service injection can supply a synthetic transport, never HTTP.
        self.transport = transport

    @property
    def connected(self):
        return configuration_status(self.user)['connected']

    @sensitive_variables('api_key', 'configuration')
    def respond(self, context):
        if not configuration_status(self.user)['connected']:
            raise ProviderError('not_connected', 'AI 尚未连接或需核对账单，未发送资料。')
        account = Account.objects.filter(owner=self.user).first()
        if not account or not account.enabled or not account.key_reference or not account.consent_at or account.budget_cny <= 0:
            raise ProviderError('not_connected', 'AI 尚未配置或已停用，未发送资料。')
        key_reference = account.key_reference
        try:
            api_key = key_store.read_configured(key_reference)
        except SecretProtectionError:
            raise ProviderError('key_not_configured', '当前本机密钥无法读取，请本人重新配置；未发送资料。') from None
        configuration = DeepSeekConfiguration(api_key=api_key, enabled=True, data_transfer_approved=True, approved_budget_cny=account.budget_cny)
        configuration.validate()
        images = tuple(_image(self.user, item['id']) for item in context.images)
        request = ProviderRequest(self.request_id, context.instructions, context.messages, images,
            selected_target_snapshot=getattr(context, 'selected_target_snapshot', None),
            selected_course_snapshot=getattr(context, 'selected_course_snapshot', None))
        pricing = PeakPricing()
        prepared = prepare_request(request, pricing)
        reservation = reserve(self.user, prepared.quote, pricing, key_reference=key_reference)
        adapter = DeepSeekProvider(configuration, pricing=pricing, transport=self.transport)
        try:
            result = adapter.complete(request, reservation,
                before_dispatch=lambda value: persist_state(self.user, value, key_reference=key_reference))
        except ProviderError:
            try:
                persist_state(self.user, reservation, key_reference=key_reference)
            except Exception:
                raise ProviderError('ledger_write_failed', '结算未确认，预留额度保留；未自动重试。', outcome_uncertain=reservation.dispatched) from None
            raise
        try:
            persist_state(self.user, reservation, key_reference=key_reference)
        except Exception:
            raise ProviderError('ledger_write_failed', '结算未确认，预留额度保留；未自动重试。', outcome_uncertain=True) from None
        return result.result


def gateway_provider(user, submission_key):
    if user is None or submission_key is None:
        return DisconnectedProvider()
    status = configuration_status(user)
    if not status['connected']:
        provider = DisconnectedProvider()
        if status['state'] == 'budget_exhausted':
            provider.notice = '消息及图片已在本机保存。本机 AI 预算已使用或预留完毕，本次没有发送资料，也没有生成 AI 回答。'
        elif status['state'] == 'disabled':
            provider.notice = '消息及图片已在本机保存。AI 已停用，本次没有发送资料，也没有生成 AI 回答。'
        elif status['state'] == 'billing_review_required':
            provider.notice = '消息及图片已在本机保存。AI 因超界用量停用，需本人核对账单；不确定账本和额度保留，本次未发送资料。'
        return provider
    return GatewayProvider(user, submission_key)
