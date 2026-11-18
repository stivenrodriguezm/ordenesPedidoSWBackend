# Instala o actualiza el agente de impresión de Lottus en el Windows de la oficina
# (2026-10-30; desde 2026-11-18 se conecta solo con un usuario administrador del ERP).
#   1. Elige la impresora de Windows (la Ricoh).
#   2. Copia el agente a %LOCALAPPDATA%\LottusImpresion (sin permisos de administrador de Windows).
#   3. Conecta esta computadora a la plataforma: pide usuario y contraseña de un administrador
#      y recibe el token de la impresora (o usa config.json si viene junto a este archivo).
#   4. Lo deja arrancando al iniciar sesión y lo arranca ya.
#   5. Imprime una hoja de prueba que pasa por el servidor, igual que desde la plataforma.
#
#   instalar.bat                                     -> producción
#   instalar.ps1 -Api https://api.muebleslottus.com:8443/api -Servidor pruebas
param(
    [string]$Api = 'https://api.muebleslottus.com/api',
    [string]$Servidor = 'produccion'
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$Api = $Api.TrimEnd('/')
$origen = $PSScriptRoot
$destino = Join-Path $env:LOCALAPPDATA 'LottusImpresion'
$configOrigen = Join-Path $origen 'config.json'
$configDestino = Join-Path $destino 'config.json'

function Fallar([string]$mensaje) {
    Write-Host ''
    Write-Host $mensaje -ForegroundColor Red
    exit 1
}

function Paso([string]$texto) {
    Write-Host ''
    Write-Host $texto -ForegroundColor Cyan
}

function Llamar([string]$metodo, [string]$ruta, $cuerpo = $null, [string]$acceso = '') {
    $opciones = @{ Method = $metodo; Uri = "$Api$ruta"; TimeoutSec = 30; Headers = @{} }
    if ($acceso) { $opciones.Headers['Authorization'] = "Bearer $acceso" }
    if ($null -ne $cuerpo) {
        $opciones.Body = [Text.Encoding]::UTF8.GetBytes(($cuerpo | ConvertTo-Json -Compress -Depth 5))
        $opciones.ContentType = 'application/json; charset=utf-8'
    }
    Invoke-RestMethod @opciones
}

function CodigoHttp($registro) {
    if ($registro.Exception.Response) { return [int]$registro.Exception.Response.StatusCode }
    return 0
}

function RespuestaError($registro) {
    try { return ($registro.ErrorDetails.Message | ConvertFrom-Json) } catch { return $null }
}

Write-Host '=============================================' -ForegroundColor Green
Write-Host '  Lottus - impresión en la oficina' -ForegroundColor Green
Write-Host '=============================================' -ForegroundColor Green
Write-Host "Plataforma: $Api"

foreach ($archivo in 'agente.py', 'SumatraPDF.exe', 'python\pythonw.exe') {
    if (-not (Test-Path (Join-Path $origen $archivo))) { Fallar "Falta $archivo en esta carpeta. Descomprime todo el .zip y vuelve a ejecutar instalar.bat." }
}
# El agente convierte cada documento a PDF con Edge o Chrome (los busca donde los busca agente.py).
$navegadores = @()
foreach ($base in ${env:ProgramFiles(x86)}, $env:ProgramFiles, $env:LOCALAPPDATA) {
    if (-not $base) { continue }
    foreach ($relativa in 'Microsoft\Edge\Application\msedge.exe', 'Google\Chrome\Application\chrome.exe') {
        if (Test-Path (Join-Path $base $relativa)) { $navegadores += (Join-Path $base $relativa) }
    }
}
if ($navegadores.Count -eq 0) { Fallar 'Esta computadora no tiene Microsoft Edge ni Google Chrome: instala uno de los dos y vuelve a ejecutar.' }

# 1. La impresora de Windows: la Ricoh si hay una sola; si no, se pregunta.
Paso '1. Impresora'
$impresoras = @(Get-Printer | Where-Object { $_.Name -notmatch 'PDF|XPS|OneNote|Fax' } | Select-Object -ExpandProperty Name)
$ricoh = @($impresoras | Where-Object { $_ -match 'ricoh|3710' })
if ($ricoh.Count -eq 1) {
    $cola = $ricoh[0]
} else {
    if ($impresoras.Count -eq 0) { Fallar 'Este Windows no tiene impresoras instaladas. Instala la Ricoh (Configuración > Impresoras y escáneres > Agregar) y vuelve a ejecutar.' }
    Write-Host 'Impresoras de este Windows:'
    for ($i = 0; $i -lt $impresoras.Count; $i++) { Write-Host "  $($i + 1). $($impresoras[$i])" }
    $numero = 0
    while ($numero -lt 1 -or $numero -gt $impresoras.Count) {
        [int]::TryParse((Read-Host 'Número de la Ricoh'), [ref]$numero) | Out-Null
    }
    $cola = $impresoras[$numero - 1]
}
Write-Host "Impresora: $cola"

# 2. Detener el agente anterior y copiar los archivos.
Paso '2. Copiando el agente'
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*LottusImpresion*agente.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2  # que Windows suelte los archivos del agente anterior antes de reemplazarlos
New-Item -ItemType Directory -Force -Path $destino | Out-Null
Copy-Item (Join-Path $origen 'agente.py'), (Join-Path $origen 'SumatraPDF.exe') $destino -Force
Copy-Item (Join-Path $origen 'python') $destino -Recurse -Force
# Lo que viene en un .zip descargado queda marcado «de Internet»: se desmarca para que arranque sin avisos.
Get-ChildItem $destino -Recurse -File | Unblock-File -ErrorAction SilentlyContinue
Write-Host "Agente en $destino"

# 3. Conectar esta computadora a la plataforma.
Paso '3. Conexión con la plataforma'
$config = $null
if (Test-Path $configOrigen) { $config = Get-Content $configOrigen -Raw -Encoding UTF8 | ConvertFrom-Json }
elseif (Test-Path $configDestino) { $config = Get-Content $configDestino -Raw -Encoding UTF8 | ConvertFrom-Json }
$servidores = @()
if ($config -and $config.servidores) { $servidores = @($config.servidores) }
$conexion = $servidores | Where-Object { $_.api -eq $Api } | Select-Object -First 1
if ($conexion -and -not (Test-Path $configOrigen)) {
    $respuesta = Read-Host 'Esta computadora ya estaba conectada. ¿Conectarla de nuevo? (s/N)'
    if ($respuesta -match '^[sS]') { $conexion = $null }
}

$acceso = ''
if (-not $conexion) {
    Write-Host 'Entra con un usuario ADMINISTRADOR de la plataforma (el mismo con que entras a app.muebleslottus.com).'
    for ($intento = 1; $intento -le 3 -and -not $acceso; $intento++) {
        $usuario = (Read-Host 'Usuario').Trim()
        $segura = Read-Host 'Contraseña' -AsSecureString
        $puntero = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($segura)
        try {
            $clave = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($puntero)
            $acceso = (Llamar 'Post' '/token/' @{ username = $usuario; password = $clave }).access
        } catch {
            $codigo = CodigoHttp $_
            if ($codigo -eq 401) { Write-Host 'Usuario o contraseña incorrectos (o el usuario está desactivado).' -ForegroundColor Yellow }
            elseif ($codigo -eq 429) { Fallar 'Demasiados intentos. Espera un minuto y vuelve a ejecutar instalar.bat.' }
            elseif ($codigo -eq 0) { Fallar "No hay conexión con la plataforma ($Api). Revisa el internet de esta computadora. Detalle: $($_.Exception.Message)" }
            else { Fallar "La plataforma respondió con un error ($codigo) al entrar." }
        } finally {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($puntero)
            $clave = $null
        }
    }
    if (-not $acceso) { Fallar 'No se pudo entrar a la plataforma.' }

    $pedido = @{ nombre = $cola; equipo = $env:COMPUTERNAME }
    $respuesta = $null
    while (-not $respuesta) {
        try {
            $respuesta = Llamar 'Post' '/impresion/conectar/' $pedido $acceso
        } catch {
            $codigo = CodigoHttp $_
            $detalle = RespuestaError $_
            if ($codigo -eq 409 -and $detalle.impresoras -and -not $pedido.ContainsKey('impresora')) {
                Write-Host 'En la plataforma hay varias impresoras de oficina:'
                $lista = @($detalle.impresoras)
                for ($i = 0; $i -lt $lista.Count; $i++) { Write-Host "  $($i + 1). $($lista[$i].nombre) $($lista[$i].ubicacion)" }
                $numero = 0
                while ($numero -lt 1 -or $numero -gt $lista.Count) {
                    [int]::TryParse((Read-Host 'Número de la que imprime en esta computadora'), [ref]$numero) | Out-Null
                }
                $pedido['impresora'] = $lista[$numero - 1].id
            } elseif ($codigo -eq 403) {
                Fallar 'Ese usuario no es administrador de la plataforma. Vuelve a ejecutar instalar.bat con un administrador.'
            } elseif ($codigo -eq 404) {
                Fallar 'La plataforma todavía no tiene la versión que conecta esta computadora: primero hay que desplegar el backend.'
            } else {
                $texto = if ($detalle.error) { $detalle.error } else { $_.Exception.Message }
                Fallar "No se pudo conectar esta computadora ($codigo): $texto"
            }
        }
    }
    $conexion = [pscustomobject]@{ nombre = $Servidor; api = $Api; token = $respuesta.token; impresora = $respuesta.impresora }
    Write-Host "Conectada a la impresora «$($respuesta.nombre)» de la plataforma." -ForegroundColor Green
}

# Guardar la configuración (sin BOM, solo para este usuario de Windows).
$nueva = [ordered]@{ cola = $cola; servidores = @(@($servidores | Where-Object { $_ -and $_.api -ne $Api }) + $conexion) }
foreach ($opcional in 'intervalo', 'chrome', 'simular') {
    if ($config -and $null -ne $config.$opcional) { $nueva[$opcional] = $config.$opcional }
}
[IO.File]::WriteAllText($configDestino, ($nueva | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))
icacls $configDestino /inheritance:r /grant:r "$($env:USERNAME):F" | Out-Null

# 4. Que arranque al iniciar sesión (acceso directo en Inicio) y arrancarlo ya.
Paso '4. Arranque automático'
$python = Join-Path $destino 'python\pythonw.exe'
$agente = Join-Path $destino 'agente.py'
$acceso_directo = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'Lottus Impresion.lnk'))
$acceso_directo.TargetPath = $python
$acceso_directo.Arguments = "`"$agente`""
$acceso_directo.WorkingDirectory = $destino
$acceso_directo.Save()
Start-Process $python -ArgumentList "`"$agente`"" -WorkingDirectory $destino
Write-Host 'El agente queda corriendo y arranca solo cada vez que se inicia sesión en este Windows.'

