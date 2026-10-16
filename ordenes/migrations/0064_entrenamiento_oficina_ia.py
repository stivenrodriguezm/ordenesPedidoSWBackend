from django.db import migrations, models


def convertir_entrenamiento(apps, schema_editor):
    Zona = apps.get_model('ordenes', 'ZonaOficinaIA')
    zonas = Zona.objects.using(schema_editor.connection.alias)
    for zona in zonas.filter(ambiente='tecnologia'):
        zona.ambiente = 'entrenamiento'
        if zona.nombre == 'Tecnología' and not zonas.filter(nombre='Entrenamiento').exclude(pk=zona.pk).exists():
            zona.nombre = 'Entrenamiento'
        if zona.descripcion == 'Herramientas, infraestructura e inteligencia artificial':
            zona.descripcion = 'Clases, aprendizaje y motivación para el equipo comercial'
        zona.save(using=schema_editor.connection.alias, update_fields=['ambiente', 'nombre', 'descripcion'])


class Migration(migrations.Migration):
    dependencies = [('ordenes', '0063_automatizaciones_oficina_ia')]
    operations = [
        migrations.AlterField(
            model_name='zonaoficinaia', name='ambiente',
            field=models.CharField(max_length=16, default='estudio', choices=[
                ('estudio', 'Estudio'), ('showroom', 'Showroom'), ('operaciones', 'Operaciones'),
                ('finanzas', 'Finanzas'), ('gerencia', 'Gerencia'), ('oficina', 'Oficina'),
                ('entrenamiento', 'Entrenamiento'), ('creativo', 'Desarrollo creativo'), ('social', 'Zona social'),
            ]),
        ),
        # Solo cambia la identidad de la zona; conserva su ID, perfiles e historial.
        migrations.RunPython(convertir_entrenamiento, migrations.RunPython.noop),
    ]
