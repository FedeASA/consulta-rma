"""
sheets_operations.py - Módulo para operaciones con Google Sheets
"""

import gspread
from gspread.exceptions import APIError
from googleapiclient.errors import HttpError
import unicodedata
import uuid
import re
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from google_auth_httplib2 import AuthorizedHttp
import httplib2
import pandas as pd
import streamlit as st
from datetime import datetime
import json
import os
import time
import io

# Timeout (segundos) para llamadas a la API de Google Drive.
# Sin esto, una llamada como files().delete() puede quedarse esperando
# una respuesta de red indefinidamente (cuelgue de socket, no error 429),
# lo que traba toda la app sin generar ninguna excepción ni log.
DRIVE_HTTP_TIMEOUT = 20

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

@st.cache_resource
def get_google_credentials():
    try:
        if "GOOGLE_CREDS" in st.secrets:
            creds_dict = st.secrets["GOOGLE_CREDS"]
            if isinstance(creds_dict, str):
                creds_dict = json.loads(creds_dict)
        else:
            raise KeyError("GOOGLE_CREDS not in secrets")
    except:
        try:
            if os.path.exists("creds_google.json"):
                with open("creds_google.json", "r") as f:
                    creds_dict = json.load(f)
            else:
                raise FileNotFoundError("creds_google.json not found")
        except:
            st.error("❌ Error: No se encontraron credenciales de Google.")
            st.stop()

    try:
        return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    except Exception as e:
        st.error(f"❌ Error al autenticar con Google: {e}")
        st.stop()


@st.cache_resource
def get_sheets_client():
    credentials = get_google_credentials()
    try:
        client = gspread.authorize(credentials)
        return client
    except Exception as e:
        st.error(f"❌ Error al autenticar con Google: {e}")
        st.stop()


# --- GOOGLE DRIVE: fotos adjuntas de los RMA ---

@st.cache_resource
def get_drive_service():
    credentials = get_google_credentials()
    try:
        # ✅ http con timeout: si Drive no responde en DRIVE_HTTP_TIMEOUT segundos,
        # tira una excepción en vez de colgar la app indefinidamente.
        http_con_timeout = httplib2.Http(timeout=DRIVE_HTTP_TIMEOUT)
        authed_http = AuthorizedHttp(credentials, http=http_con_timeout)
        return build("drive", "v3", http=authed_http, cache_discovery=False)
    except Exception as e:
        st.error(f"❌ Error al conectar con Google Drive: {e}")
        st.stop()


def _get_drive_folder_id():
    """Devuelve el ID de la carpeta de fotos, o None si no está configurado.
    (Ya no hace st.stop(): eso cortaba el guardado del ticket entero.)"""
    try:
        valor = str(st.secrets["DRIVE_FOTOS_RMA_FOLDER_ID"]).strip()
        return valor or None
    except Exception:
        return None


def _explicar_error_drive(e):
    """Traduce los errores de Drive más comunes a un mensaje entendible."""
    txt = str(e)
    if "storageQuotaExceeded" in txt or "do not have storage quota" in txt:
        return ("La cuenta de servicio no tiene cuota de almacenamiento propia. "
                "La carpeta de fotos tiene que estar dentro de una Unidad compartida "
                "(Shared Drive) con la cuenta de servicio como miembro (Gestor de contenido). "
                f"Detalle: {txt}")
    if "File not found" in txt or "notFound" in txt:
        return ("No se encontró la carpeta DRIVE_FOTOS_RMA_FOLDER_ID o la cuenta de servicio "
                f"no tiene acceso a ella. Detalle: {txt}")
    if "insufficientFilePermissions" in txt or "403" in txt:
        return ("La cuenta de servicio no tiene permiso de escritura sobre la carpeta de fotos. "
                f"Detalle: {txt}")
    return txt


