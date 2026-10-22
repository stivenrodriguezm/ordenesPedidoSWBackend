from .archivos_privados import almacen_evidencias
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone

class CustomUser(AbstractUser):
    ROLE_CHOICES = (
        ('vendedor', 'Vendedor'),
        ('administrador', 'Administrador'),
        ('auxiliar', 'Auxiliar'),
        ('transportador', 'Transportador'),
        ('marketing', 'Marketing'),
        # Contabilidad (2026-10-21): ve ventas, recibos y comprobantes y marca ventas facturadas.
        ('contabilidad', 'Contabilidad'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='vendedor')
    acceso_rapido_ia = models.BooleanField(default=False)

class RolePermission(models.Model):
    role = models.CharField(max_length=20, choices=CustomUser.ROLE_CHOICES, unique=True)
    permissions = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"Permisos para Rol: {self.get_role_display()}"

class Proveedor(models.Model):
    nombre_empresa = models.CharField(max_length=255, unique=True, default='N/A')
    nombre_encargado = models.CharField(max_length=255, default='N/A')
    contacto = models.CharField(max_length=20, default='0')
    dias_pago = models.IntegerField(default=0)
    porcentaje_descuento = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)

    def __str__(self):
        return self.nombre_empresa

class Referencia(models.Model):
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name='referencias')
    nombre = models.CharField(max_length=255)
    categorias = models.ManyToManyField(
        'suministros.Categoria',
        blank=True,
        related_name='referencias',
    )
    subcategorias = models.ManyToManyField(
        'suministros.Subcategoria',
        blank=True,
        related_name='referencias',
    )

    def __str__(self):
        return f'{self.nombre} ({self.proveedor.nombre_empresa})'

class Cliente(models.Model):
    nombre = models.CharField(max_length=255, db_index=True)
    cedula = models.CharField(max_length=20, unique=True, db_index=True)
    correo = models.EmailField(blank=True, null=True)
    direccion = models.CharField(max_length=255, blank=True, null=True)
    barrio = models.CharField(max_length=100, blank=True, null=True)
    ciudad = models.CharField(max_length=100, blank=True, null=True)
    telefono1 = models.CharField(max_length=20)
    telefono2 = models.CharField(max_length=20, blank=True, null=True)

    def __str__(self):
        return self.nombre

class CorreccionCliente(models.Model):
    """Valores originales de correcciones de formato, visibles solo al revisor."""
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='correcciones_formato')
    usuario = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='+')
    fecha = models.DateTimeField(default=timezone.now)
    cambios = models.JSONField(default=dict)

    class Meta:
        ordering = ['-id']


