#!/bin/bash
# Instala (o actualiza) el agente de impresión en la computadora de la oficina principal,
# como LaunchAgent: arranca al iniciar sesión, se reinicia si se cae y evita que el equipo
# se duerma mientras corre (caffeinate). Requiere que ya exista config.json (crear_impresora).
#
#   ./instalar_agente.sh            instalar / actualizar y reiniciar
#   ./instalar_agente.sh --quitar   detener y desinstalar (deja config.json)
set -euo pipefail

CARPETA="$HOME/Library/Application Support/LottusImpresion"
PLIST="$HOME/Library/LaunchAgents/com.lottus.impresion.plist"
LOG="$HOME/Library/Logs/LottusImpresion.log"
PY="${PYTHON:-$(command -v python3)}"

if [ "${1:-}" = "--quitar" ]; then
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  rm -f "$PLIST" "$CARPETA/agente.py"
  echo "Agente de impresión desinstalado (se conservó $CARPETA/config.json)."
  exit 0
fi

[ -f "$CARPETA/config.json" ] || { echo "Falta $CARPETA/config.json: créalo con manage.py crear_impresora"; exit 1; }
# Fuera del Escritorio: launchd no siempre puede leer ~/Desktop (privacidad de macOS).
install -m 700 "$(dirname "$0")/agente.py" "$CARPETA/agente.py"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.lottus.impresion</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string><string>-is</string>
    <string>$PY</string><string>-u</string><string>$CARPETA/agente.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 2
launchctl print "gui/$(id -u)/com.lottus.impresion" | grep -E "^\s+state" || true
echo "Registro: $LOG"
tail -3 "$LOG" 2>/dev/null || true
