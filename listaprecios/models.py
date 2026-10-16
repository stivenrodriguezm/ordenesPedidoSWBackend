from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone


class CategoriaLista(models.Model):
    """Un "tipo de producto" del catálogo (ej. "Salas", "Comedores",
    "Alcobas") — solo agrupa/etiqueta variantes por tipo de mueble (y
    permite asignar un multiplicador en bloque por categoría). NO define
    ningún precio: el precio por metro de cada grupo de tela es el mismo
    para todas las categorías (ver GrupoTela.precio_por_metro), y el
    multiplicador de margen tampoco vive aquí (ver Multiplicador) — es un
    catálogo aparte, totalmente independiente de la categoría. Una misma
    colección (LineaProducto) puede tener variantes de varios tipos de
    producto distintos (ej. la colección "Altus" puede tener una Poltrona y
    un Sofá de 3, cada uno con su propia categoría) — por eso esta FK vive
    en VarianteProducto, no en LineaProducto."""
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Nombre")
    slug = models.SlugField(max_length=120, unique=True, verbose_name="Slug")
    orden = models.PositiveIntegerField(default=0, verbose_name="Orden")
    activo = models.BooleanField(default=True, verbose_name="Activo")

    class Meta:
        db_table = 'listaprecios_categoria'
        ordering = ['orden', 'nombre']
        verbose_name = 'Categoría de Lista de Precios'
        verbose_name_plural = 'Categorías de Lista de Precios'

    def __str__(self):
        return self.nombre


class Multiplicador(models.Model):
    """Catálogo de multiplicadores de margen, con nombre libre elegido por
    el administrador (ej. "General", "Mayorista", "Promoción Verano") — NO
    está atado a categorías ni a ningún otro dato: es una entidad propia
    que cualquier variante puede usar.

    Exactamente uno debe estar marcado es_general=True — es el que usan por
    defecto casi todas las variantes (VarianteProducto.multiplicador nulo).
    Marcar otro como general desmarca automáticamente al anterior (ver
    services.establecer_multiplicador_general)."""
    nombre = models.CharField(max_length=100, unique=True, verbose_name="Nombre")
    valor = models.DecimalField(max_digits=6, decimal_places=3, verbose_name="Valor")
    es_general = models.BooleanField(default=False, verbose_name="Es el multiplicador general (por defecto)")
    orden = models.PositiveIntegerField(default=0, verbose_name="Orden")

    class Meta:
        db_table = 'listaprecios_multiplicador'
        ordering = ['orden', 'nombre']
        verbose_name = 'Multiplicador'
        verbose_name_plural = 'Multiplicadores'

    def __str__(self):
        return f"{self.nombre} (×{self.valor})"


class GrupoTela(models.Model):
    """Catálogo global de grupos de tela/cuero ("Grupo 1"…"Grupo 5", "Cuero
    Nacional", "Cuero Importado"...). Es un rango de precio por unidad, no
    una tela/cuero específica — ver §2.2 del plan (lista_precios.md). El
    catálogo se administra a mano desde Lista de Precios → Matriz de
    Grupos: no hay grupos sembrados por código más allá de los que ya
    existían.

    precio_por_metro es el mismo para cualquier tipo de producto — NO
    depende de la categoría (corrección explícita del usuario: la categoría
    solo agrupa/etiqueta el tipo de mueble, nunca definió un precio
    distinto por grupo aunque los datos migrados del Excel sí traían
    valores diferentes por categoría; se unificaron a un solo valor por
    grupo). tipo decide la unidad de medida (ver unidad_medida): los grupos
    de tela se cotizan por metro, los de cuero por decímetro."""
    TIPO_CHOICES = [
        ('tela', 'Tela'),
        ('cuero', 'Cuero'),
    ]
    nombre = models.CharField(max_length=50, unique=True, verbose_name="Nombre")
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='tela', verbose_name="Tipo de material")
    precio_por_metro = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Precio por metro")
    orden = models.PositiveIntegerField(default=0, verbose_name="Orden")

    class Meta:
        db_table = 'listaprecios_grupo_tela'
        ordering = ['orden', 'nombre']
        verbose_name = 'Grupo de Tela'
        verbose_name_plural = 'Grupos de Tela'

    @property
    def unidad_medida(self):
        return 'decímetro' if self.tipo == 'cuero' else 'metro'

    def __str__(self):
        return f"{self.nombre} (${self.precio_por_metro}/{self.unidad_medida})"


