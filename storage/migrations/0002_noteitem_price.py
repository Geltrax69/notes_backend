from django.db import migrations, models
import django.core.validators


class Migration(migrations.Migration):

    dependencies = [
        ('storage', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='noteitem',
            name='price',
            field=models.PositiveIntegerField(default=499, validators=[django.core.validators.MinValueValidator(0)]),
        ),
    ]
