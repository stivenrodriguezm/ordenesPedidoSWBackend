from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('ordenes', '0070_academia_cursos')]
    operations = [
        migrations.AddField('interaccionoficina', 'ejecucion', models.ForeignKey(blank=True, null=True,
            on_delete=django.db.models.deletion.CASCADE, related_name='interacciones', to='ordenes.ejecucionautomatizacionia')),
        migrations.AddField('interaccionoficina', 'conversacion', models.ForeignKey(blank=True, null=True,
            on_delete=django.db.models.deletion.CASCADE, related_name='interacciones', to='ordenes.conversacionasistente')),
    ]
