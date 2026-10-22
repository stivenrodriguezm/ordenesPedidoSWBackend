from django.urls import path
from . import views as v

urlpatterns = [
    path('beneficiarios/', v.beneficiarios), path('revisar-ce/', v.revisar_ce),
    path('comprobantes/<int:pk>/beneficiario/', v.asociar_ce),
    path('catalogo/', v.catalogo), path('cuentas/', v.cuentas), path('cuentas/<int:pk>/', v.cuenta),
    path('empleados/', v.empleados), path('empleados/<int:pk>/', v.empleado),
    path('pendientes/', v.pendientes), path('lotes/', v.lotes), path('lotes/<int:pk>/', v.lote),
    path('lotes/<int:pk>/archivo/', v.archivo), path('lotes/<int:pk>/anular/', v.anular),
    path('lotes/<int:pk>/corregir/', v.corregir),
    path('lotes/<int:pk>/confirmar/', v.confirmar),
    path('lotes/<int:pk>/reintentar/', v.reintentar),
    path('programacion/', v.programacion),
]