class Venta(models.Model):
    # Constantes de estado: usar estas en vez de literales ('anulado' ≠ 'anulada', H13).
    ESTADO_PENDIENTE = 'pendiente'
    ESTADO_ENTREGADO = 'entregado'
    ESTADO_ANULADA = 'anulada'
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('entregado', 'Entregado'),
        ('anulada', 'Anulada'),
    ]
    id = models.PositiveIntegerField(primary_key=True)
    # PROTECT: borrar un cliente o usuario nunca debe arrastrar sus ventas
    # (auditoría 2026-10-02, H12). Los usuarios se desactivan, no se borran.
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='ventas')
    vendedor = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='ventas')
    vendedores_compartidos = models.ManyToManyField(CustomUser, related_name='ventas_compartidas', blank=True)
    traslado = models.BooleanField(default=False)
    sede = models.CharField(max_length=20, choices=[('Lottus 1', 'Lottus 1'), ('Lottus 2', 'Lottus 2')], default='Lottus 1', null=True, blank=True, db_index=True)
    valor_total = models.DecimalField(max_digits=10, decimal_places=2)
    # Precio de lista antes del descuento (D12a): define el % de comisión en Nómina.
    valor_lista = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    revision_productos = models.PositiveIntegerField(default=0)
    productos_confirmados = models.BooleanField(default=False)
    abono = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    saldo = models.DecimalField(max_digits=10, decimal_places=2)
    fecha_venta = models.DateField(default=timezone.localdate, db_index=True)
    fecha_entrega = models.DateField(db_index=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='pendiente', db_index=True)
    # Gestión de la venta (2026-10-08): True = el asesor finalizó la gestión (todo
    # pedido, telas incluidas, y productos con precio de lista). Antes era "Pedidos".
    estado_pedidos = models.BooleanField(default=False, db_index=True)
    gestion_finalizada_en = models.DateTimeField(null=True, blank=True)
    gestion_finalizada_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    es_feria_hogar = models.BooleanField(default=False, db_index=True)
    # Facturación (2026-10-21): la marca quien tiene MARCAR_VENTA_FACTURADA (p. ej. Contabilidad).
    facturada = models.BooleanField(default=False, db_index=True)
    facturada_en = models.DateTimeField(null=True, blank=True)
    facturada_por = models.ForeignKey('CustomUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='ventas_facturadas')
    # Postferia (2026-10-08): venta hecha después de la Feria del Hogar. Solo es una
    # estadística guardada; no cambia sede, pedidos ni ningún otro comportamiento.
    es_postferia = models.BooleanField(default=False, db_index=True)

    def __str__(self):
        return f"Venta {self.id} - {self.cliente.nombre}"


class LineaVenta(models.Model):
    """Línea de venta propia (P09-03 / F02).
    Permite modelar cantidad, variante/producto, opciones, precio pactado y
    compromiso de entrega por producto, enlazando compras, inventario y remisiones."""
    ESTADO_ENTREGA_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('en_produccion', 'En Producción'),
        ('preparado', 'Preparado'),
        ('despachado', 'Despachado'),
        ('entregado', 'Entregado'),
        ('cancelado', 'Cancelado'),
    ]

    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name='lineas')
    # Servicios y ajustes de la venta (2026-10-08): además de productos, la venta puede
    # llevar transporte, artículos adicionales sin referencia (jarrones, decoración) y
    # ajustes de negociación que suman o restan. Suman al precio de lista; no se piden
    # al proveedor ni llevan tela.
    TIPO_PRODUCTO, TIPO_TRANSPORTE, TIPO_ARTICULO, TIPO_AJUSTE = 'producto', 'transporte', 'articulo', 'ajuste'
    TIPO_CHOICES = [('producto', 'Producto'), ('transporte', 'Transporte'), ('articulo', 'Artículo adicional'), ('ajuste', 'Ajuste')]
    tipo = models.CharField(max_length=12, choices=TIPO_CHOICES, default='producto')
    variante = models.ForeignKey(
        'listaprecios.VarianteProducto', on_delete=models.SET_NULL, null=True, blank=True, related_name='lineas_venta'
    )
    referencia = models.ForeignKey(
        Referencia, on_delete=models.SET_NULL, null=True, blank=True, related_name='lineas_venta'
    )
    producto_nombre = models.CharField(max_length=255, verbose_name="Nombre del Producto / Colección")
    variante_nombre = models.CharField(max_length=255, blank=True, default='', verbose_name="Variante / Detalle")
    categoria_nombre = models.CharField(max_length=100, blank=True, default='', verbose_name="Categoría")
    grupo_tela = models.CharField(max_length=100, blank=True, default='', verbose_name="Grupo de Tela")
    especificaciones = models.TextField(blank=True, default='', verbose_name="Especificaciones")
    cantidad = models.PositiveIntegerField(default=1, verbose_name="Cantidad")
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="Precio Unitario")
    descuento = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="Descuento")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="Subtotal")
    costo_estimado = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Costo estimado unitario"
    )
    precio_lista_unitario = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    grupo_catalogo = models.ForeignKey('listaprecios.GrupoTela', on_delete=models.SET_NULL, null=True, blank=True)
    texto_proveedor = models.TextField(blank=True, default='')
    # "No aplica": el producto no necesita indicaciones para el proveedor.
    sin_texto_proveedor = models.BooleanField(default=False)
    texto_cliente = models.TextField(blank=True, default='')
    # Tela del producto (2026-10-08): '' = sin definir; no_aplica; incluida (la pone el
    # fabricante del mueble); aparte (Lottus la compra a un proveedor de tela).
    TELA_SIN_DEFINIR, TELA_NO_APLICA, TELA_INCLUIDA, TELA_APARTE = '', 'no_aplica', 'incluida', 'aparte'
    TELA_MODO_CHOICES = [('', 'Sin definir'), ('no_aplica', 'No lleva tela'), ('incluida', 'La incluye el proveedor'), ('aparte', 'Se compra aparte')]
    tela_modo = models.CharField(max_length=12, choices=TELA_MODO_CHOICES, blank=True, default='')
    # Igual que un pedido de /telas: material (tela en metros, cuero en decímetros),
    # referencia y color de la tela con que se vendió.
    TELA_MATERIAL_CHOICES = [('tela', 'Tela'), ('cuero', 'Cuero')]
    tela_material = models.CharField(max_length=6, choices=TELA_MATERIAL_CHOICES, blank=True, default='')
    tela_referencia = models.CharField(max_length=255, blank=True, default='')
    tela_color = models.CharField(max_length=255, blank=True, default='')
    tela_proveedor = models.ForeignKey('ProveedorTela', on_delete=models.SET_NULL, null=True, blank=True, related_name='lineas_venta')
    tela_cantidad = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    # (2026-10-15) Grupo de la tela o cuero (une el producto con la lista de precios aunque
    # no sea de catálogo) y su costo del proveedor por metro (tela) o decímetro (cuero).
    tela_grupo = models.ForeignKey('listaprecios.GrupoTela', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    tela_costo = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Conjunto (comedor = mesa + sillas; cama = base + cabecero…): piezas que se venden y se
    # ven juntas, pero cada una se pide y se factura con su propia referencia.
    conjunto = models.CharField(max_length=36, blank=True, default='', db_index=True)
    conjunto_nombre = models.CharField(max_length=150, blank=True, default='')
    conjunto_cantidad = models.PositiveIntegerField(default=1)
    adicionales = models.JSONField(default=list, blank=True)
    precio_snapshot = models.JSONField(default=dict, blank=True)
    motivo_precio = models.CharField(max_length=1000, blank=True, default='')
    inventario_origen = models.OneToOneField('suministros.Inventario', on_delete=models.PROTECT,
                                           null=True, blank=True, related_name='linea_venta_origen')
    fecha_compromiso = models.DateField(null=True, blank=True, verbose_name="Fecha de Compromiso de Entrega")
    estado_entrega = models.CharField(max_length=30, choices=ESTADO_ENTREGA_CHOICES, default='pendiente', db_index=True)
    opcionales = models.JSONField(default=list, blank=True, verbose_name="Opcionales")
    notas = models.TextField(blank=True, default='', verbose_name="Notas")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'ordenes_linea_venta'
        ordering = ['id']
        verbose_name = 'Línea de Venta'
        verbose_name_plural = 'Líneas de Venta'

    def __str__(self):
        return f"{self.cantidad}x {self.producto_nombre} (Venta {self.venta_id})"


class OrdenPedido(models.Model):
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('en_proceso', 'En Proceso'),
        ('finalizado', 'Finalizado'),
        ('recibido', 'Recibido'),
        ('anulado', 'Anulado'),
    ]
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, related_name='ordenes')
    usuario = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='ordenes')
    venta = models.ForeignKey(Venta, on_delete=models.PROTECT, related_name='ordenes_pedido', null=True, blank=True)
    fecha_creacion = models.DateField(auto_now_add=True, db_index=True)
    fecha_esperada = models.DateField()
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='pendiente', db_index=True)
    observacion = models.TextField(blank=True, null=True)
    tela = models.CharField(max_length=255, blank=True, null=True)
    requiere_tela = models.BooleanField(default=False)
    costo = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    orden_venta = models.CharField(max_length=50, blank=True, null=True)
    es_exhibicion = models.BooleanField(default=False)
    es_feria_hogar = models.BooleanField(default=False)
    # URL de Cloudinary de la foto del pedido de Feria del Hogar (opcional,
    # solo tiene sentido cuando es_feria_hogar=True). Mismo mecanismo de
    # subida que las imágenes de paginaweb (ver paginaweb/cloudinary_client.py).
    imagen_feria_hogar = models.URLField(max_length=500, blank=True, null=True)

    def __str__(self):
        return f"Orden {self.id} para {self.proveedor.nombre_empresa}"

