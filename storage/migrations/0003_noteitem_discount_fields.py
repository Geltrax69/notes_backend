from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('storage', '0002_noteitem_price'),
    ]

    operations = [
        migrations.AddField(
            model_name='noteitem',
            name='discount_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='noteitem',
            name='discount_percent',
            field=models.PositiveSmallIntegerField(default=0, validators=[django.core.validators.MinValueValidator(0)]),
        ),
    ]
