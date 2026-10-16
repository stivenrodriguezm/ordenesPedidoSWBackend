from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('listaprecios', '0019_adicionales_componentes')]
    operations = [migrations.AddField(
        model_name='cargovariante', name='preseleccionado',
        field=models.BooleanField(default=False, verbose_name='Opcional seleccionado de entrada'),
    )]
