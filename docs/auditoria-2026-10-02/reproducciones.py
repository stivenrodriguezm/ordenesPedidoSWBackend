"""Read-only audit of source; all writes use a disposable in-memory database."""
import os, sys, socket, json, logging
from pathlib import Path
from datetime import date
from decimal import Decimal
ROOT = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, ROOT)
os.environ['DJANGO_SETTINGS_MODULE'] = 'lottusPedidos.settings_test'
def no_network(*args, **kwargs):
    raise RuntimeError('External network disabled for audit probes')
socket.socket.connect = no_network
import django
from django.conf import settings
assert settings.DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3'
assert settings.DATABASES['default']['NAME'] == ':memory:'
settings.ALLOWED_HOSTS = ['testserver']
settings.SECURE_SSL_REDIRECT = False
settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
django.setup()
logging.disable(logging.CRITICAL)
from django.core.management import call_command
call_command('migrate', verbosity=0, interactive=False)
from rest_framework.test import APIClient
from ordenes.models import CustomUser, RolePermission, Cliente, Venta, Proveedor, Referencia, OrdenPedido, Caja, ComprobanteEgreso, ReciboCaja, PagoReciboCaja
from suministros.models import FacturaProveedor, Inventario, RemisionSuministro, HistorialTraslado, Sede, Zona, ItemInventarioTelaCuero
from suministros.serializers import InventarioSerializer, RemisionSuministroSerializer
from rest_framework.test import APIRequestFactory, force_authenticate

admin = CustomUser.objects.create(username='audit_admin', role='administrador')
seller = CustomUser.objects.create(username='audit_seller', first_name='Audit seller', role='vendedor')
owner = CustomUser.objects.create(username='audit_owner', role='vendedor')
limited = CustomUser.objects.create(username='audit_limited', role='marketing')
customer = Cliente.objects.create(nombre='Cliente ficticio', cedula='audit-001', telefono1='000')
p1 = Proveedor.objects.create(nombre_empresa='Proveedor ficticio A')
p2 = Proveedor.objects.create(nombre_empresa='Proveedor ficticio B')
ref = Referencia.objects.create(proveedor=p1, nombre='Referencia ficticia')
sale_seq = 100
def sale(who=owner, value='1000', state='pendiente'):
    global sale_seq
    sale_seq += 1
    return Venta.objects.create(id=sale_seq, cliente=customer, vendedor=who, valor_total=value, saldo=value, fecha_venta=date.today(), fecha_entrega=date.today(), estado=state)
def api(user=admin):
    c = APIClient()
    c.force_authenticate(user)
    return c
def permissions(user, codes):
    RolePermission.objects.update_or_create(role=user.role, defaults={'permissions': codes})
results = []
def record(name, **data):
    results.append(dict(probe=name, **data))

# Negative values bypass the strict non-negative cash balance business rule.
r = api().post('/api/caja/', {'tipo':'ingreso','valor':'-100','concepto':'audit'}, format='json')
record('negative_cash_income', status=r.status_code, balance=str(Caja.objects.latest('id').total_acumulado))
Caja.objects.all().delete()
permissions(limited, ['VER_CAJA'])
r = api(limited).post('/api/caja/', {'tipo':'cierre','valor':'900000','concepto':'audit'}, format='json')
record('read_only_cash_permission_can_set_balance', status=r.status_code, balance=str(Caja.objects.latest('id').total_acumulado))
Caja.objects.all().delete()

# A failed cash expense retains the expense voucher and paid invoice.
invoice = FacturaProveedor.objects.create(id_manual='audit-f1', proveedor=p1, valor='100')
r = api().post('/api/comprobantes-egreso/crear/', {'proveedor':p1.id, 'recibido_por':'Ficticio','valor':'100','medio_pago':'Efectivo','facturas_ids':[invoice.id]}, format='json')
invoice.refresh_from_db()
record('expense_error_retains_writes', status=r.status_code, voucher_count=ComprobanteEgreso.objects.count(), invoice_state=invoice.estado, voucher_link=invoice.comprobante_egreso_id, cash_movements=Caja.objects.count())

