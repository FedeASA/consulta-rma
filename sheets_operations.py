"""
sheets_operations.py - Módulo para operaciones con Google Sheets
Reemplaza pyairtable con gspread + Google Sheets API
"""

import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import streamlit as st
from datetime import datetime
import json
import os

# Configuración de scopes de Google
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

@st.cache_resource
def get_sheets_client():
    """Obtiene el cliente autenticado de Google Sheets"""
    try:
        # Intenta cargar desde Streamlit secrets (prioritario)
        if "GOOGLE_CREDS" in st.secrets:
            creds_dict = st.secrets["GOOGLE_CREDS"]
            if isinstance(creds_dict, str):
                creds_dict = json.loads(creds_dict)
        else:
            raise KeyError("GOOGLE_CREDS not in secrets")
    except:
        # Si no están en secrets, intenta leer del archivo local
        try:
            if os.path.exists("creds_google.json"):
                with open("creds_google.json", "r") as f:
                    creds_dict = json.load(f)
            else:
                raise FileNotFoundError("creds_google.json not found")
        except:
            st.error("❌ Error: No se encontraron credenciales de Google.\n\n"
                    "Opciones:\n"
                    "1. Coloca 'creds_google.json' en la raíz del proyecto\n"
                    "2. O configura GOOGLE_CREDS en .streamlit/secrets.toml")
            st.stop()
    
    try:
        credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        client = gspread.authorize(credentials)
        return client
    except Exception as e:
        st.error(f"❌ Error al autenticar con Google: {e}")
        st.stop()

def get_sheet(sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    """
    Obtiene una hoja de trabajo específica del Google Sheets.
    
    Args:
        sheet_name: Nombre del archivo (Spreadsheet)
        worksheet_name: Nombre de la pestaña (Worksheet)
    
    Returns:
        Objeto worksheet de gspread
    """
    client = get_sheets_client()
    
    try:
        sheet = client.open(sheet_name)
        worksheet = sheet.worksheet(worksheet_name)
        return worksheet
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"❌ Error: No se encontró el sheet '{sheet_name}'\n\n"
                f"Verifica que el nombre sea exacto y que la cuenta de servicio tenga acceso.")
        st.stop()
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ Error: No se encontró la hoja '{worksheet_name}' en '{sheet_name}'\n\n"
                f"Columnas disponibles: {sheet.worksheets()}")
        st.stop()
    except Exception as e:
        st.error(f"❌ Error al acceder al sheet: {e}")
        st.stop()

def get_all_records(sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    """
    Obtiene todos los registros de la hoja como una lista de diccionarios.
    
    Returns:
        Lista de diccionarios con los registros
    """
    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        records = worksheet.get_all_records()
        return records if records else []
    except Exception as e:
        st.error(f"❌ Error al leer registros: {e}")
        return []

def get_dataframe(sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    """
    Obtiene todos los registros como un DataFrame de pandas.
    
    Returns:
        DataFrame con los datos
    """
    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        
        # Limpiar valores vacíos y None
        df = df.fillna("")
        df = df.replace(["None", "none", "nan", "NaN"], "")
        
        return df
    except Exception as e:
        st.error(f"❌ Error al leer datos: {e}")
        return pd.DataFrame()

def search_records(formula=None, sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    """
    Busca registros. Si es una búsqueda simple, realiza búsqueda en pandas.
    
    Args:
        formula: Diccionario con {campo: valor} para filtrar, o string para búsqueda flexible
        
    Returns:
        Lista de registros que coinciden
    """
    records = get_all_records(sheet_name, worksheet_name)
    
    if isinstance(formula, dict):
        # Búsqueda por campo específico
        results = []
        for record in records:
            match = True
            for key, value in formula.items():
                if str(record.get(key, "")).strip() != str(value).strip():
                    match = False
                    break
            if match:
                results.append(record)
        return results
    
    elif isinstance(formula, str):
        # Búsqueda flexible (búsqueda de contenido parcial)
        results = []
        search_term = formula.lower().strip()
        for record in records:
            for value in record.values():
                if search_term in str(value).lower():
                    results.append(record)
                    break
        return results
    
    return records

def create_record(data, sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    """
    Crea un nuevo registro en la hoja.
    
    Args:
        data: Diccionario con los datos del nuevo registro
        
    Returns:
        True si se creó exitosamente, False en caso contrario
    """
    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        # Obtener encabezados
        headers = worksheet.row_values(1)
        
        # Preparar fila con valores en el orden correcto
        new_row = []
        for header in headers:
            new_row.append(str(data.get(header, "")))
        
        # Añadir la fila al final
        worksheet.append_row(new_row)
        st.success("✅ Registro creado exitosamente")
        return True
    except Exception as e:
        st.error(f"❌ Error al crear registro: {e}")
        return False

def update_record(row_number, data, sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    """
    Actualiza un registro existente (por número de fila).
    
    Args:
        row_number: Número de fila (1-indexed, incluyendo encabezado)
        data: Diccionario con los datos a actualizar
        
    Returns:
        True si se actualizó exitosamente, False en caso contrario
    """
    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        headers = worksheet.row_values(1)
        
        if row_number < 2 or row_number > worksheet.row_count:
            st.warning(f"Número de fila inválido: {row_number}")
            return False
        
        # Obtener fila actual
        current_row = worksheet.row_values(row_number)
        
        # Preparar nueva fila
        new_row = []
        for i, header in enumerate(headers):
            if header in data:
                new_row.append(str(data[header]))
            else:
                new_row.append(str(current_row[i]) if i < len(current_row) else "")
        
        # Actualizar cada celda
        for col_idx, value in enumerate(new_row, start=1):
            try:
                worksheet.update_cell(row_number, col_idx, value)
            except Exception as cell_error:
                # Continuar con las demás celdas aunque una falle
                pass
        
        return True
    except Exception as e:
        st.warning(f"⚠️ Error al actualizar registro en fila {row_number}: {e}")
        return False

def delete_row(row_number, sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    """
    Elimina una fila específica (por número de fila).
    
    Args:
        row_number: Número de fila (1-indexed, incluyendo encabezado)
        
    Returns:
        True si se eliminó exitosamente, False en caso contrario
    """
    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        if row_number < 2:  # No permitir eliminar encabezado
            st.warning("No se puede eliminar el encabezado")
            return False
        
        worksheet.delete_rows(row_number)
        return True
    except Exception as e:
        st.error(f"❌ Error al eliminar registro: {e}")
        return False

def find_row_by_values(search_dict, sheet_name="Proveedores", worksheet_name="RMA ALTAVISTA"):
    """
    Encuentra el número de fila de un registro que coincida con los valores especificados.
    
    Args:
        search_dict: Diccionario con {campo: valor} a buscar
        
    Returns:
        Número de fila (1-indexed) o None si no encuentra
    """
    worksheet = get_sheet(sheet_name, worksheet_name)
    try:
        records = worksheet.get_all_records()
        
        for idx, record in enumerate(records):
            match = True
            for key, value in search_dict.items():
                if str(record.get(key, "")).strip() != str(value).strip():
                    match = False
                    break
            if match:
                return idx + 2  # +1 por encabezado, +1 porque los índices comienzan en 0
        
        return None
    except Exception as e:
        st.error(f"❌ Error al buscar registro: {e}")
        return None

def clear_cache():
    """Limpia el caché de datos (para forzar recarga)"""
    try:
        st.cache_data.clear()
    except:
        pass

