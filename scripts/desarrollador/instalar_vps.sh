#!/bin/bash
# Instala (o actualiza) el servicio del agente Desarrollador en el VPS. Se ejecuta como root
# (sudo) desde una copia del repositorio backend. Idempotente.
#
# Requiere en /etc/lottus-desarrollador.env (root:desarrollador, 640):
#   DESARROLLADOR_TOKEN=...            (el mismo del .env de producción)
#   DESARROLLADOR_ANTHROPIC_API_KEY=... (Claude, primera opción)        
#   DESARROLLADOR_OPENAI_API_KEY=...    (GPT; se usa si no hay clave de Claude)
#   DESARROLLADOR_GEMINI_API_KEY=...    (opcional, último recurso)
#   DESARROLLADOR_MODELOS=...           (opcional, Gemini para implementar; por defecto Pro)
#   DESARROLLADOR_MODELOS_PLAN=...      (opcional, Gemini para planear; por defecto Flash)
# y las llaves de GitHub (deploy keys con escritura) en /home/desarrollador/.ssh/{backend,frontend}.
#
# Queda:
#   - usuario del sistema `desarrollador` (sin sudo general) con su espacio en /home/desarrollador/trabajo
#   - Node en /home/desarrollador/node y un venv de pruebas en /home/desarrollador/venv
#   - el código del servicio en /opt/lottus-desarrollador (de root: el agente no puede modificarlo)
#   - sudo acotado: desarrollador → stiven solo para desplegar_pruebas.sh; stiven → reiniciar gunicorn-pruebas
#   - servicio systemd lottus-desarrollador (escucha solo en 127.0.0.1:8020)
set -euo pipefail
ORIGEN="$(cd "$(dirname "$0")" && pwd)"
NODE_VERSION=v22.12.0
U=desarrollador
H=/home/$U

id $U >/dev/null 2>&1 || useradd -m -s /bin/bash $U
chmod 750 $H

# Código del servicio (solo lectura para el agente)
install -d -o root -g root -m 755 /opt/lottus-desarrollador/desarrollador
install -o root -g root -m 644 "$ORIGEN"/{__init__.py,espacio.py,gemini.py,claude.py,gpt.py,servicio.py,aplicar_local.py,reglas.md} /opt/lottus-desarrollador/desarrollador/
install -o root -g root -m 755 "$ORIGEN/desplegar_pruebas.sh" /opt/lottus-desarrollador/desplegar_pruebas.sh
install -o root -g root -m 644 "$ORIGEN/migrar_pruebas.py" /opt/lottus-desarrollador/migrar_pruebas.py

# Node (para lint, pruebas y build del frontend)
if [ ! -x $H/node/bin/node ] || [ "$($H/node/bin/node --version)" != "$NODE_VERSION" ]; then
  T=$(mktemp -d)
  curl -fsSL "https://nodejs.org/dist/$NODE_VERSION/node-$NODE_VERSION-linux-x64.tar.xz" -o "$T/node.tar.xz"
  rm -rf $H/node && mkdir -p $H/node && tar -xJf "$T/node.tar.xz" -C $H/node --strip-components=1
  rm -rf "$T"
  chown -R $U:$U $H/node
fi

# Llaves de GitHub y repositorios del espacio
install -d -o $U -g $U -m 700 $H/.ssh
cat > $H/.ssh/config <<'CFG'
Host github-backend
  HostName github.com
  User git
  IdentityFile ~/.ssh/backend
  IdentitiesOnly yes
Host github-frontend
  HostName github.com
  User git
  IdentityFile ~/.ssh/frontend
  IdentitiesOnly yes
CFG
chown $U:$U $H/.ssh/config && chmod 600 $H/.ssh/config
sudo -u $U bash -c 'ssh-keyscan -H github.com >> ~/.ssh/known_hosts 2>/dev/null; sort -u -o ~/.ssh/known_hosts ~/.ssh/known_hosts'
sudo -u $U mkdir -p $H/trabajo
[ -d $H/trabajo/backend/.git ] || sudo -u $U git clone -q git@github-backend:stivenrodriguezm/ordenesPedidoSWBackend.git $H/trabajo/backend
[ -d $H/trabajo/frontend/.git ] || sudo -u $U git clone -q git@github-frontend:stivenrodriguezm/ordenesPedidoSW.git $H/trabajo/frontend

# Entornos para las verificaciones
[ -x $H/venv/bin/python ] || sudo -u $U python3 -m venv $H/venv
sudo -u $U $H/venv/bin/pip install -q -r $H/trabajo/backend/requirements.txt anthropic  # anthropic: el servicio con Claude (Python 3.10+)
sudo -u $U bash -c "cd $H/trabajo/frontend && PATH=$H/node/bin:\$PATH npm ci --no-audit --no-fund --loglevel=error"

# Sudo acotado (validado con visudo antes de instalar)
cat > /tmp/lottus-desarrollador.sudoers <<'SUDO'
desarrollador ALL=(stiven) NOPASSWD: /opt/lottus-desarrollador/desplegar_pruebas.sh
stiven ALL=(root) NOPASSWD: /usr/bin/systemctl restart gunicorn-pruebas
SUDO
visudo -cf /tmp/lottus-desarrollador.sudoers
install -o root -g root -m 440 /tmp/lottus-desarrollador.sudoers /etc/sudoers.d/lottus-desarrollador
rm -f /tmp/lottus-desarrollador.sudoers

# Servicio
cat > /etc/systemd/system/lottus-desarrollador.service <<'UNIT'
[Unit]
Description=Agente Desarrollador de IA Lottus
After=network-online.target gunicorn.service

[Service]
User=desarrollador
Group=desarrollador
WorkingDirectory=/opt/lottus-desarrollador
EnvironmentFile=/etc/lottus-desarrollador.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/desarrollador/venv/bin/python -m desarrollador.servicio
Restart=on-failure
RestartSec=10
NoNewPrivileges=false
ProtectSystem=full

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable -q lottus-desarrollador
systemctl restart lottus-desarrollador
sleep 3
systemctl is-active lottus-desarrollador