# Creation trusts invoice ownership and amount supplied by client.
invoice2 = FacturaProveedor.objects.create(id_manual='audit-f2', proveedor=p2, valor='900')
r = api().post('/api/comprobantes-egreso/crear/', {'proveedor':p1.id, 'recibido_por':'Ficticio','valor':'1','medio_pago':'Transferencia','facturas_ids':[invoice2.id]}, format='json')
invoice2.refresh_from_db()
record('expense_accepts_other_supplier_and_amount', status=r.status_code, invoice_state=invoice2.estado, linked=bool(invoice2.comprobante_egreso_id))

permissions(limited, ['EDITAR_COMPROBANTE_EGRESO'])
ce = ComprobanteEgreso.objects.create(id=9000, proveedor=p1, valor='100', medio_pago='Transferencia', estado='Por Confirmar Pago', recibido_por='Ficticio')
r = api(limited).put('/api/comprobantes-egreso/9000/editar/', {'proveedor':p1.id,'recibido_por':'Ficticio','valor':'100','medio_pago':'Transferencia','estado':'Pagado'}, format='json')
ce.refresh_from_db()
record('edit_permission_bypasses_payment_approval', status=r.status_code, state=ce.estado)

# Object-level authorization and allowed fields differ across related endpoints.
foreign_sale = sale()
permissions(seller, ['VER_VENTAS','EDITAR_ESTADO_VENTA','VER_ORDENES','VER_PROPIAS_ORDENES','VER_INVENTARIO'])
c = api(seller)
before = c.get(f'/api/ventas/{foreign_sale.pk}/').status_code
r = c.put(f'/api/ventas/{foreign_sale.pk}/editar/', {'venta':{'estado':'entregado'},'cliente':{'nombre':'Modificado sin permiso de cliente'}}, format='json')
foreign_sale.refresh_from_db(); customer.refresh_from_db()
record('edit_foreign_sale_and_customer_with_state_permission', detail_status=before, edit_status=r.status_code, state=foreign_sale.estado, customer_modified=customer.nombre.startswith('Modificado'))
order = OrdenPedido.objects.create(proveedor=p1, usuario=owner, venta=foreign_sale, fecha_esperada=date.today(), costo='750')
regular = c.get(f'/api/ordenes-pedido/{order.pk}/')
full = c.get(f'/api/ordenes-pedido/{order.pk}/completo/')
record('alternate_order_endpoint_bypasses_ownership', regular_status=regular.status_code, full_status=full.status_code, cost=full.data.get('costo'))
inv = Inventario.objects.create(id_referencia='AUDITINV', referencia=ref, costo_especifico='765')
r = c.get('/api/suministros/inventario/AUDITINV/')
record('inventory_cost_visible_without_cost_permission', status=r.status_code, cost=r.data.get('costo_especifico'))

# PATCH authorization does not cover PUT or DELETE.
permissions(seller, ['VER_REMISIONES'])
rem = RemisionSuministro.objects.create(vendedor=seller, fecha_entrega=date.today())
c = api(seller)
patch = c.patch(f'/api/suministros/remisiones/{rem.pk}/', {'estado':'anulada'}, format='json')
put = c.put(f'/api/suministros/remisiones/{rem.pk}/', {'estado':'anulada'}, format='json')
record('remision_put_bypasses_patch_permission', patch_status=patch.status_code, put_status=put.status_code)
rem2 = RemisionSuministro.objects.create(vendedor=seller, fecha_entrega=date.today())
rem2.inventario_items.add(inv)
inv.disponibilidad='por_despachar'; inv.save()
r = c.delete(f'/api/suministros/remisiones/{rem2.pk}/')
inv.refresh_from_db()
record('remision_read_permission_can_delete', status=r.status_code, inventory_state=inv.disponibilidad)

