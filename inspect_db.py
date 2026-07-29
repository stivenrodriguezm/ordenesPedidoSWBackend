import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lottusPedidos.settings')
django.setup()

from ordenes.models import PedidoTela
from ordenes.serializers import PedidoTelaSerializer

pt = PedidoTela.objects.get(id=1297)
print("Pedido ID:", pt.id)
print("Orden Asociada:", pt.orden_asociada)
print("Orden Proveedor:", pt.orden_asociada.proveedor if pt.orden_asociada else None)
print("Orden Proveedor Nombre:", pt.orden_asociada.proveedor.nombre_empresa if pt.orden_asociada and hasattr(pt.orden_asociada, 'proveedor') and pt.orden_asociada.proveedor else None)
serializer = PedidoTelaSerializer(pt)
print("Serializer Data:", serializer.data)
