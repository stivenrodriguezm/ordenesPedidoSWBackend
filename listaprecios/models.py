from django.db import models


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
    categoria = models.ForeignKey(CategoriaLista, on_delete=models.PROTECT, related_name='variantes')
    nombre = models.CharField(max_length=150, verbose_name="Nombre")
    orden = models.PositiveIntegerField(default=0, verbose_name="Orden")
    costo_base = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="Costo base")
    metraje_tela = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True, verbose_name="Metraje de tela (mt.)"
    )
    notas = models.JSONField(default=list, blank=True, verbose_name="Notas")
    multiplicador = models.ForeignKey(
        Multiplicador, on_delete=models.PROTECT, null=True, blank=True, related_name='variantes',
        verbose_name="Multiplicador (vacío = usar el general)",
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

    class Meta:
        db_table = 'listaprecios_cargo_variante'
        ordering = ['id']
        verbose_name = 'Cargo de Variante'
        verbose_name_plural = 'Cargos de Variante'

    def __str__(self):
        return f"{self.descripcion} (${self.valor})"


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
