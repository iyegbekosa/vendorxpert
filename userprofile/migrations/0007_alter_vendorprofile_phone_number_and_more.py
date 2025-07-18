# Generated by Django 4.2 on 2025-07-12 23:58

from django.db import migrations
import phonenumber_field.modelfields


class Migration(migrations.Migration):

    dependencies = [
        ('userprofile', '0006_vendorplan_remove_vendorprofile_account_number_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='vendorprofile',
            name='phone_number',
            field=phonenumber_field.modelfields.PhoneNumberField(blank=True, max_length=128, null=True, region=None, unique=True),
        ),
        migrations.AlterField(
            model_name='vendorprofile',
            name='whatsapp_number',
            field=phonenumber_field.modelfields.PhoneNumberField(blank=True, max_length=128, null=True, region=None, unique=True),
        ),
    ]
