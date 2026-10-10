"""A fail-closed provider boundary. This module makes no network calls.

The gateway requires manually configured destination/data/budget authorization.
Synthetic implementations are injected into service tests; they are not selectable
from HTTP, settings, chat text, attachments, or provider-produced content.
"""
from dataclasses import dataclass
from typing import Protocol


class ProviderNotConnected(Exception):
    pass


@dataclass(frozen=True)
class ChatContext:
    instructions: str
    messages: tuple
    images: tuple
    retained_messages: int
    omitted_messages: int
    selected_target_snapshot: dict | None = None
    selected_course_snapshot: dict | None = None


@dataclass(frozen=True)
class ProviderResult:
    text: str
    drafts: tuple = ()


class Provider(Protocol):
    connected: bool

    def respond(self, context: ChatContext) -> ProviderResult: ...


class DisconnectedProvider:
    connected = False

    def respond(self, context):
        raise ProviderNotConnected('尚未连接 AI 服务。')


def get_provider(user=None, submission_key=None):
    # Default is disconnected; metadata only. No key discovery/decryption here.
    if user is None or submission_key is None:
        return DisconnectedProvider()
    from ai_gateway.services import gateway_provider
    return gateway_provider(user, submission_key)


def provider_status(user=None):
    result = {
        'connected': False,
        'state': 'not_connected',
        'label': 'AI 尚未连接',
        'detail': '文字和图片只保存在本机；目前不会发送给任何 AI 服务，也不会生成 AI 答案。',
        'local_history': True,
        'automatic_history_deletion': False,
        'history_is_permanent_ai_memory': False,
        'context_limits': {'max_messages': 20, 'max_characters': 12000, 'max_images': 4, 'max_image_bytes': 8388608},
    }
    if user is not None:
        from ai_gateway.services import configuration_status
        result.update(configuration_status(user))
    return result
