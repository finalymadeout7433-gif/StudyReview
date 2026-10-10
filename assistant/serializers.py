from django.urls import reverse
from django.utils import timezone
from attachments.models import Attachment
import uuid
from .services import confirmation_token


def attachment_data(image):
    return {'id': str(image.pk), 'display_name': image.display_name,
        'width': image.width, 'height': image.height, 'byte_size': image.byte_size,
        'content_type': 'image/png',
        'url': reverse('attachments:media', kwargs={'attachment_id': image.pk}),
        'thumbnail_url': reverse('attachments:thumbnail', kwargs={'attachment_id': image.pk})}


def session_data(session):
    return {'id': str(session.pk), 'title': session.title,
        'created_at': session.created_at.isoformat(), 'updated_at': session.updated_at.isoformat()}


def message_data(message):
    return {'id': str(message.pk), 'role': message.role, 'text': message.text,
        'status': message.status, 'submission_key': str(message.submission_key),
        'reply_to': str(message.reply_to_id) if message.reply_to_id else None,
        'created_at': message.created_at.isoformat(),
        'attachments': [attachment_data(link.attachment) for link in message.image_links.all()]}


def draft_data(draft):
    images = {}
    for name, snapshot in (('before', draft.before_snapshot), ('after', draft.after_snapshot)):
        identifiers = []
        for value in snapshot.get('attachment_ids', [])[:24]:
            try:
                identifiers.append(uuid.UUID(str(value)))
            except (ValueError, TypeError, AttributeError):
                continue
        owned = {image.pk: image for image in Attachment.objects.filter(owner_id=draft.owner_id, pk__in=identifiers)}
        images[name] = [attachment_data(owned[identifier]) for identifier in identifiers if identifier in owned]
    return {'id': str(draft.pk), 'session_id': str(draft.session_id),
        'source_message_id': str(draft.source_message_id) if draft.source_message_id else None,
        'operation': draft.operation, 'title': draft.title, 'payload': draft.payload,
        'before': draft.before_snapshot, 'after': draft.after_snapshot, 'images': images,
        'target_id': draft.target_id, 'status': draft.status,
        'created_at': draft.created_at.isoformat(), 'expires_at': draft.expires_at.isoformat(),
        'expired': draft.status == 'pending' and draft.expires_at <= timezone.now(),
        'cancelled': draft.status == 'pending' and draft.expires_at <= draft.created_at,
        'confirmation_token': confirmation_token(draft),
        'applied_at': draft.applied_at.isoformat() if draft.applied_at else None,
        'applied_object_id': draft.applied_object_id}
