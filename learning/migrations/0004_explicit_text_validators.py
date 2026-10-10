from django.core.validators import MaxLengthValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('learning', '0003_text_validation_lengths')]
    operations = [
        migrations.AlterField(model_name='wrongquestion', name='content', field=models.TextField(max_length=20000, validators=[MaxLengthValidator(20000)], verbose_name='题目正文')),
        migrations.AlterField(model_name='wrongquestion', name='original_answer', field=models.TextField(max_length=20000, validators=[MaxLengthValidator(20000)], verbose_name='原答案')),
        migrations.AlterField(model_name='wrongquestion', name='correct_answer', field=models.TextField(max_length=20000, validators=[MaxLengthValidator(20000)], verbose_name='参考答案')),
        migrations.AlterField(model_name='wrongquestion', name='error_reason', field=models.TextField(max_length=20000, validators=[MaxLengthValidator(20000)], verbose_name='错误原因')),
        migrations.AlterField(model_name='reviewrecord', name='answer', field=models.TextField(max_length=20000, validators=[MaxLengthValidator(20000)], verbose_name='本次作答')),
        migrations.AlterField(model_name='reviewrecord', name='note', field=models.TextField(blank=True, max_length=5000, validators=[MaxLengthValidator(5000)], verbose_name='备注')),
    ]
