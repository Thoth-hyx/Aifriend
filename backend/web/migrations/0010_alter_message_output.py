from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('web', '0009_ai_group_im')]

    operations = [
        migrations.AlterField(model_name='message', name='output', field=models.TextField()),
    ]
