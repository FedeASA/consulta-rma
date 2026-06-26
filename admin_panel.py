import streamlit as st
import pandas as pd
from datetime import datetime, date
import io
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sheets_operations import (
    get_dataframe,
    get_all_records,
    update_record,
    batch_update_records,
    delete_row,
    find_row_by_values,
    clear_cache
)
from utils import es_verdadero, booleano_a_sheets
from sso import generar_token

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
            except Exception as e:
                st.error(f"Error de configuración: {e}")

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
    for formato in ['%d/%m/%y', '%d/%m/%Y']:
        try:
            dt_objeto = datetime.strptime(texto, formato)
            if dt_objeto.date() > date.today(): return None, "FUTURA"
            return dt_objeto.strftime('%Y-%m-%d'), "OK"
        except ValueError: continue
    return None, "FORMATO_INVALIDO"

@st.cache_data(ttl=60, show_spinner=False)
def cargar_todos_los_datos():
    """Carga todos los registros de Google Sheets"""
    try:
        df = get_dataframe()
    except Exception as e:
        st.error(f"❌ Error al conectar con Google Sheets: {e}")
        st.stop()
    if df.empty:
        return pd.DataFrame()
    
    # Agregar ID (número de fila) para tracking
    df['row_number'] = range(2, len(df) + 2)  # Las filas de datos comienzan en 2
    return df

df_all = cargar_todos_los_datos()

# --- VERIFICACIÓN Y COMPATIBILIDAD DE COLUMNAS (AL INICIO PARA EVITAR DESFASES) ---
if not df_all.empty:
    columnas_requeridas = ['Aceptado', 'Finalizado', 'Ingreso', 'Resolucion', 'diagnostico', 'Estado del RMA', 'Compra', 'Producto', 'comentario', 'Falla', 'Serial', 'autonumero', 'Telefono', 'Email', 'Motivo del trámite', 'PROVEEDOR']
    for col in columnas_requeridas:
        if col not in df_all.columns: 
            df_all[col] = False if col in ['Aceptado', 'Finalizado'] else ""
        else:
            if col in ['Aceptado', 'Finalizado']:
                df_all[col] = df_all[col].apply(lambda x: es_verdadero(x))

    for col_txt in ['comentario', 'Falla', 'diagnostico', 'Ingreso', 'Resolucion', 'Compra', 'Cliente', 'Producto', 'Serial', 'autonumero', 'Telefono', 'Email', 'Motivo del trámite', 'PROVEEDOR']:
        if col_txt in df_all.columns:
            df_all[col_txt] = df_all[col_txt].fillna("").apply(lambda x: str(int(x)) if isinstance(x, float) and x.is_integer() else str(x))
            df_all[col_txt] = df_all[col_txt].apply(lambda x: "" if str(x).strip() in ["None", "none", "nan", "NaN", ""] else str(x).strip())
