# Guía de Despliegue en Producción - Backend Django (`api.muebleslottus.com`)

Esta guía describe el procedimiento oficial para desplegar el backend de **Lottus** en un servidor **Ubuntu** vía SSH, sirviendo la API desde `https://api.muebleslottus.com` para el cliente en `https://app.muebleslottus.com`.

---

## 1. Requisitos Previos en el Servidor Ubuntu

Conéctate al servidor vía SSH e instala las dependencias base del sistema:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pip python3-venv git nginx certbot python3-certbot-nginx libmysqlclient-dev
```

---

## 2. Clonar y Configurar el Proyecto

1. **Ubicar e ingresar al directorio:**
   ```bash
   cd /var/www
   sudo git clone https://github.com/stivenrodriguezm/ordenesPedidoSWBackend.git backend
   sudo chown -R $USER:$USER /var/www/backend
   cd /var/www/backend
   ```

2. **Crear y activar entorno virtual:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. **Configurar el archivo `.env` de producción:**
   ```bash
   cp .env.example .env
   nano .env
   ```
   *Asegúrate de configurar `DJANGO_DEBUG=False` y ajustar la clave `DJANGO_SECRET_KEY`.*

4. **Ejecutar migraciones y recolectar archivos estáticos:**
   ```bash
   python manage.py migrate
   python manage.py collectstatic --noinput
   ```

---

## 3. Configurar Gunicorn como Servicio Systemd

Crea el archivo de servicio para que Gunicorn se ejecute automáticamente en segundo plano:

```bash
sudo nano /etc/systemd/system/gunicorn.service
```

Pega el siguiente contenido (ajustando la ruta si es necesario):

```ini
[Unit]
Description=Gunicorn daemon for Lottus Backend API
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/var/www/backend
ExecStart=/var/www/backend/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 lottusPedidos.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
```

Inicia y habilita el servicio:

```bash
sudo systemctl daemon-reload
sudo systemctl start gunicorn
sudo systemctl enable gunicorn
sudo systemctl status gunicorn
```

---

## 4. Configurar Nginx como Reverse Proxy con SSL (HTTPS)

Crea el archivo de configuración para el sitio `api.muebleslottus.com`:

```bash
sudo nano /etc/nginx/sites-available/api.muebleslottus.com
```

Pega la siguiente configuración:

```nginx
server {
    server_name api.muebleslottus.com;

    client_max_body_size 20M;

    location /static/ {
        alias /var/www/backend/staticfiles/;
    }

    location /media/ {
        alias /var/www/backend/media/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Habilita el sitio en Nginx y verifica la sintaxis:

```bash
sudo ln -s /etc/nginx/sites-available/api.muebleslottus.com /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## 5. Habilitar Certificado SSL Gratuito con Let's Encrypt (HTTPS)

Ejecuta Certbot para obtener e instalar el certificado de forma automática:

```bash
sudo certbot --nginx -d api.muebleslottus.com
```

Certbot actualizará automáticamente la configuración de Nginx redirigiendo HTTP a HTTPS en `https://api.muebleslottus.com`.

---

## 6. Verificación Final de CORS

Prueba la conexión desde `https://app.muebleslottus.com` hacia `https://api.muebleslottus.com/api/token/`. 
Las cabeceras CORS pre-configuradas responderán:

- `Access-Control-Allow-Origin: https://app.muebleslottus.com`
- `Access-Control-Allow-Credentials: true`

¡El backend estará listo y operativo en producción!
