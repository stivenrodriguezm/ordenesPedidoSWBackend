from django.urls import path
from . import views as v

urlpatterns = [
    path('impresoras/', v.impresoras),
    path('trabajos/', v.crear_trabajo),
    path('trabajos/<int:pk>/', v.trabajo),
    path('agente/siguiente/', v.agente_siguiente),
    path('agente/trabajos/<int:pk>/', v.agente_reportar),
]
