"""Regresiones de comprobantes de egreso (H03, H07, H10, H15 · P02-02, P03-01,
P03-05, P03-06 · anexo A)."""
from decimal import Decimal

from ordenes.models import Caja, ComprobanteEgreso
from ordenes.tests.utils import LottusTestCase
from suministros.models import FacturaProveedor


class CrearEgresoTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.p1 = self.proveedor('Proveedor ficticio A')
        self.p2 = self.proveedor('Proveedor ficticio B')

    def crear(self, **data):
        base = {'recibido_por': 'Ficticio', 'medio_pago': 'Efectivo'}
        base.update(data)
        return self.api(self.admin).post('/api/comprobantes-egreso/crear/', base, format='json')

    def test_total_filtrado_suma_solo_el_conjunto(self):
        self.crear(proveedor=self.p1.id, valor='100', medio_pago='Transferencia')
        self.crear(proveedor=self.p2.id, valor='40', medio_pago='Transferencia')
        c = self.api(self.admin)
        r = c.get('/api/comprobantes-egreso/')
        self.assertEqual(Decimal(str(r.data['totales_filtrados']['valor'])), Decimal('140'))
        r = c.get('/api/comprobantes-egreso/', {'proveedor': str(self.p1.id)})
        self.assertEqual(Decimal(str(r.data['totales_filtrados']['valor'])), Decimal('100'))

    def test_expense_error_retains_writes(self):
        """Egreso en efectivo con caja vacía falla sin dejar comprobante, vínculo
        ni factura pagada."""
        factura = FacturaProveedor.objects.create(id_manual='f1', proveedor=self.p1, valor='100')
        r = self.crear(proveedor=self.p1.id, valor='100', facturas_ids=[factura.id])
        self.assertEqual(r.status_code, 400)
        factura.refresh_from_db()
        self.assertEqual(ComprobanteEgreso.objects.count(), 0)
        self.assertEqual(factura.estado, 'pendiente')
        self.assertIsNone(factura.comprobante_egreso_id)
        self.assertIsNone(factura.fecha_pago)
        self.assertEqual(Caja.objects.count(), 0)

    def test_expense_accepts_other_supplier_and_amount(self):
        """Factura de otro proveedor o importe incompatible se rechaza sin cambios."""
        factura_b = FacturaProveedor.objects.create(id_manual='f2', proveedor=self.p2, valor='900')
        r = self.crear(proveedor=self.p1.id, valor='1', medio_pago='Transferencia', facturas_ids=[factura_b.id])
        self.assertEqual(r.status_code, 400)
        factura_b.refresh_from_db()
        self.assertEqual(factura_b.estado, 'pendiente')
        self.assertIsNone(factura_b.comprobante_egreso_id)
        self.assertEqual(ComprobanteEgreso.objects.count(), 0)

    def test_factura_inexistente_rechazada(self):
        r = self.crear(proveedor=self.p1.id, valor='100', medio_pago='Transferencia', facturas_ids=[999999])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(ComprobanteEgreso.objects.count(), 0)

    def test_factura_ya_vinculada_rechazada(self):
        f = FacturaProveedor.objects.create(id_manual='f3', proveedor=self.p1, valor='100')
        self.assertEqual(self.crear(proveedor=self.p1.id, valor='100', medio_pago='Transferencia', facturas_ids=[f.id]).status_code, 201)
        r = self.crear(proveedor=self.p1.id, valor='100', medio_pago='Transferencia', facturas_ids=[f.id])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(ComprobanteEgreso.objects.count(), 1)

    def test_importe_menor_que_facturas_rechazado(self):
        """Sin regla de pagos parciales acordada (D02), el importe solo puede bajar
        del total de facturas por el % de descuento del proveedor y el redondeo
        de efectivo a $50 (reglas vigentes del formulario)."""
        f = FacturaProveedor.objects.create(id_manual='f4', proveedor=self.p1, valor='900')
        r = self.crear(proveedor=self.p1.id, valor='1', medio_pago='Transferencia', facturas_ids=[f.id])
        self.assertEqual(r.status_code, 400)
        f.refresh_from_db()
        self.assertEqual(f.estado, 'pendiente')

    def test_descuento_del_proveedor_y_redondeo_admitidos(self):
        self.p1.porcentaje_descuento = Decimal('5')
        self.p1.save()
        f = FacturaProveedor.objects.create(id_manual='f7', proveedor=self.p1, valor='1000')
        r = self.crear(proveedor=self.p1.id, valor='950', medio_pago='Transferencia', facturas_ids=[f.id])
        self.assertEqual(r.status_code, 201, r.data)
        self.api(self.admin).post('/api/caja/', {'tipo': 'ingreso', 'valor': '5000', 'concepto': 'base'}, format='json')
        f2 = FacturaProveedor.objects.create(id_manual='f8', proveedor=self.p1, valor='1033')
        r = self.crear(proveedor=self.p1.id, valor='1050', facturas_ids=[f2.id])  # redondeo efectivo
        self.assertEqual(r.status_code, 201, r.data)
        f3 = FacturaProveedor.objects.create(id_manual='f9', proveedor=self.p1, valor='1000')
        r = self.crear(proveedor=self.p1.id, valor='1200', medio_pago='Transferencia', facturas_ids=[f3.id])
        self.assertEqual(r.status_code, 400)

    def test_importe_con_conceptos_adicionales(self):
        """Facturas + conceptos libres: el total coincide con la suma estructurada."""
        f = FacturaProveedor.objects.create(id_manual='f5', proveedor=self.p1, valor='900')
        r = self.crear(
            proveedor=self.p1.id, valor='950', medio_pago='Transferencia', facturas_ids=[f.id],
            otros_conceptos=[{'descripcion': 'Envío', 'valor': 50}],
        )
        self.assertEqual(r.status_code, 201, r.data)
        r2 = self.crear(
            proveedor=self.p1.id, valor='999', medio_pago='Transferencia',
            otros_conceptos=[{'descripcion': 'Envío', 'valor': 50}],
        )
        self.assertEqual(r2.status_code, 400)

    def test_conceptos_que_restan(self):
        """Un concepto «resta» descuenta su valor del total; el valor se guarda positivo con su tipo."""
        f = FacturaProveedor.objects.create(id_manual='f10', proveedor=self.p1, valor='900')
        conceptos = [{'descripcion': 'Envío', 'valor': 50, 'tipo': 'suma'},
                     {'descripcion': 'Abono anterior', 'valor': 200, 'tipo': 'resta'}]
        r = self.crear(proveedor=self.p1.id, valor='750', medio_pago='Transferencia', facturas_ids=[f.id], otros_conceptos=conceptos)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(ComprobanteEgreso.objects.get().otros_conceptos, [
            {'descripcion': 'Envío', 'valor': 50, 'tipo': 'suma'}, {'descripcion': 'Abono anterior', 'valor': 200, 'tipo': 'resta'}])
        # Sumar el concepto que resta ya no corresponde.
        f2 = FacturaProveedor.objects.create(id_manual='f11', proveedor=self.p1, valor='900')
        r = self.crear(proveedor=self.p1.id, valor='1150', medio_pago='Transferencia', facturas_ids=[f2.id], otros_conceptos=conceptos)
        self.assertEqual(r.status_code, 400)
        # Tipo inválido y valor negativo se rechazan (el signo lo da el tipo).
        r = self.crear(proveedor=self.p1.id, valor='100', medio_pago='Transferencia',
                       otros_conceptos=[{'descripcion': 'X', 'valor': 100, 'tipo': 'otro'}])
        self.assertEqual(r.status_code, 400)
        r = self.crear(proveedor=self.p1.id, valor='100', medio_pago='Transferencia',
                       otros_conceptos=[{'descripcion': 'X', 'valor': -100}])
        self.assertEqual(r.status_code, 400)

    def test_conceptos_antiguos_sin_tipo_suman(self):
        r = self.crear(proveedor=self.p1.id, valor='50', medio_pago='Transferencia', otros_conceptos=[{'descripcion': 'Envío', 'valor': 50}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(ComprobanteEgreso.objects.get().otros_conceptos[0]['tipo'], 'suma')

    def test_transferencia_se_crea_sin_cuenta_destino(self):
        """La cuenta destino se asigna después (Editar o Preparar pagos), no al crear."""
        r = self.crear(proveedor=self.p1.id, valor='100', medio_pago='Transferencia')
        self.assertEqual(r.status_code, 201, r.data)
        ce = ComprobanteEgreso.objects.get()
        self.assertEqual((ce.estado, ce.cuenta_destino_id), ('Por Confirmar Pago', None))

    def test_valor_no_positivo_rechazado(self):
        self.assertEqual(self.crear(proveedor=self.p1.id, valor='0', medio_pago='Transferencia').status_code, 400)
        self.assertEqual(self.crear(proveedor=self.p1.id, valor='-5', medio_pago='Transferencia').status_code, 400)
        self.assertEqual(ComprobanteEgreso.objects.count(), 0)

    def test_efectivo_con_saldo_aplica_todo(self):
        self.api(self.admin).post('/api/caja/', {'tipo': 'ingreso', 'valor': '500', 'concepto': 'base'}, format='json')
        f = FacturaProveedor.objects.create(id_manual='f6', proveedor=self.p1, valor='100')
        r = self.crear(proveedor=self.p1.id, valor='100', facturas_ids=[f.id])
        self.assertEqual(r.status_code, 201, r.data)
        f.refresh_from_db()
        self.assertEqual(f.estado, 'pagada')
        self.assertEqual(self.saldo_caja(), Decimal('400'))
        ce = ComprobanteEgreso.objects.get()
        self.assertEqual(ce.estado, 'Pagado')

    def test_numeracion_consecutiva(self):
        ids = []
        for _ in range(3):
            r = self.crear(proveedor=self.p1.id, valor='10', medio_pago='Transferencia')
            self.assertEqual(r.status_code, 201)
            ids.append(r.data['id'])
        self.assertEqual(ids, [3001, 3002, 3003])


class AprobacionEgresoTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.p1 = self.proveedor()
        self.ce = ComprobanteEgreso.objects.create(
            id=9000, proveedor=self.p1, valor='100', medio_pago='Transferencia',
            estado='Por Confirmar Pago', recibido_por='Ficticio',
        )

    def test_edit_permission_bypasses_payment_approval(self):
        """Editar sin APROBAR_EGRESO no confirma el pago."""
        editor = self.crear_usuario('editor', role='marketing')
        self.permisos('marketing', ['EDITAR_COMPROBANTE_EGRESO'])
        r = self.api(editor).put('/api/comprobantes-egreso/9000/editar/', {
            'proveedor': self.p1.id, 'recibido_por': 'Ficticio', 'valor': '100',
            'medio_pago': 'Transferencia', 'estado': 'Pagado',
        }, format='json')
        self.assertEqual(r.status_code, 403)
        self.ce.refresh_from_db()
        self.assertEqual(self.ce.estado, 'Por Confirmar Pago')

    def test_editor_puede_editar_datos_sin_tocar_estado(self):
        editor = self.crear_usuario('editor', role='marketing')
        self.permisos('marketing', ['EDITAR_COMPROBANTE_EGRESO'])
        r = self.api(editor).put('/api/comprobantes-egreso/9000/editar/', {
            'proveedor': self.p1.id, 'recibido_por': 'Otra persona', 'valor': '100',
            'medio_pago': 'Transferencia',
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.ce.refresh_from_db()
        self.assertEqual(self.ce.recibido_por, 'Otra persona')
        self.assertEqual(self.ce.estado, 'Por Confirmar Pago')

    def test_confirmar_registra_aprobacion_una_sola_vez(self):
        f = FacturaProveedor.objects.create(id_manual='fa', proveedor=self.p1, valor='100',
                                            estado='pago_en_proceso', comprobante_egreso=self.ce)
        c = self.api(self.admin)
        self.assertEqual(c.patch('/api/comprobantes-egreso/9000/confirmar/').status_code, 200)
        self.assertEqual(c.patch('/api/comprobantes-egreso/9000/confirmar/').status_code, 200)
        self.ce.refresh_from_db(); f.refresh_from_db()
        self.assertEqual(self.ce.estado, 'Pagado')
        self.assertEqual(self.ce.aprobado_por_id, self.admin.id)
        self.assertIsNotNone(self.ce.fecha_aprobacion)
        self.assertEqual(f.estado, 'pagada')
        self.assertEqual(Caja.objects.count(), 0)  # transferencia nunca toca caja