class DetallePedido(models.Model):
    orden = models.ForeignKey(OrdenPedido, on_delete=models.CASCADE, related_name='detalles')
    referencia = models.ForeignKey(Referencia, on_delete=models.SET_NULL, null=True, blank=True)
    linea_venta = models.ForeignKey(LineaVenta, on_delete=models.SET_NULL, null=True, blank=True, related_name='detalles')
    # Pedido anterior que el asesor marcó como "no es de un producto de esta venta":
    # ya no se ofrece para vincular ni bloquea nuevos pedidos.
    ignorar_vinculo = models.BooleanField(default=False)
    cantidad = models.PositiveIntegerField()
    especificaciones = models.TextField()

    def __str__(self):
        return f"Detalle de Orden {self.orden.id} - Ref: {self.referencia.nombre if self.referencia else 'Sin referencia'}"

class ObservacionVenta(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name='observaciones')
    autor = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    texto = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)

class ObservacionCliente(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='observaciones')
    autor = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    texto = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)

class Remision(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name='remisiones')
    codigo = models.CharField(max_length=50, unique=True)
    fecha = models.DateField(default=timezone.localdate)

class ReciboCaja(models.Model):
    id = models.PositiveIntegerField(primary_key=True)
    venta = models.ForeignKey(Venta, on_delete=models.PROTECT, related_name='recibos')
    fecha = models.DateField(default=timezone.localdate, db_index=True)
    nota = models.TextField(blank=True, null=True)

