# Cotizaciones (2026-11-04): teléfono del asesor y enlace del QR en el imprimible. Las columnas
# se crean con DEFAULT '' en la base para que el código anterior (que no las conoce) pueda seguir
# creando usuarios mientras se despliega.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0086_linea_venta_tela_sin_pedir'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    "ALTER TABLE ordenes_customuser ADD COLUMN telefono varchar(20) NOT NULL DEFAULT ''",
                    'ALTER TABLE ordenes_customuser DROP COLUMN telefono',
                ),
                migrations.RunSQL(
                    "ALTER TABLE ordenes_customuser ADD COLUMN enlace_qr varchar(500) NOT NULL DEFAULT ''",
                    'ALTER TABLE ordenes_customuser DROP COLUMN enlace_qr',
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='customuser', name='telefono',
                    field=models.CharField(blank=True, default='', max_length=20),
                ),
                migrations.AddField(
                    model_name='customuser', name='enlace_qr',
                    field=models.URLField(blank=True, default='', max_length=500),
                ),
            ],
        ),
    ]
