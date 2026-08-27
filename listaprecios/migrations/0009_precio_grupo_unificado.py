from decimal import Decimal

from django.db import migrations, models

# Corrección explícita del usuario: el precio por metro/decímetro de un
# grupo de tela es el mismo para cualquier categoría — los datos migrados
# del Excel traían valores distintos por categoría (ej. Alcobas/Salas
# pagaban más que Comedores/Poltronas/Sillas/Sofacamas en el mismo grupo);
# se unificaron a un solo valor por grupo con los valores que el usuario
# confirmó como correctos (el más alto para telas, y 1.500/decímetro para
# Cuero, que ya era el valor correcto en esa unidad).
VALORES_UNIFICADOS = {
    'Grupo 1': Decimal('30000'),
    'Grupo 2': Decimal('40000'),
    'Grupo 3': Decimal('50000'),
    'Grupo 4': Decimal('60000'),
    'Grupo 5': Decimal('70000'),
    'Cuero': Decimal('1500'),
}


def poblar_precio_grupo(apps, schema_editor):
    GrupoTela = apps.get_model('listaprecios', 'GrupoTela')
    for grupo in GrupoTela.objects.all():
        if grupo.nombre in VALORES_UNIFICADOS:
            grupo.precio_por_metro = VALORES_UNIFICADOS[grupo.nombre]
            grupo.save(update_fields=['precio_por_metro'])


def limpiar_precio_grupo(apps, schema_editor):
    GrupoTela = apps.get_model('listaprecios', 'GrupoTela')
    GrupoTela.objects.update(precio_por_metro=0)


class Migration(migrations.Migration):

    dependencies = [
        ('listaprecios', '0008_variante_notas_lista'),
    ]

    operations = [
        migrations.AddField(
            model_name='grupotela',
            name='precio_por_metro',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Precio por metro'),
        ),
        migrations.RunPython(poblar_precio_grupo, limpiar_precio_grupo),
        # DeleteModel directo (no RemoveField por campo primero): en MySQL,
        # quitar 'categoria' sola falla porque todavía la usa el
        # UniqueConstraint (categoria, grupo) — DROP TABLE se lleva la
        # constraint y las columnas juntas sin ese problema de orden.
        migrations.DeleteModel(
            name='PrecioGrupoCategoria',
        ),
    ]