class LineaProducto(models.Model):
    """Una colección de producto (ej. "Detroit", "Altus"). Ya NO pertenece a
    una sola categoría — puede agrupar variantes de distintos tipos de
    producto (ej. Altus → Poltrona + Sofá de 2 + Sofá de 3, cada una con su
    propia categoría/precio en VarianteProducto)."""
    referencia = models.OneToOneField('ordenes.Referencia', on_delete=models.PROTECT, null=True, blank=True, related_name='lista_precios')
    es_decorativo = models.BooleanField(default=False)
    # Nombre/slug anteriores se conservan para documentos históricos. La UI lee Referencia.
    nombre = models.CharField(max_length=150, verbose_name="Nombre")
    slug = models.SlugField(max_length=180, unique=True, verbose_name="Slug")
    notas = models.TextField(blank=True, default='', verbose_name="Notas")
    fotos = models.JSONField(default=list, blank=True, verbose_name="Fotos")
    activo = models.BooleanField(default=True, verbose_name="Activo")
    orden = models.PositiveIntegerField(default=0, verbose_name="Orden")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Creación")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última Actualización")

    class Meta:
        db_table = 'listaprecios_linea_producto'
        ordering = ['orden', 'nombre']
        verbose_name = 'Línea de Producto'
        verbose_name_plural = 'Líneas de Producto'

    def __str__(self):
        return self.nombre


class VarianteProducto(models.Model):
    """Un ítem orderable dentro de una línea (ej. "Sofá 3p. (235cm.)" o
    "Poltrona") — equivale a una subcategoría/tipo de mueble. Tiene su
    propia categoría (solo etiqueta el tipo de mueble, no afecta el precio)
    porque una misma colección puede combinar varios tipos de producto.
    metraje_tela nulo = el producto no lleva tela (mesas, accesorios).
    notas: lista de consideraciones o variaciones puntuales de este ítem
    (ej. "en cuero incluye base metálica"), visibles al buscar el precio —
    puede haber ninguna, una o varias.

    multiplicador nulo (el caso normal, casi todos los productos) = usa el
    multiplicador marcado es_general=True del catálogo Multiplicador. Se
    puede asignar cualquier otro multiplicador del catálogo a esta variante
    puntual, o en bloque por categoría/línea (ver
    services.asignar_multiplicador_masivo)."""
    linea = models.ForeignKey(LineaProducto, on_delete=models.CASCADE, related_name='variantes')
    categoria = models.ForeignKey(CategoriaLista, on_delete=models.PROTECT, related_name='variantes', null=True, blank=True)
    categoria_referencia = models.ForeignKey('suministros.Categoria', on_delete=models.PROTECT, related_name='variantes_precio', null=True, blank=True)
    subcategoria = models.ForeignKey('suministros.Subcategoria', on_delete=models.PROTECT, related_name='variantes_precio', null=True, blank=True)
    nombre = models.CharField(max_length=150, verbose_name="Nombre")
    orden = models.PositiveIntegerField(default=0, verbose_name="Orden")
    costo_base = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Costo base")
    metraje_tela = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Metraje de tela (mt.)"
    )
    decimetraje_cuero = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Consumo de cuero (decímetros)"
    )
    notas = models.JSONField(default=list, blank=True, verbose_name="Notas")
    multiplicador = models.ForeignKey(
        Multiplicador, on_delete=models.PROTECT, null=True, blank=True, related_name='variantes',
        verbose_name="Multiplicador (vacío = usar el general)",
    )
    descuento_maximo = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Descuento máximo (%)"
    )

    class Meta:
        db_table = 'listaprecios_variante_producto'
        ordering = ['orden', 'id']
        verbose_name = 'Variante de Producto'
        verbose_name_plural = 'Variantes de Producto'

    def __str__(self):
        return f"{self.nombre} — {self.linea.nombre}"


