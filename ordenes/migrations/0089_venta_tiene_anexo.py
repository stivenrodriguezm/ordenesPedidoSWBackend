from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('ordenes', '0087_linea_venta_tipo_bold'),
    ]

    operations = [
        migrations.AddField(
            model_name='venta',
            name='tiene_anexo',
            field=models.BooleanField(default=False, editable=False),
        ),
    ]
