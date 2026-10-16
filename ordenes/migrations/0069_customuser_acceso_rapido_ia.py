from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ordenes', '0068_nomina_basico_meta_manual')]
    operations = [
        migrations.AddField(
            model_name='customuser', name='acceso_rapido_ia',
            field=models.BooleanField(default=False),
        ),
    ]
