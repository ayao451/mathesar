# Generated by Django 3.1.14 on 2022-12-08 20:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mathesar', '0009_auto_20221123_1423'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='password_change_needed',
            field=models.BooleanField(default=True),
        ),
    ]