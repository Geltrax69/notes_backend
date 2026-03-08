from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='NoteItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('item_type', models.CharField(choices=[('folder', 'Folder'), ('file', 'File')], max_length=10)),
                ('s3_key', models.CharField(blank=True, default='', max_length=1024)),
                ('content_type', models.CharField(blank=True, default='', max_length=120)),
                ('size', models.BigIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='children', to='storage.noteitem')),
            ],
            options={'ordering': ['item_type', 'name', 'id']},
        ),
    ]
