from django.db import migrations, models


def solo_mysql(sql):
    """El DEFAULT en la base es solo para MySQL (producción y pruebas); SQLite no admite ALTER COLUMN."""
    def ejecutar(apps, schema_editor):
        if schema_editor.connection.vendor == 'mysql':
            schema_editor.execute(sql)
    return ejecutar


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
        migrations.RunPython(
            solo_mysql('ALTER TABLE ordenes_venta ALTER COLUMN tiene_anexo SET DEFAULT 0'),
            solo_mysql('ALTER TABLE ordenes_venta ALTER COLUMN tiene_anexo DROP DEFAULT'),
        ),
    ]
