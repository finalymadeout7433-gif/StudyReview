from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('learning', '0013_course_owner_guard')]
    operations = [migrations.AddIndex(
        model_name='reviewrecord',
        index=models.Index(fields=['question', 'reviewed_at', 'rating', 'is_example'],
                           name='review_question_time_idx'),
    )]