class PagoReciboCaja(models.Model):
    """Una línea de pago dentro de un ReciboCaja — un recibo puede cubrirse con
    varios medios de pago a la vez (ej. una parte en efectivo y otra por
    transferencia); cada línea se confirma de forma independiente."""
    MEDIO_PAGO_CHOICES = [
        ('Efectivo', 'Efectivo'),
        ('Davivienda', 'Davivienda'),
        ('Bancolombia', 'Bancolombia'),
        ('Bold', 'Bold'),
        ('Datafono Lottus', 'Datafono Lottus'),
        ('Otro', 'Otro'),
    ]
    ESTADO_CHOICES = [
        ('Pendiente', 'Pendiente'),
        ('Confirmado', 'Confirmado'),
        ('Anulado', 'Anulado'),
    ]
    recibo = models.ForeignKey(ReciboCaja, on_delete=models.CASCADE, related_name='pagos')
    metodo_pago = models.CharField(max_length=50, choices=MEDIO_PAGO_CHOICES, db_index=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='Pendiente', db_index=True)
    confirmacion = models.TextField(blank=True, null=True)
    confirmado_por = models.ForeignKey(CustomUser, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    fecha_confirmacion = models.DateTimeField(null=True, blank=True)

class CuentaCaja(models.Model):
    """Caja física identificable (P03-02). Su fila se bloquea con
    select_for_update para serializar movimientos, incluso cuando todavía no
    existe ningún movimiento. `saldo` lo calcula siempre el servidor."""
    nombre = models.CharField(max_length=100, unique=True)
    sede = models.ForeignKey('suministros.Sede', on_delete=models.PROTECT, null=True, blank=True, related_name='cajas')
    saldo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    activa = models.BooleanField(default=True)

    PRINCIPAL = 'Caja principal'

    class Meta:
        constraints = [
            models.CheckConstraint(check=models.Q(saldo__gte=0), name='cuentacaja_saldo_no_negativo'),
        ]

    def __str__(self):
        return self.nombre


class Caja(models.Model):
    TIPO_CHOICES = [
        ('ingreso', 'Ingreso'),
        ('egreso', 'Egreso'),
        ('cierre', 'Cierre'),
    ]
    usuario = models.ForeignKey(CustomUser, on_delete=models.PROTECT)
    cuenta = models.ForeignKey(CuentaCaja, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos')
    fecha_hora = models.DateTimeField(default=timezone.now, db_index=True)
    concepto = models.CharField(max_length=255, blank=False, null=False, default='')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    total_acumulado = models.DecimalField(max_digits=12, decimal_places=2)
    # Trazabilidad estructurada (P03-07): el documento que originó el
    # movimiento y, si es una reversión, el movimiento que compensa.
    comprobante_egreso = models.ForeignKey('ComprobanteEgreso', on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos_caja')
    pago_recibo = models.ForeignKey('PagoReciboCaja', on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos_caja')
    reversa_de = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='reversiones')

class ComprobanteEgreso(models.Model):
    id = models.PositiveIntegerField(primary_key=True)
    MEDIO_PAGO_CHOICES = [
        ('Efectivo', 'Efectivo'),
        ('Transferencia', 'Transferencia'),
        ('Otro', 'Otro'),
    ]
    proveedor = models.ForeignKey(Proveedor, on_delete=models.PROTECT, null=True, blank=True)
    # Nombre libre del proveedor cuando no está registrado en el sistema (proveedor = "Otro").
    proveedor_otro_nombre = models.CharField(max_length=255, blank=True, default='')
    cuenta_destino = models.ForeignKey('pagos.CuentaBancaria', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    cuenta_destino_snapshot = models.JSONField(default=dict, blank=True)
    proveedor_tela = models.ForeignKey('ProveedorTela', on_delete=models.PROTECT, null=True, blank=True, related_name='comprobantes_egreso')
    fecha = models.DateField(default=timezone.localdate, db_index=True)
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    medio_pago = models.CharField(max_length=20, choices=MEDIO_PAGO_CHOICES, db_index=True)
    estado = models.CharField(max_length=50, default='Por Confirmar Pago')
    descripcion = models.TextField(blank=True, null=True)
    concepto = models.CharField(max_length=255, default='', blank=True)
    recibido_por = models.CharField(max_length=255, blank=True, default='')
    # Desglose estructurado de conceptos libres (envíos, instalaciones, etc.)
    # que no corresponden a una factura: [{"descripcion": str, "valor": number}].
    # Permite renderizarlos como lista/tabla en el imprimible en vez de texto
    # concatenado dentro de `descripcion`.
    otros_conceptos = models.JSONField(default=list, blank=True)
    # Autoría y aprobación (H07/H32). Nulos en comprobantes anteriores a la auditoría.
    creado_por = models.ForeignKey(CustomUser, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    aprobado_por = models.ForeignKey(CustomUser, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    fecha_aprobacion = models.DateTimeField(null=True, blank=True)


class ConsecutivoDocumento(models.Model):
    """Contador por serie documental (P03-06): se bloquea su fila para numerar
    sin duplicados, en vez de MAX(id)+1."""
    serie = models.CharField(max_length=50, unique=True)
    ultimo = models.PositiveIntegerField(default=0)


class ClaveIdempotencia(models.Model):
    """Reintentos seguros (P03-06): misma clave + mismo contenido devuelve la
    respuesta original sin repetir efectos; contenido distinto es conflicto."""
    clave = models.CharField(max_length=100)
    usuario = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='+')
    operacion = models.CharField(max_length=100)
    huella = models.CharField(max_length=64)
    estado_http = models.PositiveSmallIntegerField()
    respuesta = models.JSONField()
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['usuario', 'operacion', 'clave'], name='idempotencia_unica'),
        ]


class RegistroAuditoria(models.Model):
    """Bitácora de acciones sensibles (P02-04, P03-07): quién, cuándo, qué
    objeto, antes/después. No guarda contraseñas ni tokens."""
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    usuario = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='+')
    accion = models.CharField(max_length=60, db_index=True)
    objeto_tipo = models.CharField(max_length=60)
    objeto_id = models.CharField(max_length=60)
    detalle = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-fecha', '-id']

class ProveedorTela(models.Model):
    nombre_empresa = models.CharField(max_length=255, unique=True, default='N/A')
    nombre_encargado = models.CharField(max_length=255, default='N/A')
    contacto = models.CharField(max_length=20, default='0')

    def __str__(self):
        return self.nombre_empresa

class PedidoTela(models.Model):
    ESTADO_CHOICES = [
        ('En fabrica', 'En fabrica'),
        ('En Lottus', 'En Lottus'),
        ('Pendiente', 'Pendiente'),
    ]
    id = models.PositiveIntegerField(primary_key=True)
    usuario = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='pedidos_telas')
    proveedor = models.ForeignKey(ProveedorTela, on_delete=models.PROTECT, related_name='pedidos')
    direccion_entrega = models.TextField()
    fecha_creacion = models.DateField(auto_now_add=True, db_index=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='Pendiente', db_index=True)
    orden_asociada = models.ForeignKey(OrdenPedido, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_telas')
    # Venta directa: un pedido de tela hecho desde la venta puede no tener OP todavía.
    venta = models.ForeignKey(Venta, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_tela')
    observacion = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Pedido Tela {self.id} - {self.proveedor.nombre_empresa}"

class DetallePedidoTela(models.Model):
    pedido = models.ForeignKey(PedidoTela, on_delete=models.CASCADE, related_name='detalles')
    tela = models.TextField() # Changed to TextField as requested
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    observacion = models.TextField(blank=True, null=True)
    linea_venta = models.ForeignKey(LineaVenta, on_delete=models.SET_NULL, null=True, blank=True, related_name='detalles_tela')

    def __str__(self):
        return f"Detalle Tela {self.pedido.id} - {self.tela}"

class DireccionEntrega(models.Model):
    nombre = models.CharField(max_length=100)
    detalles = models.TextField()

    def __str__(self):
        return f"{self.nombre} - {self.detalles}"


# ---------------------------------------------------------------------------
# Comisiones explicables por versión y período (P12-02, F12)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Nómina de asesores (D12a, 2026-10-06). Reemplaza al módulo de comisiones.
# Comisión 3–4 % según el descuento sobre el precio de lista (tabla editable),
# pagadera cuando la venta tiene al menos el 30 % de abono; bonificación del 1 %
# si el asesor cumple la meta, pagadera desde el cierre siguiente a medida que
# las ventas se entregan; salario básico aparte (día 20); ajustes +/-.
# Todo es editable mientras el cierre está en borrador.
# ---------------------------------------------------------------------------

def tabla_comision_por_defecto():
    # [descuento máximo %, comisión %]: "hasta" ese descuento se paga ese porcentaje.
    return [[0, 4.0], [2.5, 3.9], [5, 3.8], [7.5, 3.7], [10, 3.6], [12.5, 3.5],
            [15, 3.4], [17.5, 3.3], [20, 3.2], [22.5, 3.1], [25, 3.0]]


class ConfigNomina(models.Model):
    """Una sola fila con las reglas vigentes; cada cierre copia lo que usa."""
    tabla_comision = models.JSONField(default=tabla_comision_por_defecto)
    abono_minimo_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('30'))
    bonificacion_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1'))
    # Ventas anteriores a esta fecha no generan comisiones (se liquidaron fuera del sistema).
    ventas_desde = models.DateField(null=True, blank=True)
    dia_pago_basico = models.PositiveSmallIntegerField(default=20)
    pago_nomina = models.CharField(max_length=60, default='entre el 6 y el 11')
    actualizado_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    actualizado_en = models.DateTimeField(auto_now=True)


class AsesorNomina(models.Model):
    """Datos fijos de cada asesor: salario básico y meta mensual por defecto."""
    asesor = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='nomina')
    salario_basico = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    meta = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    activo = models.BooleanField(default=True)


class CierreNomina(models.Model):
    ESTADO_CHOICES = [('borrador', 'Borrador'), ('cerrado', 'Cerrado')]
    nombre = models.CharField(max_length=120)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='borrador', db_index=True)
    # Reglas usadas en este cierre (copiadas de ConfigNomina y editables en borrador).
    tabla_comision = models.JSONField(default=tabla_comision_por_defecto)
    abono_minimo_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('30'))
    bonificacion_pct = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1'))
    observacion = models.TextField(blank=True, default='')
    creado_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='+')
    creado_en = models.DateTimeField(auto_now_add=True)
    cerrado_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    cerrado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha_inicio', '-id']
        constraints = [models.CheckConstraint(check=models.Q(fecha_fin__gte=models.F('fecha_inicio')), name='cierre_nomina_fechas')]


