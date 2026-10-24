from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('ordenes', '0080_contabilidad_facturada')]

    operations = [
        migrations.AddField(
            model_name='cliente',
            name='tipo_persona',
            field=models.CharField(
                max_length=8, default='natural', db_index=True,
                choices=[('natural', 'Persona natural'), ('juridica', 'Persona jurídica')],
            ),
        ),
    ]