class CargoVariante(models.Model):
    """Cargo adicional con nombre libre (transporte, instalación, "Sin
    tapa"...). Reemplaza los números sueltos hardcodeados en las fórmulas
    del Excel (§2.2/§2.5). El valor puede ser negativo. Se suma ANTES del
    multiplicador, igual que costo_base y el metraje de tela.

    opcional=False (por defecto): cargo fijo, siempre incluido en el precio
    de lista — costo interno, no se expone al vendedor (igual que
    costo_base/metraje_tela).
    opcional=True: extra que el vendedor puede activar/desactivar al
    cotizar (ej. "Tomacorriente USB", "Transporte fuera de Bogotá") — SÍ se
    expone (descripción + valor) en el catálogo de vendedor, porque es un
    ítem de venta, no un costo interno."""
    variante = models.ForeignKey(VarianteProducto, on_delete=models.CASCADE, related_name='cargos')
    descripcion = models.CharField(max_length=200, verbose_name="Descripción")
    valor = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Valor")
    opcional = models.BooleanField(default=False, verbose_name="Opcional (seleccionable al cotizar)")
    # Estado en la lista (2026-10-15): «Opcional habilitado» = opcional que aparece ya
    # seleccionado al cotizar; «Opcional deshabilitado» = opcional sin seleccionar;
    # «Obligatorio» = opcional False (siempre en el precio). Solo aplica a opcionales.
    preseleccionado = models.BooleanField(default=False, verbose_name="Opcional seleccionado de entrada")
    # Si viene de una variante especial del juego (EspecialLinea), se administra desde ella.
    especial = models.ForeignKey('EspecialLinea', on_delete=models.CASCADE, null=True, blank=True, related_name='cargos')
    # «Cojines incluidos» (2026-10-15): cargo fijo «Decorativos x2», sin valor ni edición.
    # Cada unidad del producto da derecho a 2 productos de la línea Decorativos sin cobro
    # (en grupo 1 o 2; de grupo 3 en adelante se cobra la diferencia). Ver decorativos.py.
    TIPO_DECORATIVOS = 'decorativos'
    TIPO_DIFERENCIA_PRECIO = 'diferencia_precio'
    TIPO_ESPECIAL_CONFIGURABLE = 'especial_producto'
    TIPO_CHOICES = [('', 'Cargo'), (TIPO_DECORATIVOS, 'Cojines incluidos (Decorativos x2)'),
                    (TIPO_DIFERENCIA_PRECIO, 'Diferencia sobre precio de venta'),
                    (TIPO_ESPECIAL_CONFIGURABLE, 'Especial con costo y multiplicador')]
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, blank=True, default='')
    configuracion_especial = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'listaprecios_cargo_variante'
        ordering = ['id']
        verbose_name = 'Cargo de Variante'
        verbose_name_plural = 'Cargos de Variante'

    def __str__(self):
        return f"{self.descripcion} (${self.valor})"


class EspecialLinea(models.Model):
    """Variante especial de un juego/estilo (2026-10-09): una opción que se le agrega a sus
    productos, p. ej. «Reclinables eléctricos» en una línea de sofás. Se guarda como un
    cargo opcional (CargoVariante.especial) en cada variante a la que aplica, con su propio
    valor por variante; así cotizaciones, ventas y precios la usan como cualquier opcional."""
    linea = models.ForeignKey(LineaProducto, on_delete=models.CASCADE, related_name='especiales')
    nombre = models.CharField(max_length=120, verbose_name="Nombre")
    descripcion = models.CharField(max_length=300, blank=True, default='', verbose_name="Descripción")
    valor = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Valor (costo) por defecto")
    orden = models.PositiveIntegerField(default=0)
    # Vacío conserva el cálculo histórico; las nuevas opciones guardan costo, múltiplo y consumos.
    configuracion = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = 'listaprecios_especial_linea'
        ordering = ['orden', 'id']

    def __str__(self):
        return f"{self.nombre} — {self.linea.nombre}"


