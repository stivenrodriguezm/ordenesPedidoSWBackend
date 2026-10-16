from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('ordenes', '0072_ejecutor_operativo_ia')]
    operations = [
        migrations.AddField(model_name='trabajoagenteia', name='contexto_usuario',
            field=models.JSONField(default=list, blank=True)),
        migrations.AddField(model_name='trabajoagenteia', name='continuacion_de',
            field=models.ForeignKey('ordenes.trabajoagenteia', on_delete=django.db.models.deletion.SET_NULL,
                null=True, blank=True, related_name='continuaciones')),
    ]
