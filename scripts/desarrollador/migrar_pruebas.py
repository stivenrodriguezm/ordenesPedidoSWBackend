# Migra la base de pruebas con destinos explícitos por app (se ejecuta con `manage.py shell <`).
# ordenes va hasta la migración de la que depende 0061_merge_bancos_y_nomina (sin 0057 de Bancos);
# las demás apps, hasta su última migración. Si algún plan incluyera 0057 o 0061, no migra nada.
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

ejecutor = MigrationExecutor(connection)
grafo = ejecutor.loader.graph
PROHIBIDAS = {('ordenes', '0057_eliminar_bancos'), ('ordenes', '0061_merge_bancos_y_nomina')}
merge = grafo.nodes[('ordenes', '0061_merge_bancos_y_nomina')]
destinos = {'ordenes': next(n for a, n in merge.dependencies if a == 'ordenes' and n != '0057_eliminar_bancos')}
for app in sorted({a for a, _ in grafo.nodes}):
    if app == 'ordenes':
        continue
    hojas = [n for a, n in grafo.leaf_nodes(app)]
    if hojas:
        destinos[app] = hojas[0]
plan = ejecutor.migration_plan([(a, n) for a, n in destinos.items()])
incluidas = {(m.app_label, m.name) for m, _ in plan}
if incluidas & PROHIBIDAS:
    raise SystemExit('El plan incluye migraciones de Bancos; no se migra.')
for app, nombre in destinos.items():
    if any(a == app for a, _ in incluidas):
        call_command('migrate', app, nombre, verbosity=1)
print('migraciones de pruebas al día')