class EspecialCatalogo(models.Model):
    """Biblioteca común de configuraciones, independiente de sus copias en colecciones."""
    nombre = models.CharField(max_length=120)
    configuracion = models.JSONField(default=dict)
    huella = models.CharField(max_length=64, unique=True)
    origen = models.CharField(max_length=300, blank=True, default='')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'listaprecios_especial_catalogo'
        ordering = ['nombre', '-id']


class ComponenteJuego(models.Model):
    """Juego compuesto (2026-10-09): una variante armada con otras de la misma línea, p. ej.
    «Comedor 6 puestos» = 1 Mesa de 6 + 6 Sillas de comedor. En ventas es un solo producto;
    su precio es la suma de los componentes (más sus propios cargos)."""
    juego = models.ForeignKey(VarianteProducto, on_delete=models.CASCADE, related_name='componentes')
    variante = models.ForeignKey(VarianteProducto, on_delete=models.PROTECT, related_name='en_juegos')
    cantidad = models.PositiveIntegerField(default=1)
    orden = models.PositiveIntegerField(default=0)
    costo_unitario = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name='Costo base unitario solo en este conjunto',
    )
    multiplicador = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True,
        verbose_name='Multiplicador solo en este conjunto',
    )
    adicionales = models.JSONField(default=list, blank=True, verbose_name='Cargos y especiales solo en este conjunto')

    class Meta:
        db_table = 'listaprecios_componente_juego'
        ordering = ['orden', 'id']
        constraints = [models.UniqueConstraint(fields=['juego', 'variante'], name='componente_unico_por_juego')]

    def __str__(self):
        return f"{self.cantidad} × {self.variante.nombre} en {self.juego.nombre}"


class PrecioVariante(models.Model):
    """Una fila por cada grupo de tela aplicable a una variante (grupo nulo
    = precio único, no varía por tela). precio_manual nulo = se calcula con
    la fórmula (calcular_precio en services.py); si tiene valor, se usa tal
    cual — respeta los ~60 casos "a mano" que ya existen hoy en el Excel."""
    variante = models.ForeignKey(VarianteProducto, on_delete=models.CASCADE, related_name='precios')
    grupo = models.ForeignKey(
        GrupoTela, on_delete=models.CASCADE, null=True, blank=True, related_name='precios_variante'
    )
    precio_manual = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Precio fijado manualmente"
    )

    class Meta:
        db_table = 'listaprecios_precio_variante'
        constraints = [
            models.UniqueConstraint(fields=['variante', 'grupo'], name='unique_variante_grupo'),
        ]
        ordering = ['grupo__orden']
        verbose_name = 'Precio de Variante'
        verbose_name_plural = 'Precios de Variante'

    def __str__(self):
        grupo_nombre = self.grupo.nombre if self.grupo else 'Único'
        return f"{self.variante.nombre} / {grupo_nombre}"


