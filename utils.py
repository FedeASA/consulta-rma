import re
from datetime import datetime

TRUE_VALUES = {"TRUE", "SI", "SÍ", "YES", "1", "Y", "OK"}
FALSE_VALUES = {"FALSE", "NO", "0", "N", ""}


def es_verdadero(valor):
    """Normaliza un valor a booleano verdadero o falso."""
    if isinstance(valor, bool):
        return valor
    if valor is None:
        return False
    if isinstance(valor, (int, float)):
        return int(valor) == 1

    texto = str(valor).strip().upper()
    return texto in TRUE_VALUES


def es_falso(valor):
    """Normaliza un valor a booleano falso."""
    if isinstance(valor, bool):
        return not valor
    if valor is None:
        return True
    texto = str(valor).strip().upper()
    return texto in FALSE_VALUES


def booleano_a_sheets(valor):
    """Convierte un valor booleano a los strings esperados por Google Sheets."""
    return "Sí" if es_verdadero(valor) else "No"


def formatear_fecha(fecha_raw):
    """Convierte fechas a formato DD/MM/YYYY para visualización."""
    if not fecha_raw or str(fecha_raw).strip() in ["None", "none", "nan", "NaN", ""]:
        return "N/A"

    fecha_str = str(fecha_raw).replace('-', '/').strip()
    for formato in ['%Y/%m/%d', '%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y']:
        try:
            dt = datetime.strptime(fecha_str, formato)
            return dt.strftime('%d/%m/%Y')
        except ValueError:
            continue
    return str(fecha_raw)


def validar_email(email):
    """Valida que un email tenga formato básico correcto."""
    if not email or not str(email).strip():
        return False
    patron = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(patron, str(email).strip()) is not None
