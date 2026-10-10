from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('scheduling', '0002_event_guards')]
    operations = [
        migrations.RemoveConstraint(model_name='scheduleevent', name='schedule_override_consistent'),
        migrations.AddConstraint(model_name='scheduleevent', constraint=models.CheckConstraint(
            condition=(models.Q(manual_override_date__isnull=True,
                                applied_date=models.F('suggested_date'))
                       | models.Q(manual_override_date__isnull=False,
                                  manual_override_date=models.F('applied_date'))),
            name='schedule_override_consistent')),
    ]
