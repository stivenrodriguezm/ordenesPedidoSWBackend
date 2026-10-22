"""Códigos de TABLA-BANCOS.pdf y FORMATO-EXCEL-ESTANDAR.pdf del usuario.

Son códigos de destino de Davivienda, no códigos ACH de otros exportadores.
"""
BANCOS = {
    '1': 'Banco de Bogotá', '2': 'Banco Popular', '6': 'Itaú', '7': 'Bancolombia',
    '9': 'Citibank', '12': 'GNB Sudameris', '13': 'BBVA Colombia', '14': 'Helm Bank',
    '19': 'Scotiabank Colpatria', '21': 'Juriscoop', '23': 'Banco de Occidente',
    '31': 'Bancóldex', '32': 'Banco Caja Social', '40': 'Banco Agrario', '42': 'BNP Paribas',
    '47': 'Mundo Mujer', '51': 'Davivienda', '52': 'AV Villas', '53': 'Banco W',
    '59': 'Bancamía', '60': 'Banco Pichincha', '61': 'Bancoomeva', '62': 'Banco Falabella',
    '63': 'Banco Finandina', '65': 'Santander de Negocios', '66': 'Coopcentral',
    '67': 'Mi Banco', '69': 'Serfinanza', '70': 'Lulo Bank', '71': 'J.P. Morgan',
    '283': 'CFA', '286': 'JFK', '289': 'Cootrafa', '291': 'Cofinep', '292': 'Confiar',
    '303': 'Banco Unión', '370': 'Coltefinanciera', '507': 'Nequi', '558': 'Ban100',
    '560': 'Pibank', '637': 'IRIS', '801': 'MOVii', '802': 'DING', '804': 'Ualá',
    '805': 'BTG Pactual', '803': 'Powwi', '808': 'BOLD', '809': 'Nubank',
    '811': 'RappiPay', '812': 'Coink', '813': 'Santander Consumer', '814': 'Global66',
}
DOCUMENTOS = {
    '01': 'Cédula de ciudadanía', '02': 'Cédula de extranjería', '03': 'NIT (con dígito de verificación)',
    '04': 'Tarjeta de identidad', '05': 'Pasaporte', '06': 'Seguro social extranjero',
    '07': 'Sociedad extranjera sin NIT', '08': 'Fideicomiso', '09': 'NIT menores',
    '10': 'RIF Venezuela', '11': 'NIT extranjería', '12': 'NIT persona natural',
    '13': 'Registro civil', '99': 'NIT desasociado',
}
TIPOS = {'CA': 'Ahorros', 'CC': 'Corriente', 'DP': 'DaviPlata', 'TP': 'Tarjeta prepago', 'DE': 'Depósito electrónico'}
