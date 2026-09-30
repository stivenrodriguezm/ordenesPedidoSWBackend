import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('suministros', '0030_remisionitemmanual_categoria_referencia'),
    ]

    operations = [
        migrations.CreateModel(
            name='RemisionInventarioTexto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('descripcion', models.TextField()),
                ('inventario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='suministros.inventario')),
                ('remision', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='textos_inventario', to='suministros.remisionsuministro')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('remision', 'inventario'), name='unique_texto_inventario_por_remision')],
            },
        ),
    ]