class AsesorCierre(models.Model):
    cierre = models.ForeignKey(CierreNomina, on_delete=models.CASCADE, related_name='asesores')
    asesor = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='+')
    salario_basico = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'))
    meta = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    ventas_periodo = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    # None = se calcula (ventas del período >= meta); True/False = decidido a mano.
    cumple_meta_manual = models.BooleanField(null=True, blank=True)
    # Básico y meta vienen de la configuración del asesor y se actualizan al recalcular,
    # salvo que se hayan cambiado a mano en este cierre (2026-10-09).
    basico_manual = models.BooleanField(default=False)
    meta_manual = models.BooleanField(default=False)
    nota = models.TextField(blank=True, default='')
    # La nómina se cierra por asesor (2026-10-08). El estado del cierre general se deriva:
    # cerrado cuando todos sus asesores están cerrados.
    ESTADO_CHOICES = [('abierto', 'Abierto'), ('cerrado', 'Cerrado')]
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='abierto', db_index=True)
    cerrado_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    cerrado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['asesor__first_name', 'asesor__username']
        constraints = [models.UniqueConstraint(fields=['cierre', 'asesor'], name='asesor_unico_por_cierre')]

    @property
    def cumple_meta(self):
        if self.cumple_meta_manual is not None:
            return self.cumple_meta_manual
        return self.meta > 0 and self.ventas_periodo >= self.meta


