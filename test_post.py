import sys
import json
import urllib.request

url = 'http://localhost:8000/suministros/remisiones/'
headers = {'Content-Type': 'application/json'}
data = {
    "fecha_entrega": None,
    "hora_desde": None,
    "hora_hasta": None,
    "direccion_entrega": "Test",
    "ciudad": "Test",
    "barrio": "Test",
    "orden_asociada": None,
    "estado": "creada",
    "sin_saldo": True,
    "saldo": 0,
    "metodo_pago": "",
    "transportador_usuario": None,
    "transportador": "",
    "vendedor": None,
    "observacion": "Test",
    "cliente_nombre": "Cliente Nuevo",
    "inventario_items": []
}

req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
try:
    with urllib.request.urlopen(req) as response:
        print("Success:", response.read().decode())
except urllib.error.HTTPError as e:
    print("HTTP Error:", e.code, e.read().decode())
except Exception as e:
    print("Error:", str(e))
