from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('learning', '0004_explicit_text_validators')]
    operations = [migrations.AddField(model_name='reviewrecord', name='is_example',
        field=models.BooleanField(default=False, verbose_name='示例演练记录'))]