class LineaNomina(models.Model):
    TIPO_CHOICES = [('comision', 'Comisión'), ('bonificacion', 'Bonificación'), ('ajuste', 'Ajuste')]
    asesor_cierre = models.ForeignKey(AsesorCierre, on_delete=models.CASCADE, related_name='lineas')
    tipo = models.CharField(max_length=15, choices=TIPO_CHOICES)
    venta = models.ForeignKey(Venta, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    # Bonificación: cierre en el que se ganó (se paga en cierres posteriores al entregar).
    causada_en = models.ForeignKey(CierreNomina, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    descripcion = models.CharField(max_length=255, blank=True, default='')
    valor_venta = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    precio_lista = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    origen_precio = models.CharField(max_length=30, blank=True, default='')
    revision_productos = models.PositiveIntegerField(default=0)
    descuento_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    porcentaje = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    valor = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0'))
    abono_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    estado_venta = models.CharField(max_length=20, blank=True, default='')
    participantes = models.PositiveSmallIntegerField(default=1)
    # Se paga en este cierre. False = queda pendiente (aparece de nuevo en el próximo).
    pagar = models.BooleanField(default=True)
    motivo_pendiente = models.CharField(max_length=120, blank=True, default='')
    # Editada a mano: regenerar el cierre no la recalcula.
    editada = models.BooleanField(default=False)
    nota = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['tipo', 'venta_id', 'id']


class ZonaOficinaIA(models.Model):
    nombre = models.CharField(max_length=60)
    descripcion = models.CharField(max_length=160, blank=True, default='')
    ambiente = models.CharField(max_length=16, choices=[('estudio', 'Estudio'), ('showroom', 'Showroom'),
        ('operaciones', 'Operaciones'), ('finanzas', 'Finanzas'), ('gerencia', 'Gerencia'),
        ('oficina', 'Oficina'), ('entrenamiento', 'Entrenamiento'), ('creativo', 'Desarrollo creativo'),
        ('social', 'Zona social')], default='estudio')
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['orden', 'id']


class PerfilAsistente(models.Model):
    """Agente especializado del Chat: quién es y cómo actúa, a qué áreas de datos puede
    consultar y qué documentos de conocimiento usa. Lo crean quienes tienen
    GESTIONAR_PERFILES_IA y lo usan todos los que tienen USAR_ASISTENTE_IA."""
    nombre = models.CharField(max_length=80)
    clave_sistema = models.CharField(max_length=24, null=True, blank=True, unique=True, editable=False)
    rol = models.CharField(max_length=160)
    instrucciones = models.TextField()
    icono = models.CharField(max_length=20, default='robot')
    color = models.CharField(max_length=20, default='azul')
    # Áreas de datos permitidas (claves de asistente.herramientas.AREAS). Vacío = solo conocimiento.
    areas = models.JSONField(default=list, blank=True)
    activo = models.BooleanField(default=True)
    zona = models.ForeignKey(ZonaOficinaIA, on_delete=models.SET_NULL, null=True, blank=True, related_name='agentes')
    # Quién lo ve (2026-10-09): todos los que usan IA, o solo los roles elegidos. Quienes
    # administran perfiles de IA lo ven siempre.
    visible_todos = models.BooleanField(default=True)
    roles_visibles = models.JSONField(default=list, blank=True)
    # Cómo responder según el rol de quien pregunta: {"vendedor": "Sé breve…"}.
    instrucciones_roles = models.JSONField(default=dict, blank=True)
    creado_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre', 'id']


class ConfiguracionAsistente(models.Model):
    """Una sola fila: visibilidad e instrucciones por rol de la IA Lottus general."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    general_visible_todos = models.BooleanField(default=True)
    general_roles_visibles = models.JSONField(default=list, blank=True)
    general_instrucciones_roles = models.JSONField(default=dict, blank=True)
    actualizado = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')


class DocumentoPerfilAsistente(models.Model):
    """Documento de conocimiento de un perfil (.md, .txt o .pdf). Se guarda solo el texto
    extraído, que es lo que lee la IA; el archivo original no se conserva."""
    perfil = models.ForeignKey(PerfilAsistente, on_delete=models.CASCADE, related_name='documentos')
    nombre = models.CharField(max_length=200)
    tipo = models.CharField(max_length=10)
    tamano = models.PositiveIntegerField(default=0)
    texto = models.TextField()
    recortado = models.BooleanField(default=False)
    subido_por = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['creado', 'id']


class ConversacionAsistente(models.Model):
    """Chat del asistente gerencial con IA (Gemini). Cada usuario ve solo las suyas."""
    usuario = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='conversaciones_asistente')
    # Perfil con el que se habla; vacío = IA Lottus general. Se fija al crear la conversación.
    perfil = models.ForeignKey(PerfilAsistente, on_delete=models.SET_NULL, null=True, blank=True, related_name='conversaciones')
    titulo = models.CharField(max_length=120, default='Nueva conversación')
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-actualizada']


class MensajeAsistente(models.Model):
    ROL_CHOICES = [('usuario', 'Usuario'), ('asistente', 'Asistente')]
    conversacion = models.ForeignKey(ConversacionAsistente, on_delete=models.CASCADE, related_name='mensajes')
    rol = models.CharField(max_length=10, choices=ROL_CHOICES)
    texto = models.TextField()
    # Consultas que hizo el asistente a los datos para responder (nombre y argumentos).
    herramientas = models.JSONField(default=list, blank=True)
    modelo = models.CharField(max_length=60, blank=True, default='')
    tokens = models.PositiveIntegerField(null=True, blank=True)
    # La respuesta se genera en segundo plano (gunicorn corta a los 30 s): la página
    # consulta el mensaje hasta que pasa a 'listo' o 'error'.
    ESTADO_CHOICES = [('procesando', 'Procesando'), ('listo', 'Listo'), ('error', 'Error')]
    estado = models.CharField(max_length=12, choices=ESTADO_CHOICES, default='listo')
    error = models.CharField(max_length=500, blank=True, default='')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['creado', 'id']


class AprendizajeAsistente(models.Model):
    """Lo que la IA aprende de cada usuario: valoraciones (me gustó / no me gustó) y notas
    que se agregan a las instrucciones de las siguientes respuestas del mismo perfil."""
    TIPO_CHOICES = [('gusto', 'Me gustó'), ('mejora', 'No me gustó'), ('nota', 'Nota para recordar')]
    usuario = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='aprendizajes_asistente')
    perfil = models.ForeignKey(PerfilAsistente, on_delete=models.CASCADE, null=True, blank=True, related_name='aprendizajes')
    mensaje = models.ForeignKey(MensajeAsistente, on_delete=models.SET_NULL, null=True, blank=True, related_name='aprendizajes')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    texto = models.TextField(blank=True, default='')
    pregunta = models.CharField(max_length=300, blank=True, default='')
    extracto = models.CharField(max_length=300, blank=True, default='')
    activo = models.BooleanField(default=True)
    # 'usuario': lo enseñó la persona; 'equipo': lo aprendió el agente al terminar una tarea.
    origen = models.CharField(max_length=10, default='usuario')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creado', '-id']


class ConexionAcademia(models.Model):
    """La sesión de Google está en almacenamiento privado, nunca en la API o la BD."""
    usuario = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='conexion_academia')
    estado = models.CharField(max_length=20, default='desconectada')
    cuenta = models.CharField(max_length=254, blank=True)
    error = models.CharField(max_length=400, blank=True)
    actualizado = models.DateTimeField(auto_now=True)


class CursoAcademia(models.Model):
    usuario = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='cursos_academia')
    perfil = models.ForeignKey(PerfilAsistente, on_delete=models.SET_NULL, null=True, related_name='cursos_academia')
    mensaje = models.OneToOneField(MensajeAsistente, on_delete=models.SET_NULL, null=True, blank=True, related_name='curso_academia')
    clave = models.UUIDField(unique=True)
    titulo = models.CharField(max_length=160)
    solicitud = models.TextField()
    audiencia = models.CharField(max_length=200, default='Equipo de Lottus')
    numero_modulos = models.PositiveSmallIntegerField(default=3)
    con_videos = models.BooleanField(default=True)
    investigar = models.BooleanField(default=True)
    urls = models.JSONField(default=list, blank=True)
    estado = models.CharField(max_length=20, default='pendiente')
    etapa = models.CharField(max_length=40, default='cuaderno')
    detalle = models.CharField(max_length=400, default='Esperando al coach')
    error = models.CharField(max_length=500, blank=True)
    # Cada paso conserva sus identificadores externos antes de pasar al siguiente.
    datos = models.JSONField(default=dict, blank=True)
    fuentes = models.JSONField(default=list, blank=True)
    modulos = models.JSONField(default=list, blank=True)
    resumen = models.TextField(blank=True)
    eventos = models.JSONField(default=list, blank=True)
    avance = models.PositiveSmallIntegerField(default=0)
    proxima_revision = models.DateTimeField(default=timezone.now)
    reservado_hasta = models.DateTimeField(null=True, blank=True)
    reserva = models.UUIDField(null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-creado', '-id']


class AutomatizacionAsistente(models.Model):
    """Instrucciones programadas de un usuario para un agente; resultados privados."""
    usuario = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='automatizaciones_ia')
    perfil = models.ForeignKey(PerfilAsistente, on_delete=models.SET_NULL, null=True, blank=True, related_name='automatizaciones')
    # Un agente eliminado NO debe convertirse silenciosamente en la IA general.
    es_general = models.BooleanField(default=False)
    perfil_nombre = models.CharField(max_length=80, default='IA Lottus')
    nombre = models.CharField(max_length=80)
    instrucciones = models.TextField()
    modelo = models.CharField(max_length=100, blank=True, default='')
    FRECUENCIAS = [('una_vez', 'Una sola vez'), ('diaria', 'Diariamente'), ('semanal', 'Días de la semana'), ('mensual', 'Mensualmente')]
    frecuencia = models.CharField(max_length=12, choices=FRECUENCIAS, default='semanal')
    hora = models.TimeField()
    dias_semana = models.JSONField(default=list, blank=True)
    dia_mes = models.PositiveSmallIntegerField(default=1)
    fecha_unica = models.DateTimeField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)
    activa = models.BooleanField(default=True)
    archivada = models.BooleanField(default=False)
    proxima_ejecucion = models.DateTimeField(null=True, blank=True, db_index=True)
    creada = models.DateTimeField(auto_now_add=True)
    actualizada = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-creada', '-id']


class EjecucionAutomatizacionIA(models.Model):
    automatizacion = models.ForeignKey(AutomatizacionAsistente, on_delete=models.CASCADE, related_name='ejecuciones')
    # Clave única de franja programada o de intento manual. Nunca se vuelve a llamar
    # al proveedor por reintentar una petición HTTP con la misma clave.
    clave = models.CharField(max_length=120)
    origen = models.CharField(max_length=12, choices=[('programada', 'Programada'), ('manual', 'Manual')])
    programada_para = models.DateTimeField()
    estado = models.CharField(max_length=12, choices=[('pendiente', 'En cola'), ('ejecutando', 'Trabajando'), ('listo', 'Lista'), ('error', 'Error')], default='pendiente', db_index=True)
    nombre = models.CharField(max_length=80)
    instrucciones = models.TextField()
    modelo_solicitado = models.CharField(max_length=100, blank=True, default='')
    modelo_usado = models.CharField(max_length=100, blank=True, default='')
    perfil_id_original = models.BigIntegerField(null=True, blank=True)
    perfil_nombre = models.CharField(max_length=80)
    es_general = models.BooleanField(default=False)
    conversacion = models.ForeignKey(ConversacionAsistente, on_delete=models.SET_NULL, null=True, blank=True, related_name='ejecuciones_ia')
    respuesta = models.ForeignKey(MensajeAsistente, on_delete=models.SET_NULL, null=True, blank=True, related_name='ejecuciones_ia')
    resultado = models.TextField(blank=True, default='')
    error = models.CharField(max_length=500, blank=True, default='')
    leida = models.BooleanField(default=False)
    creada = models.DateTimeField(auto_now_add=True)
    iniciada = models.DateTimeField(null=True, blank=True)
    finalizada = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creada', '-id']
        constraints = [models.UniqueConstraint(fields=['automatizacion', 'clave'], name='ejecucion_ia_unica')]


class MotorAutomatizacionesIA(models.Model):
    nombre = models.CharField(max_length=20, primary_key=True, default='principal')
    ultimo_latido = models.DateTimeField()


class TrabajoAgenteIA(models.Model):
    """Ejecución privada solicitada desde el chat; conserva operaciones y resultados."""
    origen = models.OneToOneField(MensajeAsistente, on_delete=models.PROTECT, related_name='trabajo_agente')
    usuario = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='+')
    agente = models.ForeignKey(PerfilAsistente, on_delete=models.SET_NULL, null=True, related_name='+')
    solicitud = models.TextField()
    contexto_usuario = models.JSONField(default=list, blank=True)
    continuacion_de = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='continuaciones')
    estado = models.CharField(max_length=16, default='pendiente', db_index=True,
        choices=[('pendiente','En cola'),('ejecutando','Ejecutando'),('listo','Terminado'),
                 ('necesita_datos','Necesita datos'),('error','Error')])
    pasos = models.JSONField(default=list, blank=True)
    resultado = models.TextField(blank=True)
    error = models.CharField(max_length=500, blank=True)
    conversacion = models.ForeignKey(ConversacionAsistente, on_delete=models.SET_NULL, null=True, related_name='+')
    respuesta = models.ForeignKey(MensajeAsistente, on_delete=models.SET_NULL, null=True, related_name='+')
    creado = models.DateTimeField(auto_now_add=True)
    iniciado = models.DateTimeField(null=True, blank=True)
    finalizado = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-creado','-id']


class MensajeEquipoIA(models.Model):
    """Conversación entre agentes (IA Lottus ↔ Alan, consultas entre colegas, informes).

    Cada mensaje pertenece al usuario cuya solicitud lo originó: los hilos son privados
    como sus chats. de/para: 'ia-general' o 'ia-<perfil>'."""
    TIPOS = [('solicitud', 'Solicitud'), ('avance', 'Avance'), ('resultado', 'Resultado'), ('respuesta', 'Respuesta'),
             ('consulta', 'Consulta'), ('aprendizaje', 'Aprendizaje')]
    usuario = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='+')
    de = models.CharField(max_length=40)
    para = models.CharField(max_length=40)
    tipo = models.CharField(max_length=12, choices=TIPOS)
    texto = models.TextField()
    trabajo = models.ForeignKey(TrabajoAgenteIA, on_delete=models.SET_NULL, null=True, blank=True, related_name='mensajes_equipo')
    conversacion = models.ForeignKey(ConversacionAsistente, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    creado = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['id']
        indexes = [models.Index(fields=['usuario', 'de', 'para'])]


class ConfiguracionOficina(models.Model):
    """Una oficina compartida; se configura explícitamente, nunca al consultar."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    responsable = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='+')
    revision = models.PositiveIntegerField(default=1)


class MiembroOficina(models.Model):
    usuario = models.OneToOneField(CustomUser, on_delete=models.PROTECT, related_name='membresia_oficina')
    habilitado = models.BooleanField(default=True)
    zona = models.ForeignKey(ZonaOficinaIA, on_delete=models.SET_NULL, null=True, blank=True, related_name='personas')
    puesto = models.PositiveSmallIntegerField(null=True, blank=True)
    estado = models.CharField(max_length=12, default='disponible', choices=[('disponible','Disponible'),('ocupado','Ocupado'),('ausente','Ausente')])
    nota_estado = models.CharField(max_length=100, blank=True, default='')
    ultima_presencia = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['zona','puesto'], name='oficina_puesto_persona_unico')]


