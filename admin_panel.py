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
    delete_row,
    find_row_by_values,
    clear_cache
)
from utils import es_verdadero, booleano_a_sheets

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
                st.error("Error de configuración: No se encontró la sección [USUARIOS] in los Secrets.")

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
    for formato in ['%d/%m/%y', '%d/%m/%Y']:
        try:
            dt_objeto = datetime.strptime(texto, formato)
            if dt_objeto.date() > date.today(): return None, "FUTURA"
            return dt_objeto.strftime('%Y-%m-%d'), "OK"
        except ValueError: continue
    return None, "FORMATO_INVALIDO"

@st.cache_data(ttl=5)
def cargar_todos_los_datos():
    """Carga todos los registros de Google Sheets"""
    df = get_dataframe()
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
    st.warning("No hay datos para mostrar.")
    st.stop()

# # --- LINKS DE ADMINISTRADOR ---
if st.session_state.rol == "admin" or st.session_state.usuario == "edu":
    c1, c2, c3, c4, c5, c6 = st.columns(6)
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
    with c6: st.link_button("🔁 Proveedores - RMA", "https://panelproveedores.streamlit.app/", use_container_width=True)

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
                                up[k] = booleano_a_sheets(r[k])
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
                        
                        rma_id = orig.get('autonumero', '')
                        cliente_id = cliente_nom
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
                        records_to_update.append({"row": r['row_number'], "data": up})
                        
                # Guardado en Google Sheets
                if records_to_update:
                    for rec in records_to_update:
                        update_record(rec['row'], rec['data'])
                        
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
        
        with st.form("f2"):
            if st.session_state.rol == "admin":
                c2_cols = ['autonumero', 'Cliente', 'Producto', 'Serial', 'Falla', 'Ingreso', 'diagnostico', 'Estado del RMA', 'Finalizado']
                deshabilitados_t2 = ['autonumero', 'Cliente', 'Producto', 'Serial', 'Falla']
            else:
                c2_cols = ['comentario', 'autonumero', 'Cliente', 'Producto', 'Ingreso', 'Serial', 'Estado del RMA', 'Resolucion']
                deshabilitados_t2 = ['Cliente', 'autonumero', 'Producto', 'Ingreso', 'Serial', 'Estado del RMA', 'Resolucion']
            
            st_df2 = df2[['row_number'] + c2_cols]
            
            ed2 = st.data_editor(
                st_df2.style.apply(estilo_filas, axis=1), 
                column_config={
                    "row_number": None, 
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
                records_to_update = []
                for _, r in ed2.iterrows():
                    orig = df2[df2['row_number'] == r['row_number']].iloc[0]
                    campos_a_revisar = ['comentario', 'diagnostico', 'Estado del RMA', 'Finalizado'] if st.session_state.rol == "admin" else ['comentario']
                    
                    # Convertir booleanos a strings para Google Sheets
                    up = {}
                    for k in campos_a_revisar:
                        if k in r and str(r[k]) != str(orig.get(k, "")):
                            if k in ['Aceptado', 'Finalizado']:
                                up[k] = booleano_a_sheets(r[k])
                            else:
                                up[k] = r[k]
                    
                    esta_finalizando = False
                    if st.session_state.rol == "admin" and 'Finalizado' in r:
                        finalizado_nuevo = es_verdadero(r.get('Finalizado', False))
                        finalizado_original = es_verdadero(orig.get('Finalizado', False))
                        
                        if finalizado_nuevo and not finalizado_original:
                            esta_finalizando = True
                            up['Resolucion'] = date.today().strftime('%Y-%m-%d')
                    
                    if st.session_state.rol == "admin" and 'Ingreso' in r:
                        val, stt = formatear_y_validar_fecha(r['Ingreso'])
                        if stt == "OK" and val != orig.get('Ingreso', ''): 
                            up['Ingreso'] = val
                    
                    if esta_finalizando:
                        rma_id = orig.get('autonumero', '')
                        motivo_tramite = orig.get('Motivo del trámite', 'RMA')
                        if not motivo_tramite: motivo_tramite = "RMA"
                        prod_nom = orig.get('Producto', '')
                        
                        diag_val = r.get('diagnostico', orig.get('diagnostico', ''))
                        estado_rma = r.get('Estado del RMA', orig.get('Estado del RMA', ''))
                        fecha_resolucion_str = date.today().strftime('%d/%m/%Y')
                        
                        telefono_val = orig.get('Telefono', '').strip()
                        email_val = orig.get('Email', '').strip().lower()
                        
                        if telefono_val != "":
                            asunto_ws = "Caso finalizado - Mensaje para el cliente"
                            cuerpo_ws = (
                                f"RMA FINALIZADO - MENSAJE PARA CLIENTE\n"
                                f"wa.me/{telefono_val}\n"
                                f"---------------------------------------------------------------------------------------------------------------------------\n\n"
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
                            despachar_correo("EMAIL_INTERNO", "federico@altavistasa.com.ar", asunto_ws, cuerpo_ws)
                            
                        elif email_val != "":
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
                        records_to_update.append({"row": r['row_number'], "data": up})
                
                # Guardado en Google Sheets
                if records_to_update:
                    for rec in records_to_update:
                        update_record(rec['row'], rec['data'])
                        
                clear_cache()
                st.rerun()

# --- TABLA 3: HISTÓRICO ---
df3 = df_all[(df_all['Aceptado'] == True) & (df_all['Finalizado'] == True)].copy().reset_index(drop=True)
with st.expander("✅ 3. CASOS RESUELTOS (Histórico)"):
    if not df3.empty:
        df3['Resolucion'] = df3['Resolucion'].apply(formatear_para_leer)
        
        with st.form("f3"):
            c3_cols = ['autonumero', 'comentario', 'Cliente', 'Producto', 'diagnostico', 'Estado del RMA', 'Resolucion']
            st_df3 = df3[['row_number'] + c3_cols]
            
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
                    orig = df3[df3['row_number'] == r['row_number']].iloc[0]
                    up = {k: r[k] for k in ['comentario'] if str(r[k]) != str(orig.get(k, ""))}
                    if up:
                        records_to_update.append({"row": r['row_number'], "data": up})
                
                # Guardado en Google Sheets
                if records_to_update:
                    for rec in records_to_update:
                        update_record(rec['row'], rec['data'])
                        
                clear_cache()
                st.rerun()
