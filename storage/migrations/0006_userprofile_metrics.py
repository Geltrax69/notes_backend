from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('storage', '0004_userprofile'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='login_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='purchased_notes_count',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
