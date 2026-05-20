import streamlit as st
from pyairtable import Api
import pandas as pd
from datetime import datetime, date
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="Panel RMA", layout="wide")

st.markdown("""
    <style>
        .block-container {
            max-width: 100% !important;
            padding-left: 2rem !important;
            padding-right: 2rem !important;
            padding-top: 4rem;
        }
        div[data-testid="stExpander"] { border: 1px solid #444; margin-bottom: 1rem; }
        [data-testid="stDataEditor"] div, .stDataTable td {
            border-bottom: 4px solid #000 !important;
        }
        .stDataTable td, .stDataTable th, [data-testid="stDataEditor"] * {
            font-family: sans-serif !important;
            font-size: 14px !important;
            font-weight: 400 !important;
        }
        .stDataTable td, .stDataTable th {
            border-right: 1px solid #444 !important;
        }
        div[data-testid="stGridVirtualizingContainer"] div {
            --background-color: transparent !important;
        }
        [data-testid="stDataEditor"] td div input, 
        [data-testid="stDataEditor"] td div div,
        [data-testid="stDataEditor"] [role="gridcell"] * {
            background-color: inherit !important;
            color: inherit !important;
        }
        .menu-dropdown {
            position: relative;
            display: inline-block;
            width: 100%;
        }
        .menu-boton {
            width: 100%; 
            padding: 0.55rem; 
            border-radius: 0.5rem; 
            background-color: #262730; 
            color: white; 
            border: 1px solid #4a4a4a;
            font-family: sans-serif;
            font-size: 14px;
            text-align: left;
            cursor: pointer;
        }
        .menu-contenido {
            display: none;
            position: absolute;
            background-color: #1e1e24;
            min-width: 100%;
            box-shadow: 0px 8px 16px 0px rgba(0,0,0,0.5);
            z-index: 9999;
            border-radius: 0.5rem;
            border: 1px solid #4a4a4a;
            margin-top: 2px;
        }
        .menu-contenido a {
            color: white;
            padding: 10px 16px;
            text-decoration: none;
            display: block;
            font-family: sans-serif;
            font-size: 14px;
        }
        .menu-contenido a:hover {
            background-color: #262730;
            border-radius: 0.5rem;
        }
        .menu-dropdown:hover .menu-contenido {
            display: block;
        }
    </style>
    """, unsafe_allow_html=True)

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.usuario = ""
    st.session_state.rol = ""

def login():
    st.markdown("<h2 style='text-align: center;'>Control de Acceso - Panel RMA</h2>", unsafe_allow_html=True)
    with st.form("formulario_login"):
        usuario = st.text_input("Usuario:").strip()
        clave = st.text_input("Contraseña:", type="password").strip()
        bot_login = st.form_submit_button("Iniciar Sesión", use_container_width=True)
        
        if bot_login:
            try:
                usuarios_secretos = st.secrets["USUARIOS"]
                if usuario in usuarios_secretos and usuarios_secretos[usuario] == clave:
                    st.session_state.autenticado = True
                    st.session_state.usuario = usuario
                    st.session_state.rol = "admin" if usuario == "admin" else "user"
                    st.success("¡Acceso concedido!")
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos.")
            except Exception:
                st.error("Error de configuración: No se encontró la sección [USUARIOS] en los Secrets.")

if not st.session_state.autenticado:
    login()
    st.stop()

# --- BARRA LATERAL ---
st.sidebar.write(f"Conectado como: **{st.session_state.usuario}** ({st.session_state.rol.upper()})")

if st.sidebar.button("Cerrar Sesión", type="secondary", use_container_width=True):
    st.session_state.autenticado = False
    st.session_state.usuario = ""
    st.session_state.rol = ""
    st.rerun()

try:
    AIRTABLE_TOKEN = st.secrets["AIRTABLE_TOKEN"]
    BASE_ID = st.secrets["BASE_ID"]
    TABLE_NAME = st.secrets
