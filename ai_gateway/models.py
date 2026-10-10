"""Accounting metadata only: no API key, prompt, image bytes or response text."""
import uuid
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Q


class Account(models.Model):
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ai_budget_account')
    budget_cny = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal('0'))
    spent_cny = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal('0'))
    reserved_cny = models.DecimalField(max_digits=14, decimal_places=6, default=Decimal('0'))
    revision = models.PositiveBigIntegerField(default=1)
    key_reference = models.UUIDField(null=True, blank=True, editable=False)
    enabled = models.BooleanField(default=False)
    consent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(budget_cny__gte=0, spent_cny__gte=0, reserved_cny__gte=0), name='ai_account_amounts_nonnegative'),
            models.CheckConstraint(condition=Q(enabled=False) | Q(key_reference__isnull=False, consent_at__isnull=False, budget_cny__gt=0), name='ai_account_enabled_consent'),
        ]


class RequestLedger(models.Model):
    class State(models.TextChoices):
        RESERVED = 'reserved', '已预留'
        SUCCEEDED = 'succeeded', '已结算'
        FAILED = 'failed', '已失败'
        UNCERTAIN = 'uncertain', '结果或费用未确认'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_id = models.UUIDField(unique=True, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ai_request_ledgers')
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='requests')
    request_hash = models.CharField(max_length=64)
    state = models.CharField(max_length=9, choices=State.choices, default=State.RESERVED)
    dispatched = models.BooleanField(default=False)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    pricing_snapshot = models.JSONField()
    input_token_ceiling = models.PositiveIntegerField()
    output_token_ceiling = models.PositiveIntegerField()
    reserved_cny = models.DecimalField(max_digits=14, decimal_places=6)
    held_cny = models.DecimalField(max_digits=14, decimal_places=6)
    estimated_cost_cny_peak = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    usage = models.JSONField(null=True, blank=True)
    failure_code = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['owner', 'state', 'created_at'], name='ai_ledger_owner_state_time')]
        constraints = [
            models.CheckConstraint(condition=Q(state__in=['reserved', 'succeeded', 'failed', 'uncertain']), name='ai_ledger_state_valid'),
            models.CheckConstraint(condition=Q(reserved_cny__gte=0, held_cny__gte=0) & (Q(estimated_cost_cny_peak__isnull=True) | Q(estimated_cost_cny_peak__gte=0)), name='ai_ledger_amounts_nonnegative'),
            models.CheckConstraint(condition=(Q(dispatched=False, dispatched_at__isnull=True) | Q(dispatched=True, dispatched_at__isnull=False)), name='ai_ledger_dispatch_consistent'),
        ]


class MessageContext(models.Model):
    """Retain the human-selected scope locally; signed version never goes to AI."""
    message = models.OneToOneField('assistant.Message', on_delete=models.PROTECT, primary_key=True, related_name='chosen_context')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    selected_history_ids = models.JSONField(default=list, blank=True)
    selected_target_snapshot = models.JSONField(default=dict, blank=True)
    selected_course_snapshot = models.JSONField(default=dict, blank=True)
    expected_version = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
