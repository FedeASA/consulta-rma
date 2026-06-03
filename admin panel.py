import streamlit as st
from pyairtable import Api
import pandas as pd
from datetime import datetime, date
import io
import smtplib
import requests
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
        /* ── Estilos panel Urbano ── */
        .urbano-card {
            background: #1a1f2e;
            border: 1px solid #2d4a7a;
            border-radius: 8px;
            padding: 1rem 1.2rem;
            margin-bottom: 0.5rem;
        }
        .urbano-card-ok {
            border-color: #2ea043;
            background: #0d1f12;
        }
        .urbano-card-warn {
            border-color: #d29922;
            background: #1f1a0d;
        }
        .urbano-label {
            font-size: 11px;
            color: #8b949e;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 2px;
        }
        .urbano-valor-nuevo {
            font-size: 15px;
            font-weight: 600;
            color: #3fb950;
        }
        .urbano-valor-actual {
            font-size: 13px;
            color: #8b949e;
            text-decoration: line-through;
        }
        .urbano-valor-igual {
            font-size: 15px;
            color: #c9d1d9;
        }
    </style>
    """, unsafe_allow_html=True)

# ── URL del puente local ───────────────────────────────────────────────────────
URBANO_BRIDGE_URL = "http://localhost:8765"

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.usuario = ""
    st.session_state.rol = ""

# Estado para el panel de verificación Urbano
if "urbano_resultados" not in st.session_state:
    st.session_state.urbano_resultados = {}   # {id_interno: datos_urbano}
if "urbano_seleccion" not in st.session_state:
    st.session_state.urbano_seleccion = {}    # {id_interno: {campo: bool}}


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

# ── Estado del puente Urbano en sidebar ───────────────────────────────────────
st.sidebar.divider()
try:
    r = requests.get(f"{URBANO_BRIDGE_URL}/ping", timeout=2)
    if r.status_code == 200:
        st.sidebar.success("🟢 Urbano Bridge activo")
    else:
        st.sidebar.warning("🟡 Puente responde con error")
except Exception:
    st.sidebar.error("🔴 Urbano Bridge inactivo")
    st.sidebar.caption("Ejecutá `urbano_bridge.py` en tu PC para habilitar la verificación automática.")

try:
    AIRTABLE_TOKEN = st.secrets["AIRTABLE_TOKEN"]
    BASE_ID = st.secrets["BASE_ID"]
    TABLE_NAME = st.secrets["TABLE_NAME"]
    api = Api(AIRTABLE_TOKEN)
    table = api.table(BASE_ID, TABLE_NAME)
except Exception as e:
    st.error(f"Error en credenciales: {e}")
    st.stop()

# --- ENVIADOR DE CORREOS CONFIGURABLE ---
def despachar_correo(config_section, destinatario, asunto, cuerpo_texto):
    try:
        if config_section not in st.secrets:
            st.error(f"Falta la seccion [{config_section}] en Secrets.")
            return False
        smtp_user = st.secrets[config_section]["SMTP_USER"]
        smtp_password = st.secrets[config_section]["SMTP_PASSWORD"]
        destinatario_limpio = str(destinatario).strip().lower()
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = destinatario_limpio
        msg['Subject'] = asunto
        msg.attach(MIMEText(cuerpo_texto, 'plain', 'utf-8'))
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15)
        server.login(smtp_user, smtp_password)
        rechazados = server.sendmail(smtp_user, destinatario_limpio, msg.as_string())
        server.quit()
        if rechazados:
            st.error(f"Google rechazo la entrega para el destinatario: {rechazados}")
            return False
        return True
    except Exception as e:
        st.error(f"Fallo el envio en [{config_section}] hacia ({destinatario}): {str(e)}")
        return False

def estilo_filas(row):
    estado = str(row.get('Estado del RMA', "")).upper()
    verde, naranja, celeste, rojo, gris = 'background-color: #28a745; color: white;', 'background-color: #fd7e14; color: black;', 'background-color: #17a2b8; color: white;', 'background-color: #dc3545; color: white;', 'background-color: #6c757d; color: white;'
    style = ''
    if estado in ["CAMBIO", "CREDITO"]: style = verde
    elif estado in ["GARANTIA", "GARANTIA OFICIAL"]: style = naranja
    elif estado == "NO FALLO - DEVOLVER A CLIENTE": style = celeste
    elif estado == "FUERA DE GARANTIA": style = rojo
    elif estado == "REPARADO": style = gris
    return [style if col != 'Finalizado' else '' for col in row.index]

def formatear_para_leer(fecha_raw):
    if not fecha_raw or str(fecha_raw).strip() in ["None", "none", "nan", "NaN", ""]: return ""
    fecha_str = str(fecha_raw).replace('-', '/').strip()
    for formato in ['%Y/%m/%d', '%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y']:
        try:
            dt = datetime.strptime(fecha_str, formato)
            return dt.strftime('%d/%m/%Y')
        except ValueError: continue
    return str(fecha_raw)

def formatear_y_validar_fecha(fecha_texto):
    if not fecha_texto or str(fecha_texto).strip() == "": return None, "OK"
    texto = str(fecha_texto).replace('-', '/').strip()
    for formato in ['%d/%m/%y', '%d/%m/%Y', '%d-%m-%Y', '%d-%m-%y']:
        try:
            dt_objeto = datetime.strptime(texto, formato)
            if dt_objeto.date() > date.today(): return None, "FUTURA"
            return dt_objeto.strftime('%Y-%m-%d'), "OK"
        except ValueError: continue
    return None, "FORMATO_INVALIDO"

@st.cache_data(ttl=5)
def cargar_todos_los_datos():
    all_records = table.all()
    if not all_records: return pd.DataFrame()
    rows = []
    for r in all_records:
        fields = r['fields']
        fields['id_interno'] = r['id']
        rows.append(fields)
    return pd.DataFrame(rows)

df_all = cargar_todos_los_datos()

# ─────────────────────────────────────────────────────────────────────────────
# FUNCIÓN PRINCIPAL: Consultar Urbano Bridge
# ─────────────────────────────────────────────────────────────────────────────
def consultar_urbano(serial: str) -> dict:
    """Llama al bridge local y retorna los datos del serial."""
    try:
        r = requests.get(f"{URBANO_BRIDGE_URL}/consultar/{serial.strip()}", timeout=15)
        if r.status_code == 200:
            return r.json()
        else:
            return {"encontrado": False, "error": f"HTTP {r.status_code}: {r.text}"}
    except requests.exceptions.ConnectionError:
        return {"encontrado": False, "error": "No se puede conectar al Urbano Bridge. ¿Está corriendo urbano_bridge.py?"}
    except Exception as e:
        return {"encontrado": False, "error": str(e)}


def normalizar_fecha_urbano(fecha_str: str) -> str:
    """Convierte fecha de Urbano (DD-MM-YYYY o DD/MM/YYYY) a formato legible DD/MM/YYYY."""
    if not fecha_str: return ""
    return formatear_para_leer(fecha_str)


def campo_es_diferente(valor_actual, valor_urbano) -> bool:
    """Compara dos valores ignorando mayúsculas y espacios."""
    a = str(valor_actual).strip().lower()
    b = str(valor_urbano).strip().lower()
    return a != b and b not in ["", "none", "nan"]


# ─────────────────────────────────────────────────────────────────────────────
# PANEL DE VERIFICACIÓN URBANO (se muestra debajo de Tabla 1)
# ─────────────────────────────────────────────────────────────────────────────
def mostrar_panel_verificacion_urbano(df1_actual):
    """
    Muestra el panel de resultados de Urbano para los tickets consultados.
    Permite al admin seleccionar qué campos aplicar y confirmar la actualización.
    """
    if not st.session_state.urbano_resultados:
        return

    st.markdown("### 🔍 Verificación Urbano — Resultados")
    st.caption("Revisá los datos encontrados. Los campos en **verde** difieren del valor actual. Seleccioná cuáles aplicar y confirmá.")

    cambios_a_aplicar = {}  # {id_interno: {campo_airtable: valor_nuevo}}

    for id_interno, datos in st.session_state.urbano_resultados.items():
        # Buscar fila original
        fila_orig = df1_actual[df1_actual['id_interno'] == id_interno]
        if fila_orig.empty:
            continue
        orig = fila_orig.iloc[0]

        serial = orig.get('Serial', id_interno)
        rma_num = orig.get('autonumero', '')

        if not datos.get('encontrado', False):
            with st.container(border=True):
                st.markdown(f"**Serial: {serial}** {'— RMA #' + str(rma_num) if rma_num else ''}")
                st.warning(f"❌ No encontrado en Urbano: {datos.get('error', datos.get('mensaje', 'Sin datos'))}")
            continue

        # Mapeo de campos: (label, campo_airtable, valor_urbano, valor_actual)
        fecha_urbano_legible = normalizar_fecha_urbano(datos.get('fecha_compra', ''))
        
        campos = [
            ("Producto / SKU",  "Producto",   datos.get('producto_completo', ''),  orig.get('Producto', '')),
            ("Cliente (código)","Cliente",     datos.get('cliente_codigo', ''),     orig.get('Cliente', '')),
            ("Fecha de Compra", "Compra",      fecha_urbano_legible,                formatear_para_leer(orig.get('Compra', ''))),
            ("Proveedor",       "Proveedor",   datos.get('proveedor_nombre', ''),   orig.get('Proveedor', '')),
        ]

        hay_diferencias = any(campo_es_diferente(va, vu) for _, _, vu, va in campos if vu)

        with st.container(border=True):
            encabezado = f"**Serial: {serial}**"
            if rma_num:
                encabezado += f" — RMA #{rma_num}"
            if hay_diferencias:
                encabezado += " 🟡 hay diferencias"
            else:
                encabezado += " ✅ datos coinciden"
            st.markdown(encabezado)

            if not hay_diferencias:
                st.caption("Los datos de Airtable ya coinciden con Urbano. No hay nada que actualizar.")
                continue

            # Inicializar selección para este ticket
            if id_interno not in st.session_state.urbano_seleccion:
                st.session_state.urbano_seleccion[id_interno] = {}

            cols = st.columns(len([c for c in campos if c[2]]))
            col_idx = 0
            campos_seleccionados = {}

            for label, campo_at, valor_urbano, valor_actual in campos:
                if not valor_urbano:
                    continue
                with cols[col_idx]:
                    es_diferente = campo_es_diferente(valor_actual, valor_urbano)
                    st.markdown(f"<div class='urbano-label'>{label}</div>", unsafe_allow_html=True)

                    if es_diferente:
                        st.markdown(f"<div class='urbano-valor-nuevo'>→ {valor_urbano}</div>", unsafe_allow_html=True)
                        if valor_actual:
                            st.markdown(f"<div class='urbano-valor-actual'>actual: {valor_actual}</div>", unsafe_allow_html=True)
                        key_check = f"urb_{id_interno}_{campo_at}"
                        aplicar = st.checkbox(
                            "Aplicar",
                            value=st.session_state.urbano_seleccion[id_interno].get(campo_at, True),
                            key=key_check
                        )
                        st.session_state.urbano_seleccion[id_interno][campo_at] = aplicar
                        if aplicar:
                            campos_seleccionados[campo_at] = valor_urbano
                    else:
                        st.markdown(f"<div class='urbano-valor-igual'>{valor_urbano}</div>", unsafe_allow_html=True)
                        st.caption("✓ igual")
                col_idx += 1

            if campos_seleccionados:
                cambios_a_aplicar[id_interno] = campos_seleccionados

    # ── Botón de confirmación global ─────────────────────────────────────────
    if cambios_a_aplicar:
        total_cambios = sum(len(v) for v in cambios_a_aplicar.values())
        st.divider()
        col_btn, col_info = st.columns([1, 3])
        with col_btn:
            if st.button(f"✅ Aplicar {total_cambios} cambio(s) en Airtable", type="primary", use_container_width=True):
                errores = []
                exitos = 0
                for id_rec, campos_upd in cambios_a_aplicar.items():
                    payload = {}
                    for campo_at, valor_nuevo in campos_upd.items():
                        # Convertir fecha al formato Airtable (YYYY-MM-DD) antes de guardar
                        if campo_at == "Compra":
                            fecha_fmt, estado = formatear_y_validar_fecha(valor_nuevo)
                            if estado == "OK" and fecha_fmt:
                                payload["Compra"] = fecha_fmt
                        else:
                            payload[campo_at] = valor_nuevo

                    if payload:
                        try:
                            table.update(id_rec, payload)
                            exitos += 1
                        except Exception as e:
                            errores.append(f"{id_rec}: {str(e)}")

                if errores:
                    st.error(f"Errores al guardar: {'; '.join(errores)}")
                else:
                    st.success(f"✅ {exitos} ticket(s) actualizados correctamente en Airtable.")
                    st.session_state.urbano_resultados = {}
                    st.session_state.urbano_seleccion = {}
                    cargar_todos_los_datos.clear()
                    st.rerun()
        with col_info:
            tickets_afectados = len(cambios_a_aplicar)
            st.info(f"Se actualizarán **{total_cambios} campo(s)** en **{tickets_afectados} ticket(s)**.")


# ─────────────────────────────────────────────────────────────────────────────
# LINKS ADMIN
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.rol == "admin":
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.link_button("🔵 Airtable", "https://airtable.com/appjlLix1HpBwnhpS/tblNnoXdIsLFN92Mr/viwLRiCozAc4oVKZY", use_container_width=True)
    with c2: st.link_button("💻 Github", "https://github.com/FedeASA/consulta-rma", use_container_width=True)
    with c3: st.link_button("📝 Texto Clientes", "https://docs.google.com/document/d/1URgFPuVsIoR6LX2diAwFR5rWRKYvmmEwvQ7VXuxSnYg", use_container_width=True)
    with c4:
        st.markdown("""
            <div class="menu-dropdown">
                <button class="menu-boton">🚀 Páginas... ▾</button>
                <div class="menu-contenido">
                    <a href="https://formulariorma.streamlit.app/" target="_blank">Formulario ↗</a>
                    <a href="https://rma-altavista.streamlit.app/" target="_blank">Consulta ↗</a>
                    <a href="https://share.streamlit.io/" target="_blank">Streamlit Base ↗</a>
                </div>
            </div>
        """, unsafe_allow_html=True)
    with c5: st.link_button("📊 Excel Viejo", "https://docs.google.com/spreadsheets/d/17zp1kEZhVBw1Ul3HkoDZhyQ2IYthjNGS", use_container_width=True)

# --- BOTONES DE ACCIÓN SUPERIORES ---
col_rep1, col_btn_refresh, col_rep2 = st.columns([1, 1, 3])
with col_rep1:
    btn_reporte = st.button("📊 Reporte", use_container_width=True)
with col_btn_refresh:
    if st.button("🔄 Actualizar Datos", use_container_width=True):
        cargar_todos_los_datos.clear()
        st.rerun()

if btn_reporte:
    st.session_state.mostrar_input_reporte = not st.session_state.get('mostrar_input_reporte', False)

if st.session_state.get('mostrar_input_reporte', False):
    with st.container(border=True):
        cliente_buscado = st.text_input("Ingrese nombre del Cliente para generar Excel:")
        if cliente_buscado:
            df_rep = df_all[df_all['Cliente'].astype(str).str.contains(cliente_buscado, case=False, na=False)].copy() if 'Cliente' in df_all.columns else pd.DataFrame()
            if not df_rep.empty:
                cols_sel = ['Producto', 'Compra', 'Falla', 'Serial', 'Ingreso', 'Estado del RMA', 'Resolucion']
                for c in cols_sel:
                    if c not in df_rep.columns: df_rep[c] = ""
                df_exc = df_rep[cols_sel].copy()
                df_exc['Resolucion_clean'] = df_exc['Resolucion'].astype(str).str.strip().replace(["None", "none", "nan", "NaN"], "")
                df_exc['Resolucion_dt'] = pd.to_datetime(df_exc['Resolucion_clean'], errors='coerce')
                df_exc = df_exc.sort_values(by='Resolucion_dt', ascending=False).drop(columns=['Resolucion_dt', 'Resolucion_clean'])
                for f in ['Compra', 'Ingreso', 'Resolucion']:
                    df_exc[f] = df_exc[f].apply(formatear_para_leer)
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    df_exc.to_excel(writer, index=False, sheet_name='Reporte', startrow=2)
                    workbook  = writer.book
                    worksheet = writer.sheets['Reporte']
                    formato_titulo = workbook.add_format({'bold': True, 'font_size': 14, 'font_name': 'Segoe UI'})
                    formato_encabezado = workbook.add_format({'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#000000', 'border': 1, 'border_color': '#000000', 'align': 'center', 'valign': 'vcenter', 'font_name': 'Segoe UI', 'font_size': 11})
                    formato_celda = workbook.add_format({'border': 1, 'border_color': '#000000', 'valign': 'vcenter', 'font_name': 'Segoe UI', 'font_size': 10})
                    worksheet.write(0, 0, f"REPORTE DE RMA - CLIENTE: {cliente_buscado.upper()}", formato_titulo)
                    for col_num, header_title in enumerate(df_exc.columns):
                        worksheet.write(1, col_num, header_title, formato_encabezado)
                    for i, col in enumerate(df_exc.columns):
                        max_len = len(col)
                        for row_idx in range(len(df_exc)):
                            val_raw = df_exc.iloc[row_idx, i]
                            val_celda = "" if pd.isna(val_raw) or str(val_raw).strip() in ["NaT", "None", "nan", "NaN"] else str(val_raw)
                            if len(val_celda) > max_len:
                                max_len = len(val_celda)
                            worksheet.write(row_idx + 2, i, val_celda, formato_celda)
                        worksheet.set_column(i, i, max_len + 4)
                    worksheet.set_row(1, 24)
                st.download_button(label=f"📥 Descargar Reporte {cliente_buscado}", data=output.getvalue(), file_name=f"Reporte_{cliente_buscado}_{datetime.now().strftime('%d_%m_%Y')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                st.warning("No hay datos para ese cliente.")
st.divider()

if df_all.empty:
    st.warning("No hay datos para mostrar.")
    st.stop()

# --- VERIFICACIÓN Y COMPATIBILIDAD DE COLUMNAS EXTRA ---
columnas_requeridas = ['Aceptado', 'Finalizado', 'Ingreso', 'Resolucion', 'diagnostico', 'Estado del RMA', 'Compra', 'Producto', 'comentario', 'Falla', 'Serial', 'autonumero', 'Telefono', 'Email', 'Motivo del trámite', 'Proveedor']
for col in columnas_requeridas:
    if col not in df_all.columns: 
        df_all[col] = False if col in ['Aceptado', 'Finalizado'] else ""
    else:
        if col in ['Aceptado', 'Finalizado']:
            df_all[col] = df_all[col].apply(lambda x: True if x in [True, 1, "True", "true"] else False)

for col_txt in ['comentario', 'Falla', 'diagnostico', 'Ingreso', 'Resolucion', 'Compra', 'Cliente', 'Producto', 'Serial', 'autonumero', 'Telefono', 'Email', 'Motivo del trámite', 'Proveedor']:
    if col_txt in df_all.columns:
        df_all[col_txt] = df_all[col_txt].fillna("").apply(lambda x: str(int(x)) if isinstance(x, float) and x.is_integer() else str(x))
        df_all[col_txt] = df_all[col_txt].apply(lambda x: "" if str(x).strip() in ["None", "none", "nan", "NaN", ""] else str(x).strip())

# =============================================================================
# TABLA 1: POR ACEPTAR
# =============================================================================
df1 = df_all[
    (df_all['Aceptado'] == False) & 
    (df_all['Producto'].str.strip() != "") & 
    (df_all['Cliente'].str.strip() != "")
].copy()

with st.expander("📥 1. TICKETS POR ACEPTAR (Entrada)", expanded=True):
    if not df1.empty:
        if 'Compra' in df1.columns:
            df1 = df1.sort_values(by='Compra', ascending=False)
        df1['Compra'] = df1['Compra'].apply(formatear_para_leer)

        # ── Botones de verificación Urbano ────────────────────────────────────
        if st.session_state.rol == "admin":
            st.markdown("**Verificar datos contra Urbano SQL:**")
            
            col_urb1, col_urb2, col_urb3 = st.columns([1, 1, 4])
            
            with col_urb1:
                verificar_todos = st.button("🔍 Verificar TODOS", use_container_width=True, help="Consulta Urbano para todos los tickets con serial")
            with col_urb2:
                if st.button("🗑️ Limpiar resultados", use_container_width=True):
                    st.session_state.urbano_resultados = {}
                    st.session_state.urbano_seleccion = {}
                    st.rerun()

            if verificar_todos:
                seriales_a_consultar = df1[df1['Serial'].str.strip() != ''][['id_interno', 'Serial']].values.tolist()
                if not seriales_a_consultar:
                    st.warning("No hay tickets con número de serie para verificar.")
                else:
                    progress = st.progress(0, text="Consultando Urbano...")
                    nuevos_resultados = {}
                    for i, (id_int, serial) in enumerate(seriales_a_consultar):
                        progress.progress((i + 1) / len(seriales_a_consultar), text=f"Consultando serial {serial} ({i+1}/{len(seriales_a_consultar)})...")
                        resultado = consultar_urbano(serial)
                        nuevos_resultados[id_int] = resultado
                    progress.empty()
                    st.session_state.urbano_resultados.update(nuevos_resultados)
                    encontrados = sum(1 for v in nuevos_resultados.values() if v.get('encontrado'))
                    st.success(f"✅ Consulta completada: {encontrados}/{len(seriales_a_consultar)} seriales encontrados en Urbano.")

            # ── Verificación individual por fila ─────────────────────────────
            st.caption("O verificá ticket por ticket:")
            filas_con_serial = df1[df1['Serial'].str.strip() != '']
            
            if not filas_con_serial.empty:
                cols_botones = st.columns(min(len(filas_con_serial), 6))
                for i, (_, fila) in enumerate(filas_con_serial.iterrows()):
                    col_i = i % len(cols_botones)
                    with cols_botones[col_i]:
                        serial_btn = fila['Serial']
                        id_btn = fila['id_interno']
                        rma_btn = fila.get('autonumero', serial_btn[:8])
                        ya_verificado = id_btn in st.session_state.urbano_resultados
                        label_btn = f"{'✓' if ya_verificado else '🔍'} #{rma_btn}"
                        if st.button(label_btn, key=f"urb_btn_{id_btn}", use_container_width=True, help=f"Serial: {serial_btn}"):
                            with st.spinner(f"Consultando {serial_btn}..."):
                                resultado = consultar_urbano(serial_btn)
                                st.session_state.urbano_resultados[id_btn] = resultado
                            st.rerun()

        # ── Panel de resultados Urbano ────────────────────────────────────────
        mostrar_panel_verificacion_urbano(df1)

        st.divider()

        # ── Tabla editable (igual que antes) ─────────────────────────────────
        with st.form("f1"):
            if st.session_state.rol == "admin":
                c1_cols = ['Cliente', 'Producto', 'Serial', 'Falla', 'Compra', 'Aceptado']
                esta_deshabilitado_t1 = ['Serial', 'Falla']
            else:
                c1_cols = ['Cliente', 'Producto', 'Serial', 'Falla']
                esta_deshabilitado_t1 = ['Cliente', 'Producto', 'Serial', 'Falla']
            
            ed1 = st.data_editor(df1[['id_interno'] + c1_cols].reset_index(drop=True), column_config={"id_interno": None}, disabled=esta_deshabilitado_t1, hide_index=True, use_container_width=True)
            
            if st.form_submit_button("GUARDAR ENTRADAS", disabled=(st.session_state.rol != "admin")):
                for _, r in ed1.iterrows():
                    orig = df1[df1['id_interno'] == r['id_interno']].iloc[0]
                    
                    esta_aceptando = False
                    if 'Aceptado' in r and r['Aceptado'] == True and orig.get('Aceptado') == False:
                        esta_aceptando = True
                    
                    up = {k: r[k] for k in ['Aceptado', 'Cliente', 'Producto'] if k in r and str(r[k]) != str(orig.get(k, ""))}
                    if 'Compra' in r:
                        f, e = formatear_y_validar_fecha(r['Compra'])
                        if e == "OK" and f: up['Compra'] = f
                    
                    if esta_aceptando:
                        cliente_nom = orig.get('Cliente', '')
                        prod_nom = orig.get('Producto', '')
                        serial_num = orig.get('Serial', '')
                        falla_desc = orig.get('Falla', '')
                        fecha_compra_str = formatear_para_leer(orig.get('Compra', ''))
                        motivo_tramite = orig.get('Motivo del trámite', 'RMA')
                        if not motivo_tramite: motivo_tramite = "RMA"
                        rma_id = orig.get('autonumero', '')
                        cliente_id = orig.get('Cliente', '')
                        estado_rma = "PENDIENTE"
                        telefono_val = orig.get('Telefono', '').strip()
                        email_val = orig.get('Email', '').strip().lower()
                        
                        if telefono_val != "":
                            asunto_ws = "Caso aceptado - Mensaje para el cliente"
                            cuerpo_ws = (
                                f"RMA ACEPTADO - MENSAJE PARA CLIENTE\n"
                                f"wa.me/{telefono_val}\n"
                                f"---------------------------------------------------------------------------------------------------------------------------\n"
                                f"Su solicitud para {motivo_tramite} del producto {prod_nom} ha sido aceptada.\n\n"
                                f"Se le asignó el siguiente número de caso: {rma_id}\n"
                                f"Su código de cliente es: {cliente_id}\n\n"
                                f"--------------------------------------------------\n\n"
                                f"Detalle del caso:\n"
                                f"Producto: {prod_nom}\n"
                                f"Serial: {serial_num}\n"
                                f"Falla: {falla_desc}\n"
                                f"Fecha Compra: {fecha_compra_str}\n"
                                f"Estado del caso: {estado_rma}\n\n"
                                f"--------------------------------------------------\n\n"
                                f"Le recomendamos anotar su código de usuario para poder consultar el estado de sus casos en el siguiente enlace https://rma-altavista.streamlit.app/\n\n"
                                f"Cuando tengamos novedades le notificaremos por este canal.\n\n"
                                f"Recuerde que nos puede contactar en:\n"
                                f"WhatsApp: 3433002458\n"
                                f"Email: federico@altavistasa.com.ar"
                            )
                            despachar_correo("EMAIL_INTERNO", "federico@altavistasa.com.ar", asunto_ws, cuerpo_ws)
                            
                        elif email_val != "":
                            asunto_email = f"ALTAVISTA SA – {motivo_tramite} - Caso aceptado."
                            cuerpo_email = (
                                f"Su solicitud para {motivo_tramite} del producto {prod_nom} ha sido aceptada.\n\n"
                                f"Se le asignó el siguiente número de caso: {rma_id}\n"
                                f"Su código de cliente es: {cliente_id}\n\n"
                                f"--------------------------------------------------\n\n"
                                f"Detalle del caso:\n"
                                f"Producto: {prod_nom}\n"
                                f"Serial: {serial_num}\n"
                                f"Falla: {falla_desc}\n"
                                f"Fecha Compra: {fecha_compra_str}\n"
                                f"Estado del caso: {estado_rma}\n\n"
                                f"--------------------------------------------------\n\n"
                                f"Le recomendamos anotar su código de usuario para poder consultar el estado de sus casos en el siguiente enlace https://rma-altavista.streamlit.app/\n\n"
                                f"Cuando tengamos novedades le notificaremos por este canal.\n\n"
                                f"Recuerde que nos puede contactar en:\n"
                                f"WhatsApp: 3433002458\n"
                                f"Email: federico@altavistasa.com.ar"
                            )
                            despachar_correo("EMAIL_CLIENTE", email_val, asunto_email, cuerpo_email)
                    
                    if up: 
                        table.update(r['id_interno'], up)
                        
                cargar_todos_los_datos.clear()
                st.rerun()
    else:
        st.info("No hay pendientes.")

# --- TABLA 2: EN PROCESO ---
df2 = df_all[(df_all['Aceptado'] == True) & (df_all['Finalizado'] == False)].copy().reset_index(drop=True)
with st.expander("⚙️ 2. TICKETS EN PROCESO (Aceptados)", expanded=True):
    if not df2.empty:
        for c in ['Compra', 'Ingreso', 'Resolucion']: 
            df2[c] = df2[c].apply(formatear_para_leer)
        
        with st.form("f2"):
            if st.session_state.rol == "admin":
                c2_cols = ['autonumero', 'Cliente', 'Producto', 'Serial', 'Falla', 'Ingreso', 'diagnostico', 'Estado del RMA', 'Finalizado']
                deshabilitados_t2 = ['autonumero', 'Cliente', 'Producto', 'Serial', 'Falla']
            else:
                c2_cols = ['comentario', 'Cliente', 'Producto', 'Ingreso', 'diagnostico', 'Estado del RMA', 'Resolucion']
                deshabilitados_t2 = ['Cliente', 'Producto', 'Ingreso', 'diagnostico', 'Estado del RMA', 'Resolucion']
            
            st_df2 = df2[['id_interno'] + c2_cols]
            
            ed2 = st.data_editor(
                st_df2.style.apply(estilo_filas, axis=1), 
                column_config={
                    "id_interno": None, 
                    "autonumero": st.column_config.TextColumn("🔢 Nº RMA", width="small"),
                    "comentario": st.column_config.TextColumn("💬 Comentario", width="medium"),
                    "diagnostico": st.column_config.TextColumn("🔧 Diagnóstico", width="medium"),
                    "Finalizado": st.column_config.CheckboxColumn("Finalizar"), 
                    "Estado del RMA": st.column_config.SelectboxColumn(options=["CAMBIO", "CREDITO", "GARANTIA OFICIAL", "GARANTIA", "FUERA DE GARANTIA", "NO FALLO - DEVOLVER A CLIENTE", "REPARADO"])
                }, 
                disabled=deshabilitados_t2, 
                hide_index=True, 
                use_container_width=True
            )
            
            if st.form_submit_button("ACTUALIZAR PROCESOS"):
                for _, r in ed2.iterrows():
                    orig = df2[df2['id_interno'] == r['id_interno']].iloc[0]
                    campos_a_revisar = ['comentario', 'diagnostico', 'Estado del RMA', 'Finalizado'] if st.session_state.rol == "admin" else ['comentario']
                    up = {k: r[k] for k in campos_a_revisar if k in r and str(r[k]) != str(orig.get(k, ""))}
                    
                    if st.session_state.rol == "admin" and 'Finalizado' in up and up['Finalizado'] == True:
                        if not orig.get('Finalizado', False):
                            up['Resolucion'] = date.today().strftime('%Y-%m-%d')
                    
                    if st.session_state.rol == "admin" and 'Ingreso' in r:
                        val, stt = formatear_y_validar_fecha(r['Ingreso'])
                        if stt == "OK": up['Ingreso'] = val
                    
                    if up: table.update(r['id_interno'], up)
                cargar_todos_los_datos.clear()
                st.rerun()

# --- TABLA 3: HISTÓRICO ---
df3 = df_all[(df_all['Aceptado'] == True) & (df_all['Finalizado'] == True)].copy().reset_index(drop=True)
with st.expander("✅ 3. CASOS RESUELTOS (Histórico)"):
    if not df3.empty:
        df3['Resolucion'] = df3['Resolucion'].apply(formatear_para_leer)
        
        with st.form("f3"):
            c3_cols = ['autonumero', 'comentario', 'Cliente', 'Producto', 'diagnostico', 'Estado del RMA', 'Resolucion']
            st_df3 = df3[['id_interno'] + c3_cols]
            deshabilitados_t3 = ['autonumero', 'Cliente', 'Producto', 'diagnostico', 'Estado del RMA', 'Resolucion']
            
            ed3 = st.data_editor(
                st_df3.style.apply(estilo_filas, axis=1),
                column_config={
                    "id_interno": None,
                    "autonumero": st.column_config.TextColumn("🔢 Nº RMA", width="small"),
                    "comentario": st.column_config.TextColumn("💬 Comentario", width="medium"),
                    "diagnostico": st.column_config.TextColumn("🔧 Diagnóstico", width="medium")
                },
                disabled=deshabilitados_t3,
                hide_index=True,
                use_container_width=True
            )
            
            if st.form_submit_button("ACTUALIZAR COMENTARIOS HISTÓRICO"):
                for _, r in ed3.iterrows():
                    orig = df3[df3['id_interno'] == r['id_interno']].iloc[0]
                    up = {k: r[k] for k in ['comentario'] if str(r[k]) != str(orig.get(k, ""))}
                    if up: table.update(r['id_interno'], up)
                cargar_todos_los_datos.clear()
                st.rerun()
