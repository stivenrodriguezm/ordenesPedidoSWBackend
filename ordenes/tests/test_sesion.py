"""Sesión: rotación y revocación del refresh token (P02-05, H28)."""
from django.test import TestCase
from rest_framework.test import APIClient

from ordenes.models import CustomUser


class SesionTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create(username='u', role='vendedor')
        self.user.set_password('Clave-segura-123')
        self.user.save()
        self.c = APIClient()

    def login(self):
        r = self.c.post('/api/token/', {'username': 'u', 'password': 'Clave-segura-123'}, format='json')
        self.assertEqual(r.status_code, 200)
        return r.data

    def test_refresh_rota_y_el_anterior_queda_revocado(self):
        t = self.login()
        r1 = self.c.post('/api/token/refresh/', {'refresh': t['refresh']}, format='json')
        self.assertEqual(r1.status_code, 200)
        self.assertIn('refresh', r1.data)
        r2 = self.c.post('/api/token/refresh/', {'refresh': t['refresh']}, format='json')
        self.assertEqual(r2.status_code, 401)

    def test_logout_revoca_el_refresh(self):
        t = self.login()
        self.assertEqual(self.c.post('/api/logout/', {'refresh': t['refresh']}, format='json').status_code, 200)
        self.assertEqual(self.c.post('/api/token/refresh/', {'refresh': t['refresh']}, format='json').status_code, 401)

    def test_usuario_desactivado_no_renueva(self):
        t = self.login()
        self.user.is_active = False
        self.user.save()
        r = self.c.post('/api/token/refresh/', {'refresh': t['refresh']}, format='json')
        self.assertEqual(r.status_code, 401)
