# Generated manually
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('suministros', '0021_tela_inventario'),
    ]

    operations = [
        migrations.CreateModel(
            name='ItemInventarioTelaCuero',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tipo', models.CharField(choices=[('tela', 'Tela'), ('cuero', 'Cuero')], default='tela', max_length=20)),
                ('referencia', models.CharField(blank=True, max_length=100, null=True)),
                ('color', models.CharField(blank=True, max_length=50, null=True)),
                ('unidad_medida', models.CharField(choices=[('metro', 'Metro (m)'), ('decimetro', 'Decímetro (dm)')], default='metro', max_length=20)),
                ('costo_unidad', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('cantidad', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('inventario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='telas_cueros', to='suministros.inventario')),
            ],
        ),
    ]
