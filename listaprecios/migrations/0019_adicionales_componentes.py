from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('listaprecios', '0018_costos_componentes')]
    operations = [migrations.AddField(
        model_name='componentejuego', name='adicionales',
        field=models.JSONField(blank=True, default=list, verbose_name='Cargos y especiales solo en este conjunto'),
    )]
