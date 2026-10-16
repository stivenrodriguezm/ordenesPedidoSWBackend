"""PDF mínimo de texto para pruebas (sin dependencias): una línea por renglón,
fuente Helvetica con WinAnsiEncoding para tildes."""


def _escapar(texto):
    return texto.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')


def pdf_de_texto(paginas):
    objetos = []

    def agregar(cuerpo):
        objetos.append(cuerpo)
        return len(objetos)

    fuente = agregar(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>')
    raiz_paginas = agregar(b'')  # se completa al final
    hijos = []
    for lineas in paginas:
        flujo = b'BT /F1 9 Tf 12 TL 40 800 Td\n' + b''.join(
            b'(' + _escapar(l).encode('cp1252') + b') Tj T*\n' for l in lineas) + b'ET'
        contenido = agregar(b'<< /Length %d >>\nstream\n' % len(flujo) + flujo + b'\nendstream')
        hijos.append(agregar(b'<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 842] /Contents %d 0 R '
                             b'/Resources << /Font << /F1 %d 0 R >> >> >>' % (raiz_paginas, contenido, fuente)))
    objetos[raiz_paginas - 1] = b'<< /Type /Pages /Kids [%s] /Count %d >>' % (
        b' '.join(b'%d 0 R' % h for h in hijos), len(hijos))
    catalogo = agregar(b'<< /Type /Catalog /Pages %d 0 R >>' % raiz_paginas)
    salida = bytearray(b'%PDF-1.4\n')
    posiciones = []
    for i, cuerpo in enumerate(objetos, start=1):
        posiciones.append(len(salida))
        salida += b'%d 0 obj\n' % i + cuerpo + b'\nendobj\n'
    xref = len(salida)
    salida += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objetos) + 1)
    salida += b''.join(b'%010d 00000 n \n' % p for p in posiciones)
    salida += b'trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objetos) + 1, catalogo, xref)
    return bytes(salida)
