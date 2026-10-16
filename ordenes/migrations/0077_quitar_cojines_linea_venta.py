# 2026-10-15: los cojines por línea de venta se retiran (ahora: «Cojines incluidos» →
# decorativos cubiertos, guardado en precio_snapshot['decorativos']).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0076_linea_venta_cojines'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='lineaventa',
            name='cojines',
        ),
    ]
