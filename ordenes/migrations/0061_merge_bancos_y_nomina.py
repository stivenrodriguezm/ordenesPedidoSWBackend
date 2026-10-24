# Une dos ramas independientes: 0057 (retiro de Bancos, pendiente de autorización en
# pruebasv3) y 0058→0077 (perfiles de IA, nómina, oficina virtual, equipo IA y productos de venta). Así esas migraciones se
# aplican sin ejecutar 0057, con destino explícito:
#   migrate ordenes 0081_cliente_tipo_persona
# (Reemplaza a 0059_merge_bancos_y_perfiles_ia, que nunca se aplicó.)
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ordenes', '0057_eliminar_bancos'),
        ('ordenes', '0081_cliente_tipo_persona'),
    ]

    operations = []