# Editing invoice products destroys stable stock identities and their history.
invoice3 = FacturaProveedor.objects.create(id_manual='audit-f3', proveedor=p1, valor='100')
old = Inventario.objects.create(id_referencia='AUDITOLD', referencia=ref, factura=invoice3, disponibilidad='por_despachar')
HistorialTraslado.objects.create(item_inventario=old, usuario=admin)
rem3 = RemisionSuministro.objects.create(vendedor=admin, fecha_entrega=date.today())
rem3.inventario_items.add(old)
r = api().patch(f'/api/suministros/facturas/{invoice3.pk}/', {'productos':[{'referencia':ref.pk, 'cantidad':1, 'costo':100}]}, format='json')
record('invoice_edit_deletes_stock_identity_and_history', status=r.status_code, old_item_exists=Inventario.objects.filter(pk='AUDITOLD').exists(), shipment_items=rem3.inventario_items.count(), movement_history=HistorialTraslado.objects.filter(item_inventario_id='AUDITOLD').count())
r = api().post('/api/suministros/facturas/', {'id_manual':'audit-invalid','proveedor':p1.pk,'valor':'999','productos':[{'referencia':999999,'costo':'1','cantidad':1}]}, format='json')
record('invoice_accepts_invalid_product_and_total', status=r.status_code, items=len(r.data.get('items_inventario', [])))

# New multi-fabric data isn't included in backend total cost.
cost_item = Inventario.objects.create(id_referencia='AUDITCOST', referencia=ref, costo_especifico='100')
ItemInventarioTelaCuero.objects.create(inventario=cost_item, costo_unidad='20', cantidad='3')
record('cost_omits_new_fabric_rows', computed=InventarioSerializer(cost_item).data['costo_total'], expected='160')

# Cancelled sale and multi-seller math in dashboard.
shared = sale(who=owner, value='300')
shared.vendedores_compartidos.add(seller, limited)
r = api(seller).get('/api/dashboard-stats/')
record('shared_sales_three_people', dashboard_value=r.data.get('ventas_dia'), expected='100')
cancelled = sale(who=seller, value='600', state='anulada')
r = api(seller).get('/api/dashboard-stats/')
record('cancelled_sale_in_dashboard', dashboard_value=r.data.get('ventas_dia'), expected_excluding_cancelled='100')

# Paying a pending cash line changed from transfer updates sale but not cash.
s = sale()
rc = ReciboCaja.objects.create(id=9900, venta=s)
pay = PagoReciboCaja.objects.create(recibo=rc, metodo_pago='Davivienda', valor='50', estado='Pendiente')
r1 = api().put('/api/recibos-caja/9900/editar/', {'pagos_pendientes':[{'id':pay.pk,'metodo_pago':'Efectivo','valor':'50'}]}, format='json')
cash_before = Caja.objects.count()
r2 = api().patch(f'/api/recibos-caja/pagos/{pay.pk}/confirmar/', {}, format='json')
s.refresh_from_db(); pay.refresh_from_db()
record('transfer_changed_to_cash_missing_cash_movement', edit_status=r1.status_code, confirm_status=r2.status_code, sale_paid=str(s.abono), cash_movements_created=Caja.objects.count()-cash_before)

# Read-only price access also authorizes the bulk mutation custom action.
from listaprecios.models import CategoriaLista, LineaProducto, VarianteProducto, Multiplicador
cat = CategoriaLista.objects.create(nombre='Audit', slug='audit')
line = LineaProducto.objects.create(nombre='Audit', slug='audit')
mult = Multiplicador.objects.create(nombre='Audit', valor='2')
variant = VarianteProducto.objects.create(linea=line, categoria=cat, nombre='Audit', costo_base='100')
permissions(limited, ['VER_COSTOS_LISTA_PRECIOS'])
r = api(limited).post('/api/listaprecios/variantes/asignar-multiplicador/', {'multiplicador':mult.pk,'variante_ids':[variant.pk]}, format='json')
variant.refresh_from_db()
record('read_price_permission_allows_bulk_mutation', status=r.status_code, multiplier_changed=variant.multiplicador_id == mult.pk)