class Cotizacion(models.Model):
    """Documento persistente de cotización (P09-01 / F01).
    Conserva la snapshot de precios aceptados, opciones y cálculo para que no
    cambien silenciosamente si se modifican costos o multiplicadores del catálogo.
    Las cotizaciones en estado 'aceptada' o 'convertida' quedan protegidas contra edición."""
    ESTADO_BORRADOR = 'borrador'
    ESTADO_EMITIDA = 'emitida'
    ESTADO_ACEPTADA = 'aceptada'
    ESTADO_CONVERTIDA = 'convertida'
    ESTADO_VENCIDA = 'vencida'
    ESTADO_RECHAZADA = 'rechazada'
    ESTADO_CHOICES = [
        (ESTADO_BORRADOR, 'Borrador'),
        (ESTADO_EMITIDA, 'Emitida'),
        (ESTADO_ACEPTADA, 'Aceptada'),
        (ESTADO_CONVERTIDA, 'Convertida'),
        (ESTADO_VENCIDA, 'Vencida'),
        (ESTADO_RECHAZADA, 'Rechazada'),
    ]

    numero = models.CharField(max_length=50, unique=True, db_index=True, verbose_name="Número de Cotización")
    cliente = models.ForeignKey(
        'ordenes.Cliente', on_delete=models.SET_NULL, null=True, blank=True, related_name='cotizaciones'
    )
    cliente_nombre = models.CharField(max_length=255, blank=True, default='', verbose_name="Nombre del Cliente")
    cliente_documento = models.CharField(max_length=50, blank=True, default='', verbose_name="Documento del Cliente")
    cliente_telefono = models.CharField(max_length=50, blank=True, default='', verbose_name="Teléfono del Cliente")
    cliente_email = models.CharField(max_length=150, blank=True, default='', verbose_name="Email del Cliente")
    asesor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='cotizaciones'
    )
    asesor_nombre = models.CharField(max_length=255, blank=True, default='', verbose_name="Nombre del Asesor")
    fecha_creacion = models.DateTimeField(auto_now_add=True, db_index=True)
    fecha_vencimiento = models.DateField(null=True, blank=True, db_index=True)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=ESTADO_EMITIDA, db_index=True)
    version = models.PositiveIntegerField(default=1, verbose_name="Versión (control de concurrencia)")
    version_calculo = models.CharField(max_length=50, default='v1.0', verbose_name="Versión de Cálculo")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    descuento = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    descuento_porcentaje = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    notas = models.TextField(blank=True, default='', verbose_name="Notas / Términos")
    venta_asociada = models.ForeignKey(
        'ordenes.Venta', on_delete=models.SET_NULL, null=True, blank=True, related_name='cotizaciones'
    )
    fecha_conversion = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'listaprecios_cotizacion'
        ordering = ['-id']
        verbose_name = 'Cotización'
        verbose_name_plural = 'Cotizaciones'

    def __str__(self):
        return f"{self.numero} - {self.cliente_nombre or 'Sin cliente'} (${self.total})"


class LineaCotizacion(models.Model):
    """Línea de cotización con snapshot de precio, producto y opciones."""
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.CASCADE, related_name='lineas')
    variante = models.ForeignKey(
        VarianteProducto, on_delete=models.SET_NULL, null=True, blank=True, related_name='lineas_cotizacion'
    )
    linea_nombre = models.CharField(max_length=150, verbose_name="Línea / Colección")
    variante_nombre = models.CharField(max_length=150, verbose_name="Variante / Producto")
    categoria_nombre = models.CharField(max_length=100, blank=True, default='', verbose_name="Categoría")
    grupo_tela = models.ForeignKey(
        GrupoTela, on_delete=models.SET_NULL, null=True, blank=True, related_name='lineas_cotizacion'
    )
    grupo_nombre = models.CharField(max_length=100, blank=True, default='', verbose_name="Grupo de Tela")
    cantidad = models.PositiveIntegerField(default=1, verbose_name="Cantidad")
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Precio Unitario")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, verbose_name="Subtotal")
    costo_estimado = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Costo estimado unitario"
    )
    opcionales = models.JSONField(default=list, blank=True, verbose_name="Opcionales seleccionados")
    notas = models.TextField(blank=True, default='', verbose_name="Notas del ítem")
    foto = models.URLField(max_length=500, blank=True, null=True, verbose_name="Foto referencial")
    # Parte del precio cubierta por los «Decorativos x2» de otro producto de la cotización.
    incluido = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="Valor incluido")

    class Meta:
        db_table = 'listaprecios_linea_cotizacion'
        ordering = ['id']
        verbose_name = 'Línea de Cotización'
        verbose_name_plural = 'Líneas de Cotización'

    def __str__(self):
        return f"{self.cantidad}x {self.linea_nombre} - {self.variante_nombre} (${self.subtotal})"
