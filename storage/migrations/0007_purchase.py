from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('storage', '0006_userprofile_metrics'),
    ]

    operations = [
        migrations.CreateModel(
            name='Purchase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.PositiveIntegerField(default=0)),
                ('payment_provider', models.CharField(default='razorpay', max_length=32)),
                ('provider_order_id', models.CharField(blank=True, default='', max_length=128)),
                ('provider_payment_id', models.CharField(blank=True, default='', max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='purchases', to='storage.noteitem')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='purchases', to='auth.user')),
            ],
            options={
                'ordering': ['-created_at'],
                'unique_together': {('user', 'item')},
            },
        ),
    ]
