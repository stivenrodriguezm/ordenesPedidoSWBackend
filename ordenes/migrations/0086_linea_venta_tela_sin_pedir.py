# Tela registrada pero que no se pide (2026-11-04): el producto guarda con qué tela se vendió,
# pero no aparece por pedir ni bloquea la gestión. La columna se crea con DEFAULT 0 en la base
# para que el código anterior (que no la conoce) pueda seguir creando líneas mientras se despliega.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0085_tareas_desarrollador'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                'ALTER TABLE ordenes_linea_venta ADD COLUMN tela_sin_pedir bool NOT NULL DEFAULT 0',
                'ALTER TABLE ordenes_linea_venta DROP COLUMN tela_sin_pedir',
            )],
            state_operations=[migrations.AddField(
                model_name='lineaventa', name='tela_sin_pedir', field=models.BooleanField(default=False),
            )],
        ),
    ]