class MensajeOficina(models.Model):
    autor = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='+')
    destinatario = models.ForeignKey(CustomUser, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    texto = models.TextField(max_length=2000)
    destacado_hasta = models.DateTimeField(null=True, blank=True)
    archivado = models.BooleanField(default=False)
    leido_en = models.DateTimeField(null=True, blank=True)
    creado = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-id']


class TrabajoOficina(models.Model):
    tipo = models.CharField(max_length=12, choices=[('tarea','Tarea'),('solicitud','Solicitud')])
    creador = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='+')
    responsable = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='+')
    titulo = models.CharField(max_length=140)
    descripcion = models.TextField(max_length=3000, blank=True, default='')
    prioridad = models.CharField(max_length=8, default='normal', choices=[('normal','Normal'),('alta','Alta')])
    estado = models.CharField(max_length=12, default='pendiente', choices=[('pendiente','Pendiente'),('en_curso','En curso'),('bloqueada','Bloqueada'),('hecha','Hecha'),('cancelada','Cancelada')])
    fecha_limite = models.DateField(null=True, blank=True)
    venta = models.ForeignKey(Venta, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    revision = models.PositiveIntegerField(default=1)
    creado = models.DateTimeField(default=timezone.now)
    actualizado = models.DateTimeField(default=timezone.now)
    entregado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-actualizado','-id']


class ComentarioTrabajoOficina(models.Model):
    trabajo = models.ForeignKey(TrabajoOficina, on_delete=models.CASCADE, related_name='comentarios')
    autor = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='+')
    texto = models.TextField(max_length=2000)
    es_cambio_estado = models.BooleanField(default=False)
    creado = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['id']


