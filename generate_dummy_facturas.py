import os
import sys
import django
import random
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

# Set up Django environment
sys.path.append('/Users/stiven/Desktop/Coding/pruebaLottusKemi/ordenesPedidoSWBackend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lottusPedidos.settings')
django.setup()

from suministros.models import FacturaProveedor, DetalleFactura, Inventario
from ordenes.models import Proveedor, Referencia

def generate_dummy_data():
    # Remove old dummy data
    old_facturas = FacturaProveedor.objects.filter(id_manual__startswith="FAC-DUMMY-")
    print(f"Borrando {old_facturas.count()} facturas dummy anteriores...")
    old_facturas.delete()

    proveedores = list(Proveedor.objects.all())
    referencias = list(Referencia.objects.all())

    if not proveedores:
        print("No hay proveedores. Creando uno de prueba.")
        proveedor = Proveedor.objects.create(nombre_empresa="Proveedor Dummy", nit="123456789")
        proveedores = [proveedor]

    if not referencias:
        print("No hay referencias. Creando una de prueba.")
        referencia = Referencia.objects.create(nombre="Referencia Dummy")
        referencias = [referencia]

    for i in range(10):
        prov = random.choice(proveedores)
        # Random date in the last 30 days
        days_ago = random.randint(1, 30)
        fecha_fac = timezone.now() - timedelta(days=days_ago)
        fecha_pago = (fecha_fac + timedelta(days=15)).date()
        
        factura = FacturaProveedor.objects.create(
            id_manual=f"FAC-DUMMY-{random.randint(10000, 99999)}",
            proveedor=prov,
            estado='pendiente',
            fecha_factura=fecha_fac,
            fecha_pago=fecha_pago,
            valor=Decimal(0) # se actualiza despues
        )
        
        total = Decimal(0)
        num_detalles = random.randint(1, 5)
        for j in range(num_detalles):
            ref = random.choice(referencias)
            costo = Decimal(random.randint(10000, 500000))
            
            prefix = "XX"
            gen_id = f"{prefix}{random.randint(1000, 9999)}"
            while Inventario.objects.filter(id_referencia=gen_id).exists():
                gen_id = f"{prefix}{random.randint(1000, 9999)}"

            Inventario.objects.create(
                id_referencia=gen_id,
                referencia=ref,
                costo_especifico=costo,
                observacion=f"Producto de prueba {j+1}",
                estado_fisico='buen_estado',
                disponibilidad='exhibicion',
                factura=factura,
                factura_manual=factura.id_manual
            )
            total += costo
            
        factura.valor = total
        factura.save()
        print(f"Creada factura {factura.id_manual} para {prov.nombre_empresa} con {num_detalles} productos (en Inventario). Total: {total}")

if __name__ == "__main__":
    generate_dummy_data()
