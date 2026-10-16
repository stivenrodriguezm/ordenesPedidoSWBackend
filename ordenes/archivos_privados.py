"""Solo para las migraciones históricas 0046/0048 de posventa, que referencian
este almacén. El módulo Posventa se eliminó por decisión del usuario
(2026-10-06, D-ALCANCE en docs/auditoria-2026-10-02/decisiones.md): no volver a crearlo."""
from django.core.files.storage import FileSystemStorage


def almacen_evidencias():
    return FileSystemStorage()