else:
    st.error("⚠️ No se pudieron cargar datos desde Google Sheets. Verificá las credenciales.")
    if st.button("🔄 Reintentar"):
        st.cache_data.clear()
        st.rerun()
    st.stop()

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
        cargar_todos_los_datos.clear()
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
        df1.insert(0, 'Eliminar', False)
        
        with st.form("f1"):
            if st.session_state.rol == "admin":
                # MODIFICADO: Se agrega PROVEEDOR y se deja la lista deshabilitada VACÍA (Todo es editable)
                c1_cols = ['Eliminar', 'Cliente', 'Producto', 'Serial', 'Falla', 'Compra', 'PROVEEDOR', 'Aceptado']
                esta_deshabilitado_t1 = []
            else:
                c1_cols = ['Eliminar', 'Cliente', 'Producto', 'Serial', 'Falla', 'PROVEEDOR']
                esta_deshabilitado_t1 = ['Cliente', 'Producto', 'Serial', 'Falla', 'PROVEEDOR']
            
            ed1 = st.data_editor(
                df1[['row_number'] + c1_cols].reset_index(drop=True), 
                column_config={
                    "row_number": None,
                    "Eliminar": st.column_config.CheckboxColumn("🗑️", width="small", help="Seleccione para eliminar este registro")
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
                confirmar_borrado = st.checkbox("Confirmo que deseo ELIMINAR los registros seleccionados.")
            with col_btn_elim:
                submit_eliminar = st.form_submit_button("🗑️ ELIMINAR REGISTROS", use_container_width=True)
            
            if submit_guardar and st.session_state.rol == "admin":
                records_to_update = []
                _numeros_existentes = pd.to_numeric(df_all['autonumero'], errors='coerce').dropna()
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
                        if k in r and str(r[k]) != str(orig.get(k, "")):
                           if k in ['Aceptado', 'Finalizado']:
                                up[k] = booleano_a_sheets(bool(r[k]))
                           else:
                                up[k] = r[k]
                    
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
                            up['autonumero'] = rma_id
                            _proximo_rma += 1

                        cliente_id = cliente_nom
                        estado_rma = "PENDIENTE"
                        telefono_val = orig.get('Telefono', '').strip()
                        email_val = orig.get('Email', '').strip().lower()     
                        
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
                    batch_update_records(records_to_update)
                        
                clear_cache()
                st.rerun()

            if submit_eliminar:
                registros_a_borrar = ed1[ed1['Eliminar'] == True]['row_number'].tolist()
                if not registros_a_borrar:
                    st.warning("No seleccionaste ningún registro para eliminar.")
                elif not confirmar_borrado:
                    st.error("Debes tildar la casilla de confirmación central para habilitar la eliminación.")
                else:
                    for row_borrar in registros_a_borrar:
                        delete_row(row_borrar)
                    st.success(f"¡Se eliminaron {len(registros_a_borrar)} registros correctamente!")
                    clear_cache()
                    st.rerun()
    else:
        st.info("No hay pendientes.")

# --- TABLA 2: EN PROCESO ---
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
        col_cnt.caption(f"**{len(df2_sorted)}** tickets en proceso")

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
        .badge-pendiente{ background:#444; color:#ccc; }
        .rma-sep { color:#555; }
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
            }.get(e, "badge-pendiente")
            label = e if e else "SIN ESTADO"
            return f'<span class="rma-badge {cls}">{label}</span>'

        ultimo_grupo = None

        for _, row in df2_sorted.iterrows():
            rn = row['row_number']

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

            with st.expander(f"#{row['autonumero']}  {row['Cliente']}  —  {row['Producto']}", expanded=False):
                st.markdown(header_html, unsafe_allow_html=True)
                st.markdown("<hr style='margin:8px 0;border-color:#333;'>", unsafe_allow_html=True)

                # Info de solo lectura
                ci1, ci2, ci3, ci4 = st.columns(4)
                ci1.markdown(f"**Serial**<br>{row['Serial'] or '—'}", unsafe_allow_html=True)
                ci2.markdown(f"**Falla**<br>{row['Falla'] or '—'}", unsafe_allow_html=True)
                ci3.markdown(f"**Ingreso**<br>{row['Ingreso'] or '—'}", unsafe_allow_html=True)
                ci4.markdown(f"**Compra**<br>{row['Compra'] or '—'}", unsafe_allow_html=True)

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
                                     "FUERA DE GARANTIA", "NO FALLO - DEVOLVER A CLIENTE", "REPARADO"],
                            index=(["", "CAMBIO", "CREDITO", "GARANTIA OFICIAL", "GARANTIA",
                                    "FUERA DE GARANTIA", "NO FALLO - DEVOLVER A CLIENTE", "REPARADO"
                                    ].index(str(row.get('Estado del RMA', '')))
                                   if str(row.get('Estado del RMA', '')) in
                                   ["", "CAMBIO", "CREDITO", "GARANTIA OFICIAL", "GARANTIA",
                                    "FUERA DE GARANTIA", "NO FALLO - DEVOLVER A CLIENTE", "REPARADO"]
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
                            telefono_val  = str(orig.get('Telefono', '')).strip()
                            email_val     = str(orig.get('Email', '')).strip().lower()

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
                            batch_update_records([{"row": rn, "data": up}])
                            clear_cache()
                            st.rerun()
                        else:
                            st.info("No hay cambios para guardar.")

        # ── Colores alternados por JS (inmune a separadores de grupo) ──
        import streamlit.components.v1 as components
        components.html("""
<script>
function colorCards() {
    var doc = window.parent.document;
    // Busca todos los expanders de nivel 2 (tarjetas dentro de la Tabla 2)
    var outer = doc.querySelectorAll('[data-testid="stExpander"]');
    var cards = null;
    for (var i = 0; i < outer.length; i++) {
        var nested = outer[i].querySelectorAll('[data-testid="stExpander"]');
        if (nested.length >= 1 && cards === null) {
            cards = nested;
        }
    }
    if (!cards) return;
    var colors = ['#0d2b45', '#3a4f63'];
    for (var j = 0; j < cards.length; j++) {
        var el = cards[j];
        var col = colors[j % 2];
        el.style.backgroundColor = col;
        el.style.borderRadius = '6px';
        var summary = el.querySelector('summary');
        if (summary) { summary.style.backgroundColor = col; summary.style.borderRadius = '6px'; }
    }
}
colorCards();
setTimeout(colorCards, 150);
setTimeout(colorCards, 500);
// Re-aplicar cuando el usuario expande/colapsa una tarjeta
window.parent.document.addEventListener('click', function() { setTimeout(colorCards, 80); });
</script>
""", height=0)

    else:
        st.info("No hay tickets en proceso.")

# --- TABLA 3: HISTÓRICO ---
df3 = df_all[(df_all['Aceptado'] == True) & (df_all['Finalizado'] == True)].copy().reset_index(drop=True)
with st.expander("✅ 3. CASOS RESUELTOS (Histórico)"):
    if not df3.empty:
        df3['Resolucion'] = df3['Resolucion'].apply(formatear_para_leer)

        # --- Buscador (fuera del form) ---
        sc1, sc2, sc3, _ = st.columns([2, 2, 2, 2])
        busq_cliente  = sc1.text_input("🔍 Cliente",   key="t3_cli",    placeholder="Buscar cliente...",  label_visibility="collapsed")
        busq_rma      = sc2.text_input("🔍 Nº RMA",    key="t3_rma",    placeholder="Buscar Nº RMA...",   label_visibility="collapsed")
        busq_serial   = sc3.text_input("🔍 Serial",    key="t3_serial", placeholder="Buscar serial...",   label_visibility="collapsed")

        df3_filtrado = df3.copy()
        if busq_cliente.strip():
            df3_filtrado = df3_filtrado[df3_filtrado['Cliente'].astype(str).str.contains(busq_cliente.strip(), case=False, na=False)]
        if busq_rma.strip():
            df3_filtrado = df3_filtrado[df3_filtrado['autonumero'].astype(str).str.contains(busq_rma.strip(), case=False, na=False)]
        if busq_serial.strip():
            df3_filtrado = df3_filtrado[df3_filtrado['Serial'].astype(str).str.contains(busq_serial.strip(), case=False, na=False)]

        st.caption(f"Mostrando **{len(df3_filtrado)}** de **{len(df3)}** casos resueltos")

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
                    batch_update_records(records_to_update)
                        
                clear_cache()
                st.rerun()
