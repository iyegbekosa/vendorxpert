# Generated by Django 4.2 on 2025-06-24 21:30

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0005_order_orderitem'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='order',
            name='hostel',
        ),
        migrations.RemoveField(
            model_name='order',
            name='room_no',
        ),
        migrations.AddField(
            model_name='order',
            name='pickup_location',
            field=models.CharField(choices=[('admin', 'admin'), ('faculty', 'faculty'), ('tetfund', 'tetfund'), ('hall_1', 'hall_1'), ('hall_2', 'hall_2'), ('hall_3', 'hall_3'), ('hall_4', 'hall_4'), ('hall_5', 'hall_5'), ('hall_6', 'hall_6'), ('hall_7', 'hall_7'), ('hall_8', 'hall_8')], default='admin', max_length=50),
        ),
    ]