def subir_foto_a_drive(bytes_imagen, nombre_archivo):
    """Sube una foto (bytes JPEG) a la carpeta de Drive configurada.
    Devuelve (file_id, None) si salió bien, o (None, mensaje_error) si falló."""
    folder_id = _get_drive_folder_id()
    if not folder_id:
        return None, ("Falta configurar 'DRIVE_FOTOS_RMA_FOLDER_ID' en Secrets (a nivel raíz, "
                      "no dentro de [GOOGLE_CREDS]).")
    try:
        servicio = get_drive_service()
        metadata = {"name": nombre_archivo, "parents": [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(bytes_imagen), mimetype="image/jpeg", resumable=False)
        archivo = _safe_api_call(lambda: servicio.files().create(
            body=metadata, media_body=media, fields="id",
            supportsAllDrives=True
        ).execute())
        file_id = archivo.get("id")
        if not file_id:
            return None, "Drive no devolvió un ID de archivo."
        return file_id, None
    except Exception as e:
        return None, _explicar_error_drive(e)


@st.cache_data(ttl=3600, show_spinner=False)
def descargar_foto_de_drive(file_id):
    """Descarga los bytes de una foto guardada en Drive (cacheado 1 hora)."""
    if not file_id:
        return None
    try:
        servicio = get_drive_service()
        solicitud = servicio.files().get_media(fileId=file_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, solicitud)
        listo = False
        while not listo:
            _, listo = downloader.next_chunk()
        return buffer.getvalue()
    except Exception:
        return None


def eliminar_foto_de_drive(file_id):
    """Elimina un archivo de Drive por su ID. No lanza error si ya no existe."""
    if not file_id:
        return True
    try:
        servicio = get_drive_service()
        _safe_api_call(lambda: servicio.files().delete(fileId=file_id, supportsAllDrives=True).execute())
        return True
    except Exception:
        return False


# --- CLOUDINARY: fotos adjuntas de los RMA (reemplaza a Drive para las fotos nuevas) ---
# Secrets necesarios (sección propia, a nivel raíz):
#   [CLOUDINARY]
#   cloud_name = "..."
#   api_key    = "..."
#   api_secret = "..."
#   folder     = "rma"        # opcional
# En la planilla, Foto1/Foto2 guardan la URL de Cloudinary (https://res.cloudinary.com/...).
# Los tickets viejos que tienen un ID de Drive se siguen viendo con las funciones de Drive.

def _config_cloudinary():
    """Configura el SDK. Devuelve (modulo_cloudinary, carpeta, None) o (None, None, error)."""
    try:
        import cloudinary
        import cloudinary.uploader  # noqa: F401
    except ImportError:
        return None, None, "Falta el paquete 'cloudinary' en requirements.txt."
    try:
        cfg = st.secrets["CLOUDINARY"]
        cloudinary.config(
            cloud_name=str(cfg["cloud_name"]).strip(),
            api_key=str(cfg["api_key"]).strip(),
            api_secret=str(cfg["api_secret"]).strip(),
            secure=True,
        )
        carpeta = str(cfg.get("folder", "rma")).strip() or "rma"
        return cloudinary, carpeta, None
    except Exception:
        return None, None, ("Falta la sección [CLOUDINARY] (cloud_name, api_key, api_secret) "
                            "en los Secrets de la app.")


def es_url_foto(valor):
    return str(valor or "").strip().lower().startswith("http")


def subir_foto_a_cloudinary(bytes_imagen, nombre_base="foto"):
    """Sube una foto (bytes) a Cloudinary.
    Devuelve (url_segura, None) si salió bien, o (None, mensaje_error) si falló."""
    cloudinary, carpeta, error = _config_cloudinary()
    if error:
        return None, error
    # public_id con parte aleatoria: la URL no se puede adivinar a partir del serial
    limpio = re.sub(r"[^A-Za-z0-9_-]+", "_", str(nombre_base))[:40] or "foto"
    public_id = f"{limpio}_{uuid.uuid4().hex[:10]}"
    for intento in range(3):
        try:
            res = cloudinary.uploader.upload(
                io.BytesIO(bytes_imagen),
                folder=carpeta,
                public_id=public_id,
                resource_type="image",
                overwrite=False,
            )
            url = res.get("secure_url")
            if not url:
                return None, "Cloudinary no devolvió la URL de la imagen."
            return url, None
        except Exception as e:
            txt = str(e)
            transitorio = any(c in txt for c in ("429", "500", "502", "503", "timed out", "Timeout"))
            if transitorio and intento < 2:
                time.sleep(2 * (intento + 1))
                continue
            if "401" in txt or "Invalid Signature" in txt or "api_key" in txt.lower():
                return None, f"Credenciales de Cloudinary inválidas. Detalle: {txt}"
            return None, f"Error de Cloudinary: {txt}"


def miniatura_cloudinary(url, ancho=300, alto=300):
    """Devuelve la URL de una miniatura recortada (la genera Cloudinary al vuelo)."""
    url = str(url or "").strip()
    if "/image/upload/" not in url:
        return url
    return url.replace("/image/upload/", f"/image/upload/c_fill,w_{ancho},h_{alto},q_auto,f_auto/", 1)


def _public_id_desde_url(url):
    """https://res.cloudinary.com/<cloud>/image/upload/v123/rma/abc.jpg -> rma/abc"""
    m = re.search(r"/image/upload/(?:[^/]+/)*?v\d+/(.+?)(?:\.[A-Za-z0-9]+)?$", str(url))
    if not m:
        m = re.search(r"/image/upload/(.+?)(?:\.[A-Za-z0-9]+)?$", str(url))
    return m.group(1) if m else None


def eliminar_foto(valor):
    """Borra una foto: si es URL de Cloudinary la borra allí, si es un ID viejo de Drive, de Drive."""
    valor = str(valor or "").strip()
    if not valor:
        return True
    if not es_url_foto(valor):
        return eliminar_foto_de_drive(valor)
    cloudinary, _, error = _config_cloudinary()
    if error:
        return False
    public_id = _public_id_desde_url(valor)
    if not public_id:
        return False
    try:
        res = cloudinary.uploader.destroy(public_id, resource_type="image", invalidate=True)
        return res.get("result") in ("ok", "not found")
    except Exception:
        return False


def get_sheet(sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    client = get_sheets_client()
    try:
        sheet = client.open(sheet_name)
        worksheet = sheet.worksheet(worksheet_name)
        return worksheet
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"❌ No se encontró el sheet '{sheet_name}'")
        st.stop()
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ No se encontró la hoja '{worksheet_name}'")
        st.stop()
    except Exception as e:
        st.error(f"❌ Error al acceder al sheet: {e}")
        st.stop()


@st.cache_data(ttl=60)
def _get_cached_headers(sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    """Cache de headers para no leerlos en cada operación."""
    worksheet = get_sheet(sheet_name, worksheet_name)
    return worksheet.row_values(1)


def get_all_records(sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        records = worksheet.get_all_records()
        return records if records else []
    except Exception as e:
        st.error(f"❌ Error al leer registros: {e}")
        return []


def get_dataframe(sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        # Una sola lectura que trae todo
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        df = df.fillna("").replace(["None", "none", "nan", "NaN"], "")
        return df
    except Exception as e:
        st.error(f"❌ Error al leer datos: {e}")
        return pd.DataFrame()


def _safe_api_call(fn, retries=3, delay=5):
    """Reintenta una llamada a la API (Sheets o Drive) ante errores transitorios 429/500/503."""
    for attempt in range(retries):
        try:
            return fn()
        except (APIError, HttpError) as e:
            status = None
            if isinstance(e, HttpError):
                status = getattr(getattr(e, "resp", None), "status", None)
            else:
                status = getattr(getattr(e, "response", None), "status_code", None)
            transitorio = str(status) in ("429", "500", "503") or "429" in str(e)
            if transitorio and attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                raise


def _normalizar_nombre_col(nombre):
    """'Proveedor ', 'PROVEEDOR', 'proveedor' -> 'PROVEEDOR'. Quita acentos y espacios extra."""
    s = unicodedata.normalize("NFKD", str(nombre)).encode("ascii", "ignore").decode()
    return " ".join(s.split()).upper()


def _datos_normalizados(data, headers):
    """Mapea las claves de `data` a los encabezados reales de la planilla sin importar
    mayúsculas/espacios/acentos. Avisa si alguna clave no existe como columna
    (antes esos valores se descartaban en silencio)."""
    data_n = {_normalizar_nombre_col(k): v for k, v in data.items()}
    headers_n = {_normalizar_nombre_col(h) for h in headers}
    faltantes = [k for k in data.keys() if _normalizar_nombre_col(k) not in headers_n]
    if faltantes:
        st.warning(
            "⚠️ Estas columnas no existen en la planilla y no se guardaron: "
            + ", ".join(faltantes)
            + ". Agregá el encabezado en la fila 1 de la hoja."
        )
    return data_n


def _valor_celda(val):
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val)


def update_record(row_number, data, sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    """
    Actualiza una fila ENTERA en un solo request (en lugar de celda por celda).
    Lee los headers desde caché para no gastar quota.
    """
    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        # ✅ Headers desde caché (no consume quota)
        headers = _get_cached_headers(sheet_name, worksheet_name)

        if row_number < 2 or row_number > worksheet.row_count:
            st.warning(f"Número de fila inválido: {row_number}")
            return False

        # ✅ Una sola lectura de la fila actual
        current_row = _safe_api_call(lambda: worksheet.row_values(row_number))

        # Construir la fila nueva con los valores actualizados
        data_n = _datos_normalizados(data, headers)
        new_row = []
        for i, header in enumerate(headers):
            hn = _normalizar_nombre_col(header)
            if hn in data_n:
                new_row.append(_valor_celda(data_n[hn]))
            else:
                new_row.append(str(current_row[i]) if i < len(current_row) else "")

        # ✅ Una sola escritura para toda la fila (antes era 1 por columna)
        col_end = gspread.utils.rowcol_to_a1(row_number, len(headers))
        col_start = f"A{row_number}"
        _safe_api_call(lambda: worksheet.update(f"{col_start}:{col_end}", [new_row]))

        return True
    except Exception as e:
        st.warning(f"⚠️ Error al actualizar registro en fila {row_number}: {e}")
        return False


def _texto_comparable(v):
    t = str(v if v is not None else "").strip()
    try:
        f = float(t)
        if f.is_integer():
            return str(int(f))
    except ValueError:
        pass
    return t.upper()


def _fila_coincide(fila, idx_por_col, match):
    for col, val in match.items():
        i = idx_por_col.get(_normalizar_nombre_col(col))
        if i is None:
            continue
        actual = fila[i] if i < len(fila) else ""
        if _texto_comparable(actual) != _texto_comparable(val):
            return False
    return True


def _resolver_fila(all_rows, headers, row_number, match):
    """Devuelve el número de fila real del ticket.
    Si la fila esperada ya no corresponde al ticket (alguien borró/movió filas),
    lo busca en toda la hoja. Devuelve None si no lo encuentra o si hay más de uno."""
    if not match:
        return row_number
    idx_por_col = {_normalizar_nombre_col(h): i for i, h in enumerate(headers)}
    if 2 <= row_number <= len(all_rows) and _fila_coincide(all_rows[row_number - 1], idx_por_col, match):
        return row_number
    candidatas = [n + 1 for n, fila in enumerate(all_rows) if n >= 1 and _fila_coincide(fila, idx_por_col, match)]
    return candidatas[0] if len(candidatas) == 1 else None


def batch_update_records(records_to_update, sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    """
    ✅ NUEVO: Actualiza MÚLTIPLES filas en el menor número de requests posible.
    Usar esto en lugar de llamar update_record en un loop.
    
    Args:
        records_to_update: lista de {"row": row_number, "data": {campo: valor},
                                     "match": {columna: valor}}   # match es opcional
            Con "match" (ej. {"autonumero": "123"}) se verifica que la fila siga siendo
            ese ticket antes de escribir; si se movió, se busca por ese dato.
    """
    if not records_to_update:
        return True

    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        headers = _get_cached_headers(sheet_name, worksheet_name)

        # Una sola lectura de TODOS los datos actuales
        all_rows = _safe_api_call(lambda: worksheet.get_all_values())

        batch_data = []
        no_encontrados = []
        for rec in records_to_update:
            data = rec["data"]
            row_number = _resolver_fila(all_rows, headers, int(rec["row"]), rec.get("match"))
            if row_number is None:
                no_encontrados.append(rec.get("match") or rec["row"])
                continue

            if row_number < 2 or row_number > len(all_rows) + 1:
                continue

            current_row = all_rows[row_number - 1]  # 0-indexed

            data_n = _datos_normalizados(data, headers)
            new_row = []
            for i, header in enumerate(headers):
                hn = _normalizar_nombre_col(header)
                if hn in data_n:
                    new_row.append(_valor_celda(data_n[hn]))
                else:
                    new_row.append(str(current_row[i]) if i < len(current_row) else "")

            col_end_letter = gspread.utils.rowcol_to_a1(row_number, len(headers))
            batch_data.append({
                "range": f"A{row_number}:{col_end_letter}",
                "values": [new_row]
            })

        if batch_data:
            # ✅ UN SOLO request para actualizar todas las filas
            _safe_api_call(lambda: worksheet.batch_update(batch_data))

        if no_encontrados:
            st.warning(
                "⚠️ No se guardaron cambios en algunos tickets porque ya no están en la planilla "
                f"(¿los modificó o anuló otra persona?): {no_encontrados}. Actualizá el panel."
            )
            return False
        return True
    except Exception as e:
        st.warning(f"⚠️ Error en batch_update_records: {e}")
        return False


def delete_row(row_number, sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        if row_number < 2:
            st.warning("No se puede eliminar el encabezado")
            return False
        worksheet.delete_rows(row_number)
        return True
    except Exception as e:
        st.error(f"❌ Error al eliminar registro: {e}")
        return False


def _siguiente_autonumero(worksheet, headers):
    """Próximo Nº de RMA = mayor número existente + 1 (leído en el momento, sin caché)."""
    idx = next((i for i, h in enumerate(headers) if _normalizar_nombre_col(h) == "AUTONUMERO"), None)
    if idx is None:
        return None
    valores = _safe_api_call(lambda: worksheet.col_values(idx + 1))[1:]
    numeros = []
    for v in valores:
        try:
            numeros.append(int(float(str(v).strip())))
        except (TypeError, ValueError):
            continue
    return (max(numeros) + 1) if numeros else 1


def create_record(data, sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        headers = _get_cached_headers(sheet_name, worksheet_name)
        # El Nº de RMA se guarda como valor fijo al crear el ticket (antes lo calculaba
        # la planilla y se corría al borrar filas).
        if not str(data.get("autonumero", "") or "").strip():
            proximo = _siguiente_autonumero(worksheet, headers)
            if proximo is not None:
                data = {**data, "autonumero": proximo}
        data_n = {_normalizar_nombre_col(k): v for k, v in data.items()}
        new_row = [_valor_celda(data_n.get(_normalizar_nombre_col(h), "")) for h in headers]
        worksheet.append_row(new_row)
        return True
    except Exception as e:
        st.error(f"❌ Error al crear registro: {e}")
        return False


def find_row_by_values(search_dict, sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        records = worksheet.get_all_records()
        for idx, record in enumerate(records):
            if all(str(record.get(k, "")).strip() == str(v).strip() for k, v in search_dict.items()):
                return idx + 2
        return None
    except Exception as e:
        st.error(f"❌ Error al buscar registro: {e}")
        return None


def search_records(formula=None, sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    records = get_all_records(sheet_name, worksheet_name)
    if isinstance(formula, dict):
        return [r for r in records if all(str(r.get(k,"")).strip() == str(v).strip() for k,v in formula.items())]
    elif isinstance(formula, str):
        term = formula.lower().strip()
        return [r for r in records if any(term in str(v).lower() for v in r.values())]
    return records


def clear_cache():
    try:
        st.cache_data.clear()
    except:
        pass
