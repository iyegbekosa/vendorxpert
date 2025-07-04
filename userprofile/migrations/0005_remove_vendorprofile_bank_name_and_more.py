# Generated by Django 4.2 on 2025-06-25 12:24

from django.db import migrations, models
import phonenumber_field.modelfields


class Migration(migrations.Migration):

    dependencies = [
        ('userprofile', '0004_vendorprofile_account_number_vendorprofile_bank_name'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='vendorprofile',
            name='bank_name',
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='bank_code',
            field=models.CharField(choices=[('044', 'Access Bank'), ('058', 'GTBank'), ('011', 'First Bank'), ('232', 'Sterling Bank'), ('033', 'UBA'), ('063', 'Access Bank (Diamond)')], max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='vendorprofile',
            name='subaccount_code',
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name='vendorprofile',
            name='phone_number',
            field=phonenumber_field.modelfields.PhoneNumberField(default='08031234567', max_length=128, region=None, unique=True),
        ),
        migrations.AlterField(
            model_name='vendorprofile',
            name='whatsapp_number',
            field=phonenumber_field.modelfields.PhoneNumberField(default='08031234567', max_length=128, region=None, unique=True),
        ),
    ]