class CoordinacionOficina(models.Model):
    """Programa compartido de gerencia, separado de las automatizaciones privadas."""
    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    destinatarios = models.ManyToManyField(CustomUser, related_name='+')
    # {zona_id: perfil_id}; las áreas sin líder se identifican, no se simulan.
    lideres = models.JSONField(default=dict)
    activa = models.BooleanField(default=False)
    hora_inicio = models.TimeField(default='09:50')
    hora_fin = models.TimeField(default='18:50')
    dias = models.JSONField(default=list)
    modelo = models.CharField(max_length=100, default='', blank=True)
    proxima_ejecucion = models.DateTimeField(null=True, blank=True, db_index=True)
    revision = models.PositiveIntegerField(default=1)


class InformeAreas(models.Model):
    clave = models.CharField(max_length=120, unique=True)
    solicitado_por = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='+')
    destinatarios = models.ManyToManyField(CustomUser, related_name='+')
    respuesta = models.OneToOneField(MensajeAsistente, on_delete=models.SET_NULL, null=True, blank=True, related_name='informe_areas')
    origen = models.CharField(max_length=12, default='manual')
    estado = models.CharField(max_length=12, default='pendiente', db_index=True)
    etapa = models.CharField(max_length=160, default='Esperando al coordinador')
    programado_para = models.DateTimeField(default=timezone.now)
    creado = models.DateTimeField(default=timezone.now)
    iniciado = models.DateTimeField(null=True, blank=True)
    finalizado = models.DateTimeField(null=True, blank=True)
    # Evidencia fechada y análisis de cada líder. Nunca se sobrescribe un informe.
    datos = models.JSONField(default=dict)
    resumen = models.TextField(blank=True, default='')
    error = models.CharField(max_length=500, blank=True, default='')

    class Meta:
        ordering = ['-id']


class InteraccionOficina(models.Model):
    """Eventos de negocio duraderos. El plano anima estos hechos, sin ejecutarlos."""
    actor = models.CharField(max_length=40)  # ia-general / ia-<id> / persona-<id>
    destino = models.CharField(max_length=40)
    tipo = models.CharField(max_length=20)
    texto = models.CharField(max_length=160)  # solo aviso genérico, sin contenido privado
    informe = models.ForeignKey(InformeAreas, on_delete=models.CASCADE, null=True, related_name='interacciones')
    trabajo = models.ForeignKey(TrabajoOficina, on_delete=models.CASCADE, null=True, related_name='interacciones')
    ejecucion = models.ForeignKey(EjecucionAutomatizacionIA, on_delete=models.CASCADE, null=True, blank=True, related_name='interacciones')
    conversacion = models.ForeignKey(ConversacionAsistente, on_delete=models.CASCADE, null=True, blank=True, related_name='interacciones')
    creado = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['id']
