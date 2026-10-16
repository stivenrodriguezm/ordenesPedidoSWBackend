"""Salud del servicio para el despliegue y el monitoreo (P07-04/P07-07).

No expone datos sensibles: solo confirma que el proceso responde y que la base
acepta una consulta trivial."""
from django.db import connection
from django.http import JsonResponse


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        return JsonResponse({'status': 'error', 'database': 'unavailable'}, status=503)
    return JsonResponse({'status': 'ok', 'database': 'ok'})
