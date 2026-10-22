"""Adaptadores de archivo. Nunca reutilizar un formato de un banco para otro.

Davivienda: Excel estándar, pág. 2–4 del instructivo aportado. El número de
cuenta se codifica como texto para preservar ceros iniciales. No hay fórmulas,
macros, separadores de miles, filas vacías ni hojas auxiliares.
"""
from io import BytesIO
import re
import unicodedata
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

from ordenes.servicios import ErrorNegocio

ENCABEZADOS = [
    'Tipo de Identificación', 'Número de Identificación', 'Nombre', 'Apellido',
    'Código del Banco', 'Tipo de Producto o Servicio', 'Número del Producto o Servicio',
    'Valor del pago o de la recarga', 'Referencia',
]


def nombre_bancario(valor):
    texto = unicodedata.normalize('NFKD', str(valor))
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^A-Za-z0-9 ]', ' ', texto).upper().split())


def davivienda_excel(filas):
    # OOXML mínimo con biblioteca estándar: exportador del ERP sin dependencias
    # de escritorio. Los identificadores siempre son cadenas, nunca floats.
    def celda(col, fila, valor, numerica=False, cuenta=False):
        ref = f'{chr(65 + col)}{fila}'
        if numerica:
            return f'<c r="{ref}" s="2"><v>{valor}</v></c>'
        estilo = '1' if cuenta else '0'
        return f'<c r="{ref}" s="{estilo}" t="inlineStr"><is><t>{escape(str(valor))}</t></is></c>'

    rows = ['<row r="1">' + ''.join(celda(i, 1, h) for i, h in enumerate(ENCABEZADOS)) + '</row>']
    for n, f in enumerate(filas, 2):
        c = f['cuenta']
        valores = [c['tipo_documento'], c['documento'], nombre_bancario(c['nombres']), nombre_bancario(c['apellidos']),
                   c['banco'], c['tipo'], c['numero'], str(f['valor']), str(f['referencia'])]
        rows.append(f'<row r="{n}">' + ''.join(celda(i, n, v, numerica=i in (0, 4, 7), cuenta=i in (1, 6, 8)) for i, v in enumerate(valores)) + '</row>')
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    files = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        '_rels/.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml': f'<workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Pagos" sheetId="1" r:id="rId1"/></sheets></workbook>',
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        'xl/styles.xml': f'<styleSheet xmlns="{ns}"><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="1" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
        'xl/worksheets/sheet1.xml': f'<worksheet xmlns="{ns}"><cols>' + ''.join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i,w in enumerate([24,26,32,32,20,30,32,34,18],1)) + '</cols><sheetData>' + ''.join(rows) + '</sheetData></worksheet>',
    }
    salida = BytesIO()
    with ZipFile(salida, 'w', ZIP_DEFLATED) as z:
        for ruta, xml in files.items():
            z.writestr(ruta, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml)
    return salida.getvalue()


def exportar(banco, filas):
    if banco != 'davivienda':
        raise ErrorNegocio('La descarga desde Bancolombia estará disponible al configurar su formato oficial. Usa Davivienda como banco de origen por ahora.')
    return davivienda_excel(filas)