# 5. Hoja de prueba.
Paso '5. Hoja de prueba'
if ($acceso) {
    # De punta a punta: plataforma -> servidor -> esta computadora -> Ricoh.
    $ahora = Get-Date -Format 'yyyy-MM-dd HH:mm'
    $html = "<!DOCTYPE html><html><head><meta charset=`"utf-8`"><title>Hoja de prueba</title><style>@page { size: letter portrait; margin: 12mm; } body { font-family: Arial, sans-serif; }</style></head><body><h1>Lottus - hoja de prueba</h1><p>Si ves esta hoja, la impresión en la oficina desde la plataforma funciona.</p><p>Computadora: $($env:COMPUTERNAME) - impresora: $cola - $ahora</p></body></html>"
    try {
        $trabajo = Llamar 'Post' '/impresion/trabajos/' @{ impresora = $conexion.impresora; titulo = 'Hoja de prueba'; html = $html; copias = 1 } $acceso
    } catch {
        Fallar "No se pudo enviar la hoja de prueba: $($_.Exception.Message)"
    }
    $estado = $trabajo.estado
    $ultimo = ''
    for ($i = 0; $i -lt 40 -and @('pendiente', 'procesando', 'enviado') -contains $estado; $i++) {
        Start-Sleep -Seconds 3
        $trabajo = Llamar 'Get' "/impresion/trabajos/$($trabajo.id)/" $null $acceso
        $estado = $trabajo.estado
        if ($trabajo.estado_nombre -ne $ultimo) { Write-Host "  $($trabajo.estado_nombre)"; $ultimo = $trabajo.estado_nombre }
    }
    if ($estado -eq 'impreso') {
        Write-Host ''
        Write-Host 'Listo: salió la hoja de prueba. Ya se puede imprimir desde la plataforma eligiendo «En la oficina».' -ForegroundColor Green
    } elseif ($estado -eq 'error') {
        Fallar "La hoja de prueba no se imprimió: $($trabajo.detalle)"
    } else {
        Write-Host "La hoja de prueba sigue en «$($trabajo.estado_nombre)». Revisa que la Ricoh esté encendida y con papel; el registro está en $(Join-Path $destino 'agente.log')." -ForegroundColor Yellow
    }
} else {
    & (Join-Path $destino 'python\python.exe') $agente --probar
    Write-Host 'Si salió la hoja de prueba, ya se puede imprimir desde la plataforma eligiendo «En la oficina».' -ForegroundColor Green
}
Write-Host ''
Write-Host 'Deja esta computadora encendida y con la sesión de Windows abierta (puede quedar bloqueada).'
Write-Host "Registro del agente: $(Join-Path $destino 'agente.log')"
