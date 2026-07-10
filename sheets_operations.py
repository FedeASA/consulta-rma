"""
sheets_operations.py - Módulo para operaciones con Google Sheets
"""

import gspread
from gspread.exceptions import APIError
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
import pandas as pd
import streamlit as st
from datetime import datetime
import json
import os
import time
import io

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
        return build("drive", "v3", credentials=credentials, cache_discovery=False)
    except Exception as e:
        st.error(f"❌ Error al conectar con Google Drive: {e}")
        st.stop()


def _get_drive_folder_id():
    try:
        return st.secrets["DRIVE_FOTOS_RMA_FOLDER_ID"]
    except Exception:
        st.error(
            "❌ Falta configurar 'DRIVE_FOTOS_RMA_FOLDER_ID' en Secrets con el ID "
            "de la carpeta de Drive donde se guardan las fotos de los RMA."
        )
        st.stop()


def subir_foto_a_drive(bytes_imagen, nombre_archivo):
    """Sube una foto (bytes JPEG) a la carpeta de Drive configurada.
    Devuelve el ID del archivo en Drive, o None si falló."""
    try:
        servicio = get_drive_service()
        folder_id = _get_drive_folder_id()
        metadata = {"name": nombre_archivo, "parents": [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(bytes_imagen), mimetype="image/jpeg", resumable=False)
        archivo = _safe_api_call(lambda: servicio.files().create(
            body=metadata, media_body=media, fields="id"
        ).execute())
        return archivo.get("id")
    except Exception as e:
        st.error(f"❌ Error al subir la foto a Drive: {e}")
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def descargar_foto_de_drive(file_id):
    """Descarga los bytes de una foto guardada en Drive (cacheado 1 hora)."""
    if not file_id:
        return None
    try:
        servicio = get_drive_service()
        solicitud = servicio.files().get_media(fileId=file_id)
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
        _safe_api_call(lambda: servicio.files().delete(fileId=file_id).execute())
        return True
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
    """Reintenta una llamada a la API si hay error 429."""
    for attempt in range(retries):
        try:
            return fn()
        except APIError as e:
            if "429" in str(e) and attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
            else:
                raise


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
        new_row = []
        for i, header in enumerate(headers):
            if header in data:
                val = data[header]
                if isinstance(val, bool):
                    new_row.append("TRUE" if val else "FALSE")
                else:
                    new_row.append(str(val) if val is not None else "")
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


def batch_update_records(records_to_update, sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    """
    ✅ NUEVO: Actualiza MÚLTIPLES filas en el menor número de requests posible.
    Usar esto en lugar de llamar update_record en un loop.
    
    Args:
        records_to_update: lista de {"row": row_number, "data": {campo: valor}}
    """
    if not records_to_update:
        return True

    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        headers = _get_cached_headers(sheet_name, worksheet_name)

        # Una sola lectura de TODOS los datos actuales
        all_rows = _safe_api_call(lambda: worksheet.get_all_values())

        batch_data = []
        for rec in records_to_update:
            row_number = rec["row"]
            data = rec["data"]

            if row_number < 2 or row_number > len(all_rows) + 1:
                continue

            current_row = all_rows[row_number - 1]  # 0-indexed

            new_row = []
            for i, header in enumerate(headers):
                if header in data:
                    val = data[header]
                    if isinstance(val, bool):
                        new_row.append("TRUE" if val else "FALSE")
                    else:
                        new_row.append(str(val) if val is not None else "")
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


def create_record(data, sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        headers = _get_cached_headers(sheet_name, worksheet_name)
        new_row = [str(data.get(header, "")) for header in headers]
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
