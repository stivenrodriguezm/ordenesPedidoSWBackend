import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('suministros', '0019_alter_inventario_disponibilidad'),
    ]

    operations = [
        migrations.CreateModel(
            name='CostoAdicionalInventario',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('descripcion', models.CharField(max_length=200)),
                ('valor', models.DecimalField(decimal_places=2, max_digits=12)),
                ('fecha', models.DateField(default=django.utils.timezone.localdate)),
                ('inventario', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='costos_adicionales',
                    to='suministros.inventario',
                )),
            ],
            options={
                'ordering': ['fecha', 'id'],
            },
        ),
    ]
