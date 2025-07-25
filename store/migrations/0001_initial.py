# Generated by Django 4.2 on 2025-02-07 15:15

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('userprofile', '0002_alter_userprofile_is_active'),
    ]

    operations = [
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=50)),
                ('slug', models.SlugField()),
            ],
            options={
                'verbose_name_plural': 'Categories',
            },
        ),
        migrations.CreateModel(
            name='Product',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=50)),
                ('slug', models.SlugField()),
                ('description', models.TextField()),
                ('price', models.BigIntegerField()),
                ('created_at', models.DateTimeField(auto_now=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('product_image', models.ImageField(blank=True, null=True, upload_to='uploads/product_image/')),
                ('thumbnail', models.ImageField(blank=True, null=True, upload_to='uploads/product_image/thumbnail')),
                ('status', models.CharField(choices=[('draft', 'draft'), ('waiting approval', 'waiting approval'), ('active', 'active'), ('deleted', 'deleted')], default='active', max_length=50)),
                ('stock', models.CharField(choices=[('in stock', 'In stock'), ('out of stock', 'Out of stock')], default='in stock', max_length=50)),
                ('featured', models.BooleanField(default=False)),
                ('category', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='product', to='store.category')),
                ('vendor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='product', to='userprofile.vendorprofile')),
            ],
            options={
                'ordering': ('-created_at',),
            },
        ),
    ]
