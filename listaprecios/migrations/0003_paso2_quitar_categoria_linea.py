import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('listaprecios', '0002_paso1_agregar_categoria_variante'),
    ]

    operations = [
        migrations.AlterField(
            model_name='varianteproducto',
            name='categoria',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name='variantes', to='listaprecios.categorialista',
            ),
        ),
        migrations.RemoveField(
            model_name='lineaproducto',
            name='categoria',
        ),
    ]
