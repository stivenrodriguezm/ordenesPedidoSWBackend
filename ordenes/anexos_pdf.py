"""Anexo para diligenciar a mano, con el número centrado en su recuadro."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from pypdf import PageObject, PdfReader, PdfWriter
from pypdf.generic import BooleanObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject


@lru_cache(maxsize=1)
def _plantilla():
    return (Path(__file__).parent / 'plantillas' / 'anexo-compra.pdf').read_bytes()


def generar_anexo_pdf(venta_id, copias=2):
    lector = PdfReader(BytesIO(_plantilla()))
    escritor = PdfWriter()
    frente = lector.pages[0]
    numero = PageObject.create_blank_page(width=612, height=792)
    numero[NameObject('/Resources')] = DictionaryObject({
        NameObject('/Font'): DictionaryObject({
            NameObject('/FAnexo'): DictionaryObject({
                NameObject('/Type'): NameObject('/Font'),
                NameObject('/Subtype'): NameObject('/Type1'),
                NameObject('/BaseFont'): NameObject('/Helvetica-Bold'),
            }),
        }),
    })
    contenido = DecodedStreamObject()
    texto = f'No. {int(venta_id)}'
    # Ancho de «No. » y dígitos en Helvetica-Bold, en unidades de 1/1000 em.
    ancho = (1889 + 556 * len(str(int(venta_id)))) * 16 / 1000
    x = 507.54 - ancho / 2
    contenido.set_data(f'q 0 0 0 rg BT /FAnexo 16 Tf {x:.3f} 735.4 Td ({texto}) Tj ET Q'.encode('ascii'))
    numero[NameObject('/Contents')] = contenido
    frente.merge_page(numero)
    for _ in range(copias):
        escritor.add_page(frente)
        escritor.add_page(lector.pages[1])
    escritor.add_metadata({'/Title': f'Anexo a compra No. {int(venta_id)}'})
    escritor._root_object[NameObject('/ViewerPreferences')] = DictionaryObject({
        NameObject('/Duplex'): NameObject('/DuplexFlipLongEdge'),
        NameObject('/PrintScaling'): NameObject('/None'),
        NameObject('/PickTrayByPDFSize'): BooleanObject(True),
        NameObject('/NumCopies'): NumberObject(1),
    })
    salida = BytesIO()
    escritor.write(salida)
    return salida.getvalue()
