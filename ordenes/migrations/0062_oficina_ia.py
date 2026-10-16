from django.db import migrations, models
import django.db.models.deletion


def crear_zonas(apps, schema_editor):
    Zona = apps.get_model('ordenes', 'ZonaOficinaIA')
    Perfil = apps.get_model('ordenes', 'PerfilAsistente')
    db = schema_editor.connection.alias
    zonas = {}
    for i, (ambiente, nombre, descripcion) in enumerate([
        ('estudio', 'Estudio LOTTUS', 'Estrategia, diseño y nuevas ideas'),
        ('showroom', 'Showroom comercial', 'Ventas, clientes y crecimiento'),
        ('operaciones', 'Compras y entregas', 'Fabricantes, telas e inventario'),
        ('finanzas', 'Finanzas y equipo', 'Caja, resultados y nómina'),
    ]):
        zonas[ambiente] = Zona.objects.using(db).create(nombre=nombre, descripcion=descripcion, ambiente=ambiente, orden=i)
    # Reubica solo perfiles existentes; no crea agentes ni conversaciones ficticias.
    for p in Perfil.objects.using(db).all():
        areas = set(p.areas or [])
        ambiente = 'showroom' if 'ventas' in areas else 'operaciones' if areas & {'pedidos', 'inventario'} else 'finanzas' if areas & {'finanzas', 'nomina', 'cobros'} else 'estudio'
        p.zona_id = zonas[ambiente].pk
        p.save(using=db, update_fields=['zona'])


class Migration(migrations.Migration):
    dependencies = [('ordenes', '0060_nomina_cierre_por_asesor')]
    operations = [
        migrations.CreateModel(name='ZonaOficinaIA', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('nombre', models.CharField(max_length=60)),
            ('descripcion', models.CharField(blank=True, default='', max_length=160)),
            ('ambiente', models.CharField(choices=[('estudio', 'Estudio'), ('showroom', 'Showroom'), ('operaciones', 'Operaciones'), ('finanzas', 'Finanzas')], default='estudio', max_length=16)),
            ('orden', models.PositiveSmallIntegerField(default=0)),
        ], options={'ordering': ['orden', 'id']}),
        migrations.AddField(model_name='perfilasistente', name='zona', field=models.ForeignKey(blank=True, null=True,
            on_delete=django.db.models.deletion.SET_NULL, related_name='agentes', to='ordenes.zonaoficinaia')),
        migrations.RunPython(crear_zonas, migrations.RunPython.noop),
    ]