# A remision for an owned sale can reserve another seller's stock.
permissions(seller, ['CREAR_REMISION'])
own = sale(who=seller)
foreign = sale(who=owner)
foreign_inv = Inventario.objects.create(id_referencia='AUDITFOREIGN', referencia=ref, venta=foreign, disponibilidad='cliente')
r = api(seller).post('/api/suministros/remisiones/', {'ventas':[own.pk], 'fecha_entrega':str(date.today()), 'inventario_items':[foreign_inv.pk]}, format='json')
foreign_inv.refresh_from_db()
record('remision_reserves_inventory_of_foreign_sale', status=r.status_code, inventory_state=foreign_inv.disponibilidad, original_sale_id=foreign_inv.venta_id, submitted_sale_id=own.pk)

# Race simulated as two validations before either write (not a MySQL load test).
race_inv = Inventario.objects.create(id_referencia='AUDITRACE', referencia=ref, disponibilidad='exhibicion')
payload = {'fecha_entrega':str(date.today()), 'inventario_items':[race_inv.pk]}
s1 = RemisionSuministroSerializer(data=payload)
s2 = RemisionSuministroSerializer(data=payload)
both_valid = s1.is_valid() and s2.is_valid()
if both_valid:
    s1.save(); s2.save()
record('interleaved_remision_validation_allows_double_reservation', both_valid=both_valid, reservations=race_inv.remisiones_suministros.count())

# Paid invoice can be deleted despite update's explicit safeguard.
paid_invoice_id = invoice.pk
r = api().delete(f'/api/suministros/facturas/{paid_invoice_id}/')
record('paid_invoice_delete_bypasses_edit_safeguard', status=r.status_code, invoice_exists=FacturaProveedor.objects.filter(pk=paid_invoice_id).exists())

# GET role configuration has write side effects and changes fallback permissions.
RolePermission.objects.filter(role='auxiliar').delete()
aux = CustomUser.objects.create(username='audit_aux', role='auxiliar')
before = api(aux).get('/api/caja/').status_code
api().get('/api/role-permissions/')
after = api(aux).get('/api/caja/').status_code
record('viewing_role_configuration_removes_aux_default_permissions', before=before, after=after)

# Client requests 1000 choices but API silently caps at 100.
Proveedor.objects.bulk_create([Proveedor(nombre_empresa=f'Audit supplier {i}') for i in range(101)])
r = api().get('/api/proveedores/?page_size=1000')
record('supplier_choices_silently_truncated', status=r.status_code, returned=len(r.data['results']), total=r.data['count'], has_next=bool(r.data['next']))

# Preserve valid business rule: no empty purchase orders.
r = api().post('/api/ordenes-pedido/', {'proveedor':p1.pk,'fecha_esperada':str(date.today()),'detalles':[]}, format='json')
record('empty_order_is_correctly_rejected', status=r.status_code)
r = api().post('/api/ordenes-pedido/', {'proveedor':p2.pk,'fecha_esperada':str(date.today()),'detalles':[{'referencia':ref.pk,'cantidad':0,'especificaciones':'audit'}]}, format='json')
record('zero_quantity_and_wrong_supplier_reference_accepted', status=r.status_code)

# A regular edit can silently leave the catalog without a general multiplier.
general = Multiplicador.objects.filter(es_general=True).first()
if general:
    r = api().patch(f'/api/listaprecios/multiplicadores/{general.pk}/', {'es_general':False}, format='json')
    from listaprecios.services import obtener_multiplicador_general
    record('catalog_general_multiplier_can_be_unset', status=r.status_code, fallback=str(obtener_multiplicador_general()))

# Non-admin user administration permission can grant admin role.
permissions(limited, ['ADMINISTRAR_USUARIOS'])
r = api(limited).patch(f'/api/usuarios/{limited.pk}/', {'role':'administrador'}, format='json')
limited.refresh_from_db()
record('user_manager_can_self_promote_to_admin', status=r.status_code, role=limited.role)

print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
