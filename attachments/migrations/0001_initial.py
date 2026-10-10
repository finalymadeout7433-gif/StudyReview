import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('learning', '0004_explicit_text_validators'),
    ]
    operations = [
        migrations.CreateModel(name='Attachment', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('display_name', models.CharField(max_length=200)),
            ('width', models.PositiveIntegerField()), ('height', models.PositiveIntegerField()),
            ('sha256', models.CharField(max_length=64)),
            ('storage_key', models.CharField(max_length=80, unique=True, editable=False)),
            ('byte_size', models.PositiveBigIntegerField()), ('thumbnail_bytes', models.PositiveIntegerField()),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('owner', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT, related_name='image_attachments')),
        ], options={'ordering': ['created_at', 'pk'],
            'indexes': [models.Index(fields=['owner', 'created_at'], name='attachment_owner_time_idx')],
            'constraints': [models.UniqueConstraint(fields=['owner', 'sha256'], name='attachment_owner_sha_uq'),
                models.CheckConstraint(condition=models.Q(width__gte=1, width__lte=10000, height__gte=1, height__lte=10000), name='attachment_dimensions_valid')]}),
        migrations.CreateModel(name='QuestionImage', fields=[
            ('id', models.BigAutoField(primary_key=True, auto_created=True, serialize=False, verbose_name='ID')),
            ('role', models.CharField(max_length=16, choices=[('question', '题干'), ('original_answer', '原答'), ('correct_answer', '参考答案'), ('error_reason', '错因')], default='question')),
            ('position', models.PositiveSmallIntegerField()),
            ('attachment', models.ForeignKey('attachments.attachment', on_delete=django.db.models.deletion.PROTECT, related_name='question_links')),
            ('question', models.ForeignKey('learning.wrongquestion', on_delete=django.db.models.deletion.PROTECT, related_name='image_links')),
        ], options={'ordering': ['role', 'position', 'pk'], 'constraints': [
            models.UniqueConstraint(fields=['question', 'role', 'position'], name='question_image_position_uq'),
            models.UniqueConstraint(fields=['question', 'role', 'attachment'], name='question_image_attachment_uq'),
            models.CheckConstraint(condition=models.Q(role__in=['question', 'original_answer', 'correct_answer', 'error_reason']), name='question_image_role_valid')]}),
        migrations.CreateModel(name='ReviewImageManifest', fields=[
            ('review', models.OneToOneField('learning.reviewrecord', primary_key=True, serialize=False, on_delete=django.db.models.deletion.PROTECT, related_name='image_manifest')),
            ('image_count', models.PositiveSmallIntegerField()), ('created_at', models.DateTimeField(auto_now_add=True)),
        ]),
        migrations.CreateModel(name='ReviewImageSnapshot', fields=[
            ('id', models.BigAutoField(primary_key=True, auto_created=True, serialize=False, verbose_name='ID')),
            ('role', models.CharField(max_length=16, choices=[('question', '题干'), ('original_answer', '原答'), ('correct_answer', '参考答案'), ('error_reason', '错因')])),
            ('position', models.PositiveSmallIntegerField()), ('name_snapshot', models.CharField(max_length=200)),
            ('width_snapshot', models.PositiveIntegerField()), ('height_snapshot', models.PositiveIntegerField()),
            ('sha256_snapshot', models.CharField(max_length=64)),
            ('attachment', models.ForeignKey('attachments.attachment', on_delete=django.db.models.deletion.PROTECT, related_name='review_snapshots')),
            ('review', models.ForeignKey('learning.reviewrecord', on_delete=django.db.models.deletion.PROTECT, related_name='image_snapshots')),
        ], options={'ordering': ['role', 'position', 'pk'], 'constraints': [
            models.UniqueConstraint(fields=['review', 'role', 'position'], name='review_image_position_uq'),
            models.UniqueConstraint(fields=['review', 'role', 'attachment'], name='review_image_attachment_uq'),
            models.CheckConstraint(condition=models.Q(role__in=['question', 'original_answer', 'correct_answer', 'error_reason']), name='review_image_role_valid')]}),
    ]
