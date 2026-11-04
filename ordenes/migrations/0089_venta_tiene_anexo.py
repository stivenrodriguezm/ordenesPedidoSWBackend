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
        # Permite volver al código anterior sin impedirle crear nuevas ventas.
        migrations.RunSQL(
            'ALTER TABLE ordenes_venta ALTER COLUMN tiene_anexo SET DEFAULT 0',
            'ALTER TABLE ordenes_venta ALTER COLUMN tiene_anexo DROP DEFAULT',
        ),
    ]
