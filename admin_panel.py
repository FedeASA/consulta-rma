import streamlit as st
import pandas as pd
from datetime import datetime, date
import io
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sheets_operations import (
    get_dataframe,
    get_all_records,
    update_record,
    batch_update_records,
    find_row_by_values,
    descargar_foto_de_drive,
    eliminar_foto,
    es_url_foto,
    miniatura_cloudinary
)
from utils import es_verdadero, booleano_a_sheets
from sso import generar_token
from streamlit_cookies_controller import CookieController
import hashlib

cookies = CookieController()

def generar_hash_sesion(usuario):
    secreto = st.secrets.get("COOKIE_SECRET", "cambiar_este_secreto")
    hoy = date.today().isoformat()
    return hashlib.sha256(f"{usuario}-{hoy}-{secreto}".encode()).hexdigest()

def normalizar_telefono(telefono_raw):
    """Limpia el teléfono: quita espacios, guiones y prefijos de país,
    dejando 10 dígitos consecutivos."""
    if not telefono_raw or str(telefono_raw).strip() in ["None", "none", "nan", "NaN", ""]:
        return ""

    digitos = "".join(c for c in str(telefono_raw) if c.isdigit())

    for prefijo in ["00549", "0054", "549", "54"]:
        if digitos.startswith(prefijo):
            digitos = digitos[len(prefijo):]
            break

    return digitos

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

        /* ── Tabla 2: reduce espacio entre tarjetas ── */
        div[data-testid="stExpander"] div[data-testid="stVerticalBlock"] > div {
            margin-bottom: 2px !important;
        }
    </style>
    """, unsafe_allow_html=True)

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
    st.session_state.usuario = ""
    st.session_state.rol = ""
    st.session_state.cookie_check_done = False
    st.session_state.cookie_retry = 0

# --- Intentar restaurar sesión desde cookie (con reintento por carga del componente) ---
if not st.session_state.autenticado and not st.session_state.cookie_check_done:
    try:
        cookie_usuario = cookies.get("rma_usuario")
        cookie_token = cookies.get("rma_token")
    except Exception:
        cookie_usuario = None
        cookie_token = None

    if cookie_usuario is None and cookie_token is None and st.session_state.cookie_retry < 4:
        # El componente de cookies todavía no terminó de cargar en este render; reintentamos.
        st.session_state.cookie_retry += 1
        time.sleep(0.3)
        st.rerun()

    st.session_state.cookie_check_done = True

    if cookie_usuario and cookie_token:
        if cookie_token == generar_hash_sesion(cookie_usuario):
            try:
                usuarios_secretos = st.secrets["USUARIOS"]
                if cookie_usuario in usuarios_secretos:
                    st.session_state.autenticado = True
                    st.session_state.usuario = cookie_usuario
                    st.session_state.rol = "admin" if cookie_usuario == "admin" else "user"
            except Exception:
                pass

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
                    try:
                        cookies.set("rma_usuario", usuario, max_age=60 * 60 * 24)
                        cookies.set("rma_token", generar_hash_sesion(usuario), max_age=60 * 60 * 24)
                    except Exception:
                        pass  # El componente aún no está listo; la sesión igual queda en session_state
                    st.success("¡Acceso concedido!")
                    st.rerun()
                else:
                    st.error("Usuario o contraseña incorrectos.")
            except Exception as e:
                st.error(f"Error de configuración: {e}")

if not st.session_state.autenticado:
    login()
    st.stop()

# --- BARRA LATERAL ---
st.sidebar.write(f"Conectado como: **{st.session_state.usuario}** ({st.session_state.rol.upper()})")

if st.sidebar.button("Cerrar Sesión", type="secondary", use_container_width=True):
    try:
        cookies.remove("rma_usuario")
        cookies.remove("rma_token")
    except Exception:
        pass
    st.session_state.autenticado = False
    st.session_state.usuario = ""
    st.session_state.rol = ""
    st.rerun()

# --- ENVIADOR DE CORREOS CONFIGURABLE ---
def despachar_correo(config_section, destinatario, asunto, cuerpo, html=False):
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
        # ✅ Soporta HTML o texto plano según el parámetro html=
        if html:
            msg.attach(MIMEText(cuerpo, 'html', 'utf-8'))
        else:
            msg.attach(MIMEText(cuerpo, 'plain', 'utf-8'))
        
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
    elif estado in ["FUERA DE GARANTIA", "RECHAZADO"]: style = rojo
    elif estado == "REPARADO": style = gris
    elif estado == "NUNCA ENVIO": style = 'background-color: #6f42c1; color: white;'
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
    for formato in ['%d/%m/%y', '%d/%m/%Y']:
        try:
            dt_objeto = datetime.strptime(texto, formato)
            if dt_objeto.date() > date.today(): return None, "FUTURA"
            return dt_objeto.strftime('%Y-%m-%d'), "OK"
        except ValueError: continue
    return None, "FORMATO_INVALIDO"

# =====================================================================
# DATOS: se cargan de la planilla y se guardan en la sesión.
# Después de cada cambio NO se vuelve a leer toda la planilla: el cambio se aplica
# también en memoria. Se recarga completo cada TTL_DATOS segundos o con "Actualizar Datos".
# =====================================================================
TTL_DATOS = 120
COLS_BOOL = ['Aceptado', 'Finalizado', 'Recibido', 'Anulado']
COLS_TEXTO = ['comentario', 'Falla', 'diagnostico', 'Ingreso', 'Resolucion', 'Compra', 'Cliente', 'Producto', 'Serial', 'autonumero', 'Telefono', 'Email', 'Motivo del trámite', 'PROVEEDOR', 'Foto1', 'Foto2']

def _procesar_df(df):
    """Normaliza encabezados, tipos y textos. Devuelve (df, columnas_faltantes_en_planilla)."""
    columnas_requeridas = ['Aceptado', 'Finalizado', 'Recibido', 'Anulado', 'Ingreso', 'Resolucion', 'diagnostico', 'Estado del RMA', 'Compra', 'Producto', 'comentario', 'Falla', 'Serial', 'autonumero', 'Telefono', 'Email', 'Motivo del trámite', 'PROVEEDOR', 'Foto1', 'Foto2']
    COLS_BOOL = ['Aceptado', 'Finalizado', 'Recibido', 'Anulado']

    # Si en la planilla el encabezado está escrito distinto ("Proveedor", "PROVEEDOR ",
    # "recibido"...), se renombra al nombre que usa el código. Antes se creaba una columna
    # vacía aparte y los cambios de ese campo nunca se veían.
    import unicodedata as _ud
    def _norm_col(n):
        n = _ud.normalize("NFKD", str(n)).encode("ascii", "ignore").decode()
        return " ".join(n.split()).upper()
    _mapa_cols = {_norm_col(c): c for c in df.columns}
    _renombres = {}
    for col in columnas_requeridas + ['Cliente']:
        real = _mapa_cols.get(_norm_col(col))
        if col not in df.columns and real is not None:
            _renombres[real] = col
    if _renombres:
        df = df.rename(columns=_renombres)

    # Columnas que el panel necesita y NO existen en la planilla: se avisa al admin
    COLS_FALTANTES_SHEET = [c for c in ['PROVEEDOR', 'Recibido', 'Anulado', 'Foto1', 'Foto2'] if c not in df.columns]

    for col in columnas_requeridas:
        if col not in df.columns: 
            df[col] = False if col in COLS_BOOL else ""
        else:
            if col in COLS_BOOL:
                df[col] = df[col].apply(lambda x: es_verdadero(x))

    for col_txt in ['comentario', 'Falla', 'diagnostico', 'Ingreso', 'Resolucion', 'Compra', 'Cliente', 'Producto', 'Serial', 'autonumero', 'Telefono', 'Email', 'Motivo del trámite', 'PROVEEDOR', 'Foto1', 'Foto2']:
        if col_txt in df.columns:
            df[col_txt] = df[col_txt].fillna("").apply(lambda x: str(int(x)) if isinstance(x, float) and x.is_integer() else str(x))
            df[col_txt] = df[col_txt].apply(lambda x: "" if str(x).strip() in ["None", "none", "nan", "NaN", ""] else str(x).strip())
    return df, COLS_FALTANTES_SHEET

def _cargar_desde_planilla():
    try:
        df = get_dataframe()
    except Exception as e:
        st.error(f"❌ Error al conectar con Google Sheets: {e}")
        st.stop()
    if df.empty:
        return False
    df['row_number'] = range(2, len(df) + 2)  # Las filas de datos comienzan en 2
    df, faltantes = _procesar_df(df)
    st.session_state['df_base'] = df
    st.session_state['df_base_ts'] = time.time()
    st.session_state['cols_faltantes'] = faltantes
    return True

def forzar_recarga():
    st.session_state.pop('df_base_ts', None)

def _datos_vigentes():
    ss = st.session_state
    if 'df_base' not in ss or time.time() - ss.get('df_base_ts', 0) > TTL_DATOS:
        return _cargar_desde_planilla()
    return True

def df_completo():
    """Todos los tickets (incluidos anulados) — se usa para el próximo Nº de RMA."""
    return st.session_state['df_base']

def df_visible():
    """Tickets que se muestran en el panel (sin anulados)."""
    df = st.session_state['df_base']
    return df[df['Anulado'] != True].copy()

def _aplicar_en_memoria(records):
    """Refleja en la copia en memoria lo que se acaba de guardar en la planilla."""
    df = st.session_state.get('df_base')
    if df is None:
        return
    for rec in records:
        mask = df['row_number'] == int(rec["row"])
        if not mask.any():
            continue
        for campo, valor in rec["data"].items():
            if campo not in df.columns:
                continue
            if campo in COLS_BOOL:
                df.loc[mask, campo] = es_verdadero(valor)
            else:
                df.loc[mask, campo] = "" if valor is None else str(valor).strip()

# --- IDENTIDAD DE CADA TICKET ---
# Al guardar se verifica que la fila siga siendo el mismo ticket (por Nº de RMA, o por
# Cliente+Producto+Serial si todavía no tiene número). Si alguien movió filas, se busca.
def _firma_ticket(r):
    rma = str(r.get('autonumero', '')).strip()
    if rma:
        return {"autonumero": rma}
    return {"Cliente": r.get('Cliente', ''), "Producto": r.get('Producto', ''), "Serial": r.get('Serial', '')}

def guardar_registros(records):
    """Guarda en la planilla (verificando identidad) y actualiza la copia en memoria.
    Si algo falla, fuerza una recarga completa en la próxima ejecución."""
    df = st.session_state.get('df_base')
    for rec in records:
        if "match" not in rec and df is not None:
            fila = df[df['row_number'] == int(rec["row"])]
            if not fila.empty:
                rec["match"] = _firma_ticket(fila.iloc[0])
    ok = batch_update_records(records)
    if ok:
        _aplicar_en_memoria(records)
    else:
        forzar_recarga()
    return ok

from streamlit.errors import StreamlitAPIException

def rerun_fragmento():
    """Re-ejecuta solo el fragmento actual; si no se está dentro de uno, todo el panel."""
    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        st.rerun()

if not _datos_vigentes():
    st.error("⚠️ No se pudieron cargar datos desde Google Sheets. Verificá las credenciales.")
    if st.button("🔄 Reintentar"):
        forzar_recarga()
        st.rerun()
    st.stop()

if st.session_state.get('cols_faltantes') and st.session_state.get("rol") == "admin":
    st.warning(
        "⚠️ Faltan estas columnas en la fila 1 de la planilla: **"
        + ", ".join(st.session_state['cols_faltantes'])
        + "**. Hasta que las agregues, lo que se cargue en esos campos no se va a guardar."
    )

df_all = df_visible()

# --- LIMPIEZA AUTOMÁTICA DE FOTOS VENCIDAS ---
# Borra de Drive (y limpia en la planilla) las fotos de casos finalizados
# hace más de DIAS_RETENCION_FOTOS días, para no acumular espacio en Drive.
DIAS_RETENCION_FOTOS = 30

def limpiar_fotos_vencidas(dias_retencion=DIAS_RETENCION_FOTOS):
    hoy = date.today()
    candidatos = df_all[
        (df_all['Finalizado'] == True) &
        ((df_all['Foto1'].astype(str).str.strip() != "") | (df_all['Foto2'].astype(str).str.strip() != ""))
    ]
    if candidatos.empty:
        return False

    actualizaciones = []
    for _, r in candidatos.iterrows():
        fecha_res_str = str(r.get('Resolucion', '')).strip()
        fecha_res = None
        for formato in ['%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y']:
            try:
                fecha_res = datetime.strptime(fecha_res_str, formato).date()
                break
            except ValueError:
                continue

        if not fecha_res or (hoy - fecha_res).days < dias_retencion:
            continue

        cambios = {}
        for campo_foto in ['Foto1', 'Foto2']:
            fid = str(r.get(campo_foto, '')).strip()
            if fid:
                eliminar_foto(fid)  # Cloudinary (URL) o Drive (ID viejo)
                cambios[campo_foto] = ""
        if cambios:
            actualizaciones.append({"row": r['row_number'], "data": cambios})

    if actualizaciones:
        guardar_registros(actualizaciones)
        return True

    return False

# Se ejecuta como máximo una vez por día por sesión (no hace falta más seguido:
# como Streamlit Cloud no tiene un scheduler propio, esta limpieza "perezosa"
# corre cada vez que alguien abre el panel).
if st.session_state.get("_ultima_limpieza_fotos") != date.today().isoformat():
    st.session_state["_ultima_limpieza_fotos"] = date.today().isoformat()
    if limpiar_fotos_vencidas():
        st.rerun()

# # --- LINKS DE ADMINISTRADOR ---
if st.session_state.rol == "admin" or st.session_state.usuario == "edu":
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: st.link_button("📋 Planilla Base", "https://docs.google.com/spreadsheets/d/1wBkIvtk_KDcPB3Jt1vBcWdVfpRPvzAevX1ooBQ550sI/edit?gid=1082756943#gid=1082756943", use_container_width=True)
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
    with c6:
        _sso_token = generar_token(st.session_state.usuario, st.session_state.rol)
        _url_proveedores = f"https://panelproveedores.streamlit.app/?sso={_sso_token}"
        st.link_button("🔁 Proveedores - RMA", _url_proveedores, use_container_width=True)

# --- BOTONES DE ACCIÓN SUPERIORES ---
col_rep1, col_btn_refresh, col_rep2 = st.columns([1, 1, 3])
with col_rep1:
    opcion_reporte = st.selectbox(
        "Opciones de Reporte", 
        ["Ocultar Reportes", "📊 Reporte Cliente", "🚚 Reporte Viaje"],
        label_visibility="collapsed"
    )
with col_btn_refresh:
    if st.button("🔄 Actualizar Datos", use_container_width=True):
        forzar_recarga()
        st.rerun()

if opcion_reporte == "📊 Reporte Cliente":
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
                    formato_encabezado = workbook.add_format({
                        'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#000000',
                        'border': 1, 'border_color': '#000000', 'align': 'center', 'valign': 'vcenter',
                        'font_name': 'Segoe UI', 'font_size': 11
                    })
                    formato_celda = workbook.add_format({
                        'border': 1, 'border_color': '#000000', 'valign': 'vcenter',
                        'font_name': 'Segoe UI', 'font_size': 10
                    })
                    
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
                
                st.download_button(
                    label=f"📥 Descargar Reporte {cliente_buscado}", 
                    data=output.getvalue(), 
                    file_name=f"Reporte_{cliente_buscado}_{datetime.now().strftime('%d_%m_%Y')}.xlsx", 
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            else:
                st.warning("No hay datos para ese cliente.")

elif opcion_reporte == "🚚 Reporte Viaje":
    with st.container(border=True):
        st.write("### 🚚 Reporte de Viaje Consolidado")
        df_en_proceso = df_all[(df_all['Aceptado'] == True) & (df_all['Finalizado'] == False)].copy()
        if not df_en_proceso.empty:
            clientes_disp = sorted(df_en_proceso['Cliente'].dropna().unique().astype(str).tolist())
            clientes_seleccionados = st.multiselect("Seleccione clientes para incluir en el viaje:", clientes_disp)
            
            if clientes_seleccionados:
                df_viaje = df_en_proceso[df_en_proceso['Cliente'].isin(clientes_seleccionados)].copy()
                cols_viaje = ['Cliente', 'autonumero', 'Producto', 'Falla']
                
                for c in cols_viaje:
                    if c not in df_viaje.columns: df_viaje[c] = ""
                
                df_viaje = df_viaje[cols_viaje].sort_values(by='Cliente')
                
                output_viaje = io.BytesIO()
                with pd.ExcelWriter(output_viaje, engine='xlsxwriter') as writer:
                    df_viaje.to_excel(writer, index=False, sheet_name='Viaje', startrow=2)
                    workbook = writer.book
                    worksheet = writer.sheets['Viaje']
                    
                    formato_titulo = workbook.add_format({'bold': True, 'font_size': 14, 'font_name': 'Segoe UI'})
                    formato_encabezado = workbook.add_format({
                        'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#000000',
                        'border': 1, 'border_color': '#000000', 'align': 'center', 'valign': 'vcenter',
                        'font_name': 'Segoe UI', 'font_size': 11
                    })
                    
                    worksheet.write(0, 0, f"REPORTE DE VIAJE - {datetime.now().strftime('%d/%m/%Y')}", formato_titulo)
                    
                    for col_num, header_title in enumerate(df_viaje.columns):
                        nombre_col = "Nº RMA" if header_title == "autonumero" else header_title
                        worksheet.write(1, col_num, nombre_col, formato_encabezado)
                    
                    colores_paleta = ['#E6F2FF', '#FFF0E6', '#E6FFE6', '#FFE6E6', '#F2E6FF', '#FFFFE6', '#E6E6E6']
                    dict_colores = {}
                    idx_color = 0
                    
                    for row_idx in range(len(df_viaje)):
                        cliente_actual = str(df_viaje.iloc[row_idx, 0])
                        if cliente_actual not in dict_colores:
                            dict_colores[cliente_actual] = colores_paleta[idx_color % len(colores_paleta)]
                            idx_color += 1
                            
                        formato_fila = workbook.add_format({
                            'border': 1, 'border_color': '#000000', 'valign': 'vcenter',
                            'font_name': 'Segoe UI', 'font_size': 10,
                            'bg_color': dict_colores[cliente_actual]
                        })
                        
                        for col_idx in range(len(df_viaje.columns)):
                            val_raw = df_viaje.iloc[row_idx, col_idx]
                            val_celda = "" if pd.isna(val_raw) or str(val_raw).strip() in ["NaT", "None", "nan", "NaN"] else str(val_raw)
                            worksheet.write(row_idx + 2, col_idx, val_celda, formato_fila)
                    
                    for i, col in enumerate(df_viaje.columns):
                        max_len = max([len(str(v)) for v in df_viaje[col].fillna("")] + [len(col)])
                        worksheet.set_column(i, i, max_len + 4)
                    
                    worksheet.set_row(1, 24)
                    
                    row_total = len(df_viaje) + 2
                    formato_total = workbook.add_format({
                        'bold': True, 'border': 1, 'border_color': '#000000', 'align': 'center', 'valign': 'vcenter',
                        'bg_color': '#D9D9D9', 'font_name': 'Segoe UI', 'font_size': 11
                    })
                    worksheet.merge_range(row_total, 0, row_total, len(df_viaje.columns) - 1, f"TOTAL DE ÍTEMS EN VIAJE: {len(df_viaje)}", formato_total)

                st.download_button(
                    label="📥 Descargar Reporte de Viaje", 
                    data=output_viaje.getvalue(), 
                    file_name=f"Reporte_Viaje_{datetime.now().strftime('%d_%m_%Y')}.xlsx", 
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        else:
            st.info("No hay tickets en proceso en este momento.")

st.divider()

# --- TABLA 1: POR ACEPTAR ---
# (fragmento: un cambio acá re-ejecuta solo esta tabla, no todo el panel)
@st.fragment
def tabla_1():
    df_all = df_visible()
    df1 = df_all[
        (df_all['Aceptado'] == False) & 
        (df_all['Producto'].str.strip() != "") & 
        (df_all['Cliente'].str.strip() != "")
    ].copy()

    with st.expander("📥 1. TICKETS POR ACEPTAR (Entrada)", expanded=True):
        if st.session_state.get('t1_msg_error'):
            st.error(st.session_state.pop('t1_msg_error'))
        if st.session_state.get('t1_msg_ok'):
            st.success(st.session_state.pop('t1_msg_ok'))
        if not df1.empty:
            if 'Compra' in df1.columns:
                df1 = df1.sort_values(by='Compra', ascending=False)
            
            df1['Compra'] = df1['Compra'].apply(formatear_para_leer)
            df1.insert(0, 'Eliminar', False)
            # Miniatura de la primera foto (solo fotos de Cloudinary; las viejas de Drive no tienen URL pública)
            df1['Foto'] = df1.apply(
                lambda r: next((miniatura_cloudinary(v, 120, 120) for v in [r.get('Foto1', ''), r.get('Foto2', '')] if es_url_foto(v)), ""),
                axis=1
            )
        
            with st.form("f1"):
                if st.session_state.rol == "admin":
                    # MODIFICADO: Se agrega PROVEEDOR y se deja la lista deshabilitada VACÍA (Todo es editable)
                    c1_cols = ['Eliminar', 'Foto', 'Cliente', 'Producto', 'Serial', 'Falla', 'Compra', 'PROVEEDOR', 'Aceptado']
                    esta_deshabilitado_t1 = ['Foto']
                else:
                    c1_cols = ['Eliminar', 'Foto', 'Cliente', 'Producto', 'Serial', 'Falla', 'PROVEEDOR']
                    esta_deshabilitado_t1 = ['Foto', 'Cliente', 'Producto', 'Serial', 'Falla', 'PROVEEDOR']
            
                ed1 = st.data_editor(
                    df1[['row_number'] + c1_cols].reset_index(drop=True), 
                    column_config={
                        "row_number": None,
                        "Eliminar": st.column_config.CheckboxColumn("🚫", width="small", help="Seleccione para anular este ticket"),
                        "PROVEEDOR": st.column_config.TextColumn("PROVEEDOR"),
                        "Foto": st.column_config.ImageColumn("📷", width="small", help="Foto adjunta por el cliente (pasá el mouse para agrandar)"),
                        "Aceptado": st.column_config.CheckboxColumn("Aceptado"),
                    }, 
                    disabled=esta_deshabilitado_t1, 
                    hide_index=True, 
                    use_container_width=True
                )
            
                st.write("---")
                col_btn_guardar, col_chk_elim, col_btn_elim = st.columns([2, 3, 2])
            
                with col_btn_guardar:
                    submit_guardar = st.form_submit_button("GUARDAR ENTRADAS", disabled=(st.session_state.rol != "admin"), use_container_width=True)
                with col_chk_elim:
                    confirmar_borrado = st.checkbox("Confirmo que deseo ANULAR los tickets seleccionados.")
                with col_btn_elim:
                    submit_eliminar = st.form_submit_button("🚫 ANULAR TICKETS", use_container_width=True)
            
                if submit_guardar and st.session_state.rol == "admin":
                    records_to_update = []
                    _numeros_existentes = pd.to_numeric(df_completo()['autonumero'], errors='coerce').dropna()
                    _proximo_rma = int(_numeros_existentes.max() + 1) if not _numeros_existentes.empty else 1

                    for _, r in ed1.iterrows():
                        orig = df1[df1['row_number'] == r['row_number']].iloc[0]
                    
                        aceptado_nuevo = es_verdadero(r.get('Aceptado', False))
                        aceptado_original = es_verdadero(orig.get('Aceptado', False))
                        esta_aceptando = aceptado_nuevo and not aceptado_original
                    
                        # MODIFICADO: Incluye todos los campos editables de la Tabla 1 para guardarse en Google Sheets
                        campos_a_revisar = ['Aceptado', 'Cliente', 'Producto', 'Serial', 'Falla', 'PROVEEDOR']
                        up = {}
                        for k in campos_a_revisar:
                            if k not in r:
                                continue
                            if k in ['Aceptado', 'Finalizado']:
                                if es_verdadero(r[k]) != es_verdadero(orig.get(k, False)):
                                    up[k] = booleano_a_sheets(es_verdadero(r[k]))
                            else:
                                # Una celda borrada en el editor llega como None/NaN: se guarda vacía
                                # (antes se comparaba/guardaba el texto "None").
                                v_nuevo = "" if pd.isna(r[k]) else str(r[k]).strip()
                                v_orig = str(orig.get(k, "") or "").strip()
                                if v_nuevo != v_orig:
                                    up[k] = v_nuevo
                    
                        if 'Compra' in r:
                            f, e = formatear_y_validar_fecha(r['Compra'])
                            if e == "OK" and f and f != orig.get('Compra', ''): 
                                up['Compra'] = f
                    
                        if esta_aceptando:
                            # OPTIMIZACIÓN: Lee el valor corregido (r) si existe, o el original (orig) de respaldo
                            cliente_nom = r.get('Cliente', orig.get('Cliente', ''))
                            prod_nom = r.get('Producto', orig.get('Producto', ''))
                            serial_num = r.get('Serial', orig.get('Serial', ''))
                            falla_desc = r.get('Falla', orig.get('Falla', ''))
                            fecha_compra_str = formatear_para_leer(up.get('Compra', orig.get('Compra', '')))
                            motivo_tramite = orig.get('Motivo del trámite', 'RMA')
                            if not motivo_tramite: motivo_tramite = "RMA"
                        
                            rma_id = str(orig.get('autonumero', '')).strip()
                            if rma_id in ["", "nan", "None"]:
                                rma_id = str(_proximo_rma)
                                _proximo_rma += 1
                            # Se escribe siempre como valor fijo: si la celda tenía una fórmula
                            # (ej. =FILA()-1), al borrar filas el número se corría.
                            up['autonumero'] = rma_id

                            cliente_id = cliente_nom
                            estado_rma = "PENDIENTE"
                            telefono_val = normalizar_telefono(orig.get('Telefono', ''))
                            email_val = orig.get('Email', '').strip().lower()     
                            if telefono_val and telefono_val != str(orig.get('Telefono', '')).strip():
                                up['Telefono'] = telefono_val
                        
                            if telefono_val != "":
                                import urllib.parse
                                mensaje_wa = (
                                    f"Su solicitud para {motivo_tramite} del producto {prod_nom} ha sido aceptada.\n\n"
                                    f"Se le asign\u00f3 el n\u00famero de caso: #{rma_id}\n"
                                    f"Su c\u00f3digo de cliente es: {cliente_id}\n\n"
                                    f"Detalle del caso:\n"
                                    f"Producto: {prod_nom}\n"
                                    f"Serial: {serial_num}\n"
                                    f"Falla: {falla_desc}\n"
                                    f"Fecha Compra: {fecha_compra_str}\n\n"
                                    f"Le recomendamos anotar su c\u00f3digo de usuario para consultar el estado en:\n"
                                    f"https://rma-altavista.streamlit.app/\n\n"
                                    f"Cuando tengamos novedades le notificaremos por este canal.\n\n"
                                    f"Servicio T\u00e9cnico: 3433002458\n"
                                    f"Ventas: 3434469399\n"
                                    f"Email: federico@altavistasa.com.ar"
                                )
                                link_wa = f"https://wa.me/{telefono_val}?text={urllib.parse.quote(mensaje_wa)}"
                                asunto_ws = "Caso aceptado - Mensaje para el cliente"
                                cuerpo_html_acc = (
                                    '<html><body>'
                                    '<p><b>RMA ACEPTADO &#8212; MENSAJE PARA CLIENTE</b></p>'
                                    '<table style="border-collapse:collapse;margin-bottom:16px;">'
                                    f'  <tr><td style="padding:4px 12px 4px 0;color:#888;">Tel&eacute;fono</td><td><b>{telefono_val}</b></td></tr>'
                                    f'  <tr><td style="padding:4px 12px 4px 0;color:#888;">Caso</td><td><b>#{rma_id}</b></td></tr>'
                                    f'  <tr><td style="padding:4px 12px 4px 0;color:#888;">Cliente</td><td>{cliente_nom}</td></tr>'
                                    f'  <tr><td style="padding:4px 12px 4px 0;color:#888;">Producto</td><td>{prod_nom}</td></tr>'
                                    f'  <tr><td style="padding:4px 12px 4px 0;color:#888;">Serial</td><td>{serial_num}</td></tr>'
                                    f'  <tr><td style="padding:4px 12px 4px 0;color:#888;">Falla</td><td>{falla_desc}</td></tr>'
                                    f'  <tr><td style="padding:4px 12px 4px 0;color:#888;">Fecha Compra</td><td>{fecha_compra_str}</td></tr>'
                                    '</table>'
                                    f'<a href="{link_wa}" style="display:inline-block;background-color:#25D366;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:bold;font-size:15px;">'
                                    '  &#128242; Abrir WhatsApp y enviar mensaje'
                                    '</a>'
                                    '<p style="margin-top:16px;color:#888;font-size:12px;">'
                                    '  Si el bot&oacute;n no funciona, copi&aacute; este enlace:<br>'
                                    f'  <a href="{link_wa}">{link_wa}</a>'
                                    '</p>'
                                    '</body></html>'
                                )
                                despachar_correo("EMAIL_INTERNO", "federico@altavistasa.com.ar", asunto_ws, cuerpo_html_acc, html=True)
                            
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
                            records_to_update.append({"row": r['row_number'], "data": up})
                        
                    # ✅ CORREGIDO: un solo request en lugar de N loops
                    if records_to_update:
                        if not guardar_registros(records_to_update):
                            st.session_state['t1_msg_error'] = "❌ No se pudieron guardar los cambios de la Tabla 1 en Google Sheets."
                        
                    st.rerun()  # completo: los tickets aceptados pasan a la Tabla 2

                if submit_eliminar:
                    registros_a_anular = ed1[ed1['Eliminar'] == True]['row_number'].tolist()
                    if not registros_a_anular:
                        st.warning("No seleccionaste ningún ticket para anular.")
                    elif not confirmar_borrado:
                        st.error("Debes tildar la casilla de confirmación central para habilitar la anulación.")
                    else:
                        # Ya no se borran filas: se marca Anulado = Sí y el ticket se oculta del panel.
                        # Así la numeración no se corre y el ticket se puede recuperar desde la planilla.
                        ok = guardar_registros([
                            {"row": int(rn_a), "data": {"Anulado": booleano_a_sheets(True)}}
                            for rn_a in registros_a_anular
                        ])
                        if ok:
                            st.session_state['t1_msg_ok'] = f"🚫 Se anularon {len(registros_a_anular)} ticket(s)."
                        else:
                            st.session_state['t1_msg_error'] = "❌ No se pudieron anular todos los tickets seleccionados."
                        rerun_fragmento()
        else:
            st.info("No hay pendientes.")

tabla_1()

# --- TABLA 2: EN PROCESO ---
# (fragmento: un cambio acá re-ejecuta solo esta tabla, no todo el panel)
@st.fragment
def tabla_2():
    df_all = df_visible()
    df2 = df_all[(df_all['Aceptado'] == True) & (df_all['Finalizado'] == False)].copy().reset_index(drop=True)
    with st.expander("⚙️ 2. TICKETS EN PROCESO (Aceptados)", expanded=True):
        if not df2.empty:
            for c in ['Compra','Ingreso','Resolucion']:
                df2[c] = df2[c].apply(formatear_para_leer)

            # --- Selector de orden ---
            ORDEN_OPCIONES = {
                "🔢 Nº RMA":           "autonumero",
                "👤 Cliente":           "Cliente",
                "📦 Producto":          "Producto",
                "📅 Fecha de ingreso":  "Ingreso",
            }
            col_ord, col_cnt, _ = st.columns([2, 2, 4])
            orden_label = col_ord.selectbox(
                "Ordenar por", list(ORDEN_OPCIONES.keys()),
                key="t2_orden", label_visibility="collapsed"
            )
            orden_col = ORDEN_OPCIONES[orden_label]
            df2_sorted = df2.sort_values(by=orden_col, ascending=True).reset_index(drop=True)
            df2_sin_recibir = df2_sorted[df2_sorted['Recibido'] != True].reset_index(drop=True)
            df2_recibidos   = df2_sorted[df2_sorted['Recibido'] == True].reset_index(drop=True)
            col_cnt.caption(
                f"**{len(df2_sorted)}** tickets en proceso · "
                f"**{len(df2_sin_recibir)}** sin recibir · **{len(df2_recibidos)}** recibidos"
            )

            if st.session_state.get('t2_msg_error'):
                st.error(st.session_state.pop('t2_msg_error'))

            st.markdown("""
            <style>
            /* Tarjeta header */
            .rma-card-header {
                display: flex; gap: 18px; align-items: center;
                font-size: 13px; flex-wrap: wrap;
            }
            .rma-badge {
                padding: 2px 10px; border-radius: 4px;
                font-size: 11px; font-weight: 700; letter-spacing:.04em;
            }
            .badge-verde    { background:#28a745; color:#fff; }
            .badge-naranja  { background:#fd7e14; color:#000; }
            .badge-celeste  { background:#17a2b8; color:#fff; }
            .badge-rojo     { background:#dc3545; color:#fff; }
            .badge-gris     { background:#6c757d; color:#fff; }
            .badge-violeta  { background:#6f42c1; color:#fff; }
            .badge-pendiente{ background:#444; color:#ccc; }
            .rma-sep { color:#555; }

            /* Tarjetas de la Tabla 2: azul / celeste alternado */
            .st-key-t2card_a_marker, [class*="st-key-t2card_a_"] details,
            [class*="st-key-t2card_a_"] summary {
                background-color: #0d2b45 !important; border-radius: 6px;
            }
            .st-key-t2card_b_marker, [class*="st-key-t2card_b_"] details,
            [class*="st-key-t2card_b_"] summary {
                background-color: #3a4f63 !important; border-radius: 6px;
            }
            </style>
            """, unsafe_allow_html=True)

            def badge_estado(estado):
                e = str(estado).upper()
                cls = {
                    "CAMBIO": "badge-verde", "CREDITO": "badge-verde",
                    "GARANTIA": "badge-naranja", "GARANTIA OFICIAL": "badge-naranja",
                    "NO FALLO - DEVOLVER A CLIENTE": "badge-celeste",
                    "FUERA DE GARANTIA": "badge-rojo",
                    "REPARADO": "badge-gris",
                    "RECHAZADO": "badge-rojo",
                    "NUNCA ENVIO": "badge-violeta",
                }.get(e, "badge-pendiente")
                label = e if e else "SIN ESTADO"
                return f'<span class="rma-badge {cls}">{label}</span>'

            @st.dialog("📷 Foto adjunta", width="large")
            def _ver_foto_grande(origen):
                # Ventana grande con la foto en su resolución original
                st.image(origen, use_container_width=True)
                if isinstance(origen, str) and es_url_foto(origen):
                    st.link_button("Abrir original en otra pestaña ↗", origen)

            def _toggle_recibido(rn, key):
                """Guarda el tilde de 'Recibido' apenas se hace clic."""
                nuevo_valor = bool(st.session_state.get(key, False))
                ok = guardar_registros([{"row": rn, "data": {"Recibido": booleano_a_sheets(nuevo_valor)}}])
                if not ok:
                    st.session_state['t2_msg_error'] = "❌ No se pudo guardar 'Recibido' en Google Sheets. Probá de nuevo."

            def _render_tarjeta_t2(row, posicion):
                rn = row['row_number']
                # Color alternado azul / celeste por CSS (clase st-key-t2card_a_/b_): no depende de JS,
                # así no se pierde cuando la tarjeta cambia de columna al tildar "Recibido".
                tono = "a" if posicion % 2 == 0 else "b"

                # Header de la tarjeta
                header_html = (
                    f'<div class="rma-card-header">'
                    f'<b>#{row["autonumero"]}</b>'
                    f'<span class="rma-sep">|</span>'
                    f'<span>👤 {row["Cliente"]}</span>'
                    f'<span class="rma-sep">|</span>'
                    f'<span>📦 {row["Producto"]}</span>'
                    f'<span class="rma-sep">|</span>'
                    f'{badge_estado(row["Estado del RMA"])}'
                    f'<span class="rma-sep" style="margin-left:auto;font-size:11px;color:#666;">'
                    f'📅 {row["Ingreso"]}</span>'
                    f'</div>'
                )

                key_rec = f"rec_{rn}"
                st.session_state[key_rec] = bool(row['Recibido'])  # la planilla manda

                with st.expander(f"#{row['autonumero']}  {row['Cliente']}  —  {row['Producto']}{'  📎' if (str(row.get('Foto1','')).strip() or str(row.get('Foto2','')).strip()) else ''}", expanded=False, key=f"t2card_{tono}_{rn}"):
                    # Encabezado + checkbox "Recibido" arriba a la derecha (se guarda al tildar)
                    c_head, c_chk = st.columns([4, 1], gap="small", vertical_alignment="center")
                    c_head.markdown(header_html, unsafe_allow_html=True)
                    c_chk.checkbox(
                        "📦 Recibido", key=key_rec,
                        on_change=_toggle_recibido, args=(rn, key_rec)
                    )
                    st.markdown("<hr style='margin:8px 0;border-color:#333;'>", unsafe_allow_html=True)

                    # Info de solo lectura
                    # (2x2 porque ahora cada tarjeta ocupa media pantalla)
                    ci1, ci2 = st.columns(2)
                    ci1.markdown(f"**Serial**<br>{row['Serial'] or '—'}", unsafe_allow_html=True)
                    ci2.markdown(f"**Falla**<br>{row['Falla'] or '—'}", unsafe_allow_html=True)
                    ci3, ci4 = st.columns(2)
                    ci3.markdown(f"**Ingreso**<br>{row['Ingreso'] or '—'}", unsafe_allow_html=True)
                    ci4.markdown(f"**Compra**<br>{row['Compra'] or '—'}", unsafe_allow_html=True)

                    # --- Fotos adjuntas por el cliente (si las hay) ---
                    foto1_val = str(row.get('Foto1', '')).strip()
                    foto2_val = str(row.get('Foto2', '')).strip()
                    if foto1_val or foto2_val:
                        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                        fotos_presentes = [v for v in [foto1_val, foto2_val] if v]
                        with st.container(border=True):
                            st.caption("📷 Fotos adjuntas por el cliente")
                            cols_fotos = st.columns(2)
                            for idx_f, valor_foto in enumerate(fotos_presentes):
                                with cols_fotos[idx_f]:
                                    if es_url_foto(valor_foto):
                                        # Cloudinary: el navegador carga la miniatura directo, sin pasar por el servidor
                                        st.image(miniatura_cloudinary(valor_foto, 320, 320), width=160,
                                                 caption=f"Foto {idx_f + 1}")
                                        if st.button("🔍 Ampliar", key=f"ver_foto_{rn}_{idx_f}"):
                                            _ver_foto_grande(valor_foto)
                                    else:
                                        # Ticket viejo con la foto en Drive
                                        foto_bytes = descargar_foto_de_drive(valor_foto)
                                        if not foto_bytes:
                                            st.caption(f"⚠️ Foto {idx_f + 1} no disponible")
                                            continue
                                        st.image(foto_bytes, width=160, caption=f"Foto {idx_f + 1}")
                                        if st.button("🔍 Ampliar", key=f"ver_foto_{rn}_{idx_f}"):
                                            _ver_foto_grande(foto_bytes)

                    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

                    with st.form(f"form_t2_{rn}"):
                        if st.session_state.rol == "admin":
                            fe1, fe2 = st.columns(2)
                            nuevo_diag = fe1.text_input(
                                "🔧 Diagnóstico",
                                value=str(row.get('diagnostico', '')),
                                key=f"diag_{rn}"
                            )
                            nuevo_estado = fe2.selectbox(
                                "📋 Estado del RMA",
                                options=["", "CAMBIO", "CREDITO", "GARANTIA OFICIAL", "GARANTIA",
                                         "FUERA DE GARANTIA", "NO FALLO - DEVOLVER A CLIENTE", "REPARADO",
                                         "RECHAZADO", "NUNCA ENVIO"],
                                index=(["", "CAMBIO", "CREDITO", "GARANTIA OFICIAL", "GARANTIA",
                                        "FUERA DE GARANTIA", "NO FALLO - DEVOLVER A CLIENTE", "REPARADO",
                                         "RECHAZADO", "NUNCA ENVIO"
                                        ].index(str(row.get('Estado del RMA', '')))
                                       if str(row.get('Estado del RMA', '')) in
                                       ["", "CAMBIO", "CREDITO", "GARANTIA OFICIAL", "GARANTIA",
                                        "FUERA DE GARANTIA", "NO FALLO - DEVOLVER A CLIENTE", "REPARADO",
                                         "RECHAZADO", "NUNCA ENVIO"]
                                       else 0),
                                key=f"estado_{rn}"
                            )
                            fe3, fe4 = st.columns([3, 1])
                            nuevo_comentario = fe3.text_input(
                                "💬 Comentario",
                                value=str(row.get('comentario', '')),
                                key=f"com_{rn}"
                            )
                            nuevo_ingreso = fe3.text_input(
                                "📅 Fecha Ingreso (dd/mm/aaaa)",
                                value=str(row.get('Ingreso', '')),
                                key=f"ing_{rn}"
                            )
                            nuevo_finalizado = fe4.checkbox(
                                "✅ Finalizar ticket",
                                value=False,
                                key=f"fin_{rn}"
                            )
                        else:
                            nuevo_comentario = st.text_input(
                                "💬 Comentario",
                                value=str(row.get('comentario', '')),
                                key=f"com_{rn}"
                            )
                            nuevo_diag = row.get('diagnostico', '')
                            nuevo_estado = row.get('Estado del RMA', '')
                            nuevo_finalizado = False
                            nuevo_ingreso = row.get('Ingreso', '')

                        if st.form_submit_button("💾 Guardar cambios", use_container_width=True):
                            up = {}
                            orig = df2[df2['row_number'] == rn].iloc[0]

                            if st.session_state.rol == "admin":
                                if nuevo_diag != str(orig.get('diagnostico', '')):
                                    up['diagnostico'] = nuevo_diag
                                if nuevo_estado != str(orig.get('Estado del RMA', '')):
                                    up['Estado del RMA'] = nuevo_estado
                                if nuevo_ingreso:
                                    val_f, stt_f = formatear_y_validar_fecha(nuevo_ingreso)
                                    if stt_f == "OK" and val_f and val_f != orig.get('Ingreso', ''):
                                        up['Ingreso'] = val_f

                            if nuevo_comentario != str(orig.get('comentario', '')):
                                up['comentario'] = nuevo_comentario

                            esta_finalizando = False
                            if st.session_state.rol == "admin" and nuevo_finalizado:
                                esta_finalizando = True
                                up['Finalizado'] = booleano_a_sheets(True)
                                up['Resolucion'] = date.today().strftime('%Y-%m-%d')

                            if esta_finalizando:
                                rma_id        = orig.get('autonumero', '')
                                motivo_tramite = orig.get('Motivo del trámite', 'RMA') or 'RMA'
                                prod_nom      = orig.get('Producto', '')
                                diag_val      = nuevo_diag
                                estado_rma    = nuevo_estado
                                fecha_resolucion_str = date.today().strftime('%d/%m/%Y')
                                telefono_val  = normalizar_telefono(orig.get('Telefono', ''))
                                email_val     = str(orig.get('Email', '')).strip().lower()
                                if telefono_val and telefono_val != str(orig.get('Telefono', '')).strip():
                                    up['Telefono'] = telefono_val

                                if telefono_val:
                                    import urllib.parse
                                    mensaje_wa = (
                                        f"Su número de caso #{rma_id} correspondiente al producto {prod_nom} ha finalizado.\n\n"
                                        f"Diagnóstico: {diag_val}\n"
                                        f"Resolución: {estado_rma}\n"
                                        f"Fecha resolución: {fecha_resolucion_str}\n\n"
                                        f"Le recomendamos contactarnos para coordinar el retiro del producto "
                                        f"o la gestión de la nota de crédito según corresponda.\n\n"
                                        f"Servicio Técnico: 3433002458\n"
                                        f"Ventas: 3434469399\n"
                                        f"Email: federico@altavistasa.com.ar"
                                    )
                                    link_wa = f"https://wa.me/{telefono_val}?text={urllib.parse.quote(mensaje_wa)}"
                                    asunto_ws = "Caso finalizado - Mensaje para el cliente"
                                    cuerpo_html = f"""<html><body>
    <p><b>RMA FINALIZADO — MENSAJE PARA CLIENTE</b></p>
    <table style="border-collapse:collapse;margin-bottom:16px;">
      <tr><td style="padding:4px 12px 4px 0;color:#888;">Teléfono</td><td><b>{telefono_val}</b></td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#888;">Caso</td><td><b>#{rma_id}</b></td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#888;">Producto</td><td>{prod_nom}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#888;">Diagnóstico</td><td>{diag_val}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#888;">Resolución</td><td>{estado_rma}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#888;">Fecha</td><td>{fecha_resolucion_str}</td></tr>
    </table>
    <a href="{link_wa}" style="display:inline-block;background-color:#25D366;color:#fff;padding:12px 24px;text-decoration:none;border-radius:6px;font-weight:bold;font-size:15px;">
      📲 Abrir WhatsApp y enviar mensaje
    </a>
    <p style="margin-top:16px;color:#888;font-size:12px;">
      Si el botón no funciona, copiá este enlace:<br>
      <a href="{link_wa}">{link_wa}</a>
    </p>
    </body></html>"""
                                    despachar_correo("EMAIL_INTERNO", "federico@altavistasa.com.ar", asunto_ws, cuerpo_html, html=True)

                                elif email_val:
                                    asunto_email = f"ALTAVISTA SA - Su caso de {motivo_tramite} número: {rma_id} ha sido resuelto."
                                    cuerpo_email = (
                                        f"Su número de caso #{rma_id} correspondiente al producto {prod_nom} ha finalizado.\n\n"
                                        f"--------------------------------------------------\n\n"
                                        f"Diagnóstico: {diag_val}\n"
                                        f"Resolución: {estado_rma}\n"
                                        f"Fecha resolución: {fecha_resolucion_str}\n\n"
                                        f"--------------------------------------------------\n\n"
                                        f"Le recomendamos contactarnos para coordinar el retiro del producto, o la gestión de la nota de crédito según corresponda.\n\n"
                                        f"Servicio Técnico: 3433002458\n"
                                        f"Ventas: 3434469399\n"
                                        f"Email: federico@altavistasa.com.ar"
                                    )
                                    despachar_correo("EMAIL_CLIENTE", email_val, asunto_email, cuerpo_email)

                            if up:
                                guardar_registros([{"row": rn, "data": up}])
                                if esta_finalizando:
                                    st.rerun()  # completo: el ticket pasa a la Tabla 3
                                else:
                                    rerun_fragmento()
                            else:
                                st.info("No hay cambios para guardar.")


            def _render_columna_t2(df_col, titulo, color, msg_vacio):
                st.markdown(
                    f"<div style='font-size:13px;font-weight:700;color:{color};"
                    f"border-bottom:2px solid {color};padding-bottom:4px;margin-bottom:6px;'>"
                    f"{titulo} ({len(df_col)})</div>",
                    unsafe_allow_html=True
                )
                if df_col.empty:
                    st.caption(msg_vacio)
                    return
                ultimo_grupo = None
                for posicion, (_, row) in enumerate(df_col.iterrows()):
                    # Separador de grupo (si no es por RMA)
                    if orden_col != "autonumero":
                        grupo_actual = str(row[orden_col]).strip()
                        if grupo_actual != ultimo_grupo:
                            st.markdown(
                                f"<div style='margin:4px 0 2px 0; color:#8ba8d0; "
                                f"font-size:11px; font-weight:700; letter-spacing:.08em; "
                                f"text-transform:uppercase; border-bottom:1px solid #2d3a52; "
                                f"padding-bottom:4px;'>{grupo_actual}</div>",
                                unsafe_allow_html=True
                            )
                            ultimo_grupo = grupo_actual
                    _render_tarjeta_t2(row, posicion)

            col_izq, col_der = st.columns(2, gap="medium")
            with col_izq:
                _render_columna_t2(df2_sin_recibir, "⏳ ACEPTADOS — SIN RECIBIR", "#fd7e14",
                                   "No hay tickets pendientes de recibir.")
            with col_der:
                _render_columna_t2(df2_recibidos, "📦 ACEPTADOS — RECIBIDOS", "#28a745",
                                   "Todavía no hay tickets recibidos.")


        else:
            st.info("No hay tickets en proceso.")

tabla_2()

# --- TABLA 3: HISTÓRICO ---
# (fragmento: un cambio acá re-ejecuta solo esta tabla, no todo el panel)
@st.fragment
def tabla_3():
    df_all = df_visible()
    df3 = df_all[(df_all['Aceptado'] == True) & (df_all['Finalizado'] == True)].copy().reset_index(drop=True)
    with st.expander("✅ 3. CASOS RESUELTOS (Histórico)"):
        if not df3.empty:
            # --- Por defecto solo los últimos DIAS_HISTORICO días (por fecha de Resolución) ---
            DIAS_HISTORICO = 60
            def _fecha_res(v):
                v = str(v).strip()
                for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y'):
                    try:
                        return datetime.strptime(v, fmt).date()
                    except ValueError:
                        continue
                return None
            _fechas = df3['Resolucion'].apply(_fecha_res)
            # Sin fecha legible: se muestran igual (mejor no ocultar un caso por un dato mal cargado)
            _recientes = _fechas.apply(lambda f: f is None or (date.today() - f).days <= DIAS_HISTORICO)
            ver_todo = st.session_state.get('t3_ver_todo', False)

            df3['Resolucion'] = df3['Resolucion'].apply(formatear_para_leer)

            # --- Leyenda de colores ---
            st.markdown("""
            <div style="display:flex; flex-wrap:wrap; gap:10px; margin-bottom:14px; align-items:center;">
                <span style="font-size:12px; color:#aaa; margin-right:4px;">Referencias:</span>
                <span style="background:#28a745; color:white; padding:3px 12px; border-radius:4px; font-size:12px; font-weight:600;">🟢 Cambio / Crédito</span>
                <span style="background:#fd7e14; color:black; padding:3px 12px; border-radius:4px; font-size:12px; font-weight:600;">🟠 Garantía / Garantía Oficial</span>
                <span style="background:#17a2b8; color:white; padding:3px 12px; border-radius:4px; font-size:12px; font-weight:600;">🔵 No falló – Devolver a cliente</span>
                <span style="background:#dc3545; color:white; padding:3px 12px; border-radius:4px; font-size:12px; font-weight:600;">🔴 Fuera de garantía / Rechazado</span>
                <span style="background:#6c757d; color:white; padding:3px 12px; border-radius:4px; font-size:12px; font-weight:600;">⚪ Reparado</span>
                <span style="background:#6f42c1; color:white; padding:3px 12px; border-radius:4px; font-size:12px; font-weight:600;">🟣 Nunca envió</span>
            </div>
            """, unsafe_allow_html=True)

            # --- Buscador (fuera del form) ---
            sc1, sc2, sc3, _ = st.columns([2, 2, 2, 2])
            busq_cliente  = sc1.text_input("🔍 Cliente",   key="t3_cli",    placeholder="Buscar cliente...",  label_visibility="collapsed")
            busq_rma      = sc2.text_input("🔍 Nº RMA",    key="t3_rma",    placeholder="Buscar Nº RMA...",   label_visibility="collapsed")
            busq_serial   = sc3.text_input("🔍 Serial",    key="t3_serial", placeholder="Buscar serial...",   label_visibility="collapsed")

            hay_busqueda = bool(busq_cliente.strip() or busq_rma.strip() or busq_serial.strip())
            # Al buscar se busca en TODO el histórico; sin búsqueda, solo lo reciente (salvo "ver todo")
            if ver_todo or hay_busqueda:
                df3_filtrado = df3.copy()
            else:
                df3_filtrado = df3[_recientes.values].copy()
            if busq_cliente.strip():
                df3_filtrado = df3_filtrado[df3_filtrado['Cliente'].astype(str).str.contains(busq_cliente.strip(), case=False, na=False)]
            if busq_rma.strip():
                df3_filtrado = df3_filtrado[df3_filtrado['autonumero'].astype(str).str.contains(busq_rma.strip(), case=False, na=False)]
            if busq_serial.strip():
                df3_filtrado = df3_filtrado[df3_filtrado['Serial'].astype(str).str.contains(busq_serial.strip(), case=False, na=False)]

            cap1, cap2 = st.columns([3, 1], vertical_alignment="center")
            if ver_todo or hay_busqueda:
                cap1.caption(f"Mostrando **{len(df3_filtrado)}** de **{len(df3)}** casos resueltos (histórico completo)")
            else:
                cap1.caption(f"Mostrando **{len(df3_filtrado)}** casos resueltos en los últimos {DIAS_HISTORICO} días "
                             f"(total histórico: {len(df3)})")
            def _set_ver_todo(valor):
                st.session_state['t3_ver_todo'] = valor
            if ver_todo:
                cap2.button(f"↩️ Ver solo últimos {DIAS_HISTORICO} días", key="t3_btn_recientes",
                            use_container_width=True, on_click=_set_ver_todo, args=(False,))
            else:
                cap2.button("📂 Cargar histórico completo", key="t3_btn_todo",
                            use_container_width=True, on_click=_set_ver_todo, args=(True,))

            with st.form("f3"):
                c3_cols = ['autonumero', 'comentario', 'Cliente', 'Producto', 'diagnostico', 'Estado del RMA', 'Resolucion']
                st_df3 = df3_filtrado[['row_number'] + c3_cols]
            
                deshabilitados_t3 = ['autonumero', 'Cliente', 'Producto', 'diagnostico', 'Estado del RMA', 'Resolucion']
            
                ed3 = st.data_editor(
                    st_df3.style.apply(estilo_filas, axis=1),
                    column_config={
                        "row_number": None,
                        "autonumero": st.column_config.TextColumn("🔢 Nº RMA", width="small"),
                        "comentario": st.column_config.TextColumn("💬 Comentario", width="medium"),
                        "diagnostico": st.column_config.TextColumn("🔧 Diagnóstico", width="medium")
                    },
                    disabled=deshabilitados_t3,
                    hide_index=True,
                    use_container_width=True
                )
            
                if st.form_submit_button("ACTUALIZAR COMENTARIOS HISTÓRICO"):
                    records_to_update = []
                    for _, r in ed3.iterrows():
                        orig = df3_filtrado[df3_filtrado['row_number'] == r['row_number']].iloc[0]
                        up = {k: r[k] for k in ['comentario'] if str(r[k]) != str(orig.get(k, ""))}
                        if up:
                            records_to_update.append({"row": r['row_number'], "data": up})
                
                    # ✅ CORREGIDO: un solo request en lugar de N loops
                    if records_to_update:
                        guardar_registros(records_to_update)
                    rerun_fragmento()

tabla_3()

