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
        div[data-testid="stExpander"] { border: 1px solid #444; margin-bottom: 1rem; }\n        [data-testid="stDataEditor"] div, .stDataTable td {
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
        [data-testid="stDataEditor"] * div * {
            color: #ffffff !important;
            font-weight: bold !important;
        }
        div[data-testid="stNotification"] {
            font-weight: bold !important;
        }
    </style>
    """, unsafe_allow_html=True)

try:
    AIRTABLE_TOKEN = st.secrets["AIRTABLE_TOKEN"]
    BASE_ID = st.secrets["BASE_ID"]
    TABLE_NAME = "RMA ALTAVISTA"
except Exception:
    st.error("Error: No se encontraron las credenciales en Secrets.")
    st.stop()

api = Api(AIRTABLE_TOKEN)
table = api.table(BASE_ID, TABLE_NAME)

# --- 2. ENVIADOR DE CORREOS ---
def despachar_correo(config_section, destinatario, asunto, cuerpo_texto):
    try:
        if config_section not in st.secrets:
            return False
        smtp_user = st.secrets[config_section]["SMTP_USER"]
        smtp_password = st.secrets[config_section]["SMTP_PASSWORD"]
        
        dest_limpio = str(destinatario).strip().lower()
        if not dest_limpio:
            return False
            
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = dest_limpio
        msg['Subject'] = asunto
        msg.attach(MIMEText(cuerpo_texto, 'plain', 'utf-8'))
        
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15)
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, dest_limpio, msg.as_string())
        server.quit()
        return True
    except Exception:
        return False

# --- 3. FUNCIONES AUXILIARES ---
def corregir_bool(x):
    return x in [True, 1, "True", "true", "1"]

def formatear_para_leer(val):
    if not val or str(val).strip() in ["None", "none", "nan", "NaN", ""]:
        return ""
    v_str = str(val).replace('-', '/').strip()
    for f in ['%Y/%m/%d', '%Y-%m-%d', '%d/%m/%Y']:
        try:
            return datetime.strptime(v_str, f).strftime('%d/%m/%Y')
        except ValueError:
            continue
    return str(val)

def estilo_filas(row):
    estilos = [''] * len(row)
    estado = str(row.get('Estado del RMA', '')).strip().upper()
    
    if "FUERA DE GARANTIA" in estado:
        color = 'background-color: #5c1d1d; color: #ffffff;'
    elif "PRESUPUESTO" in estado:
        color = 'background-color: #61460b; color: #ffffff;'
    elif "RECAMBIO" in estado or "REPARADO" in estado or "NOTA DE CREDITO" in estado:
        color = 'background-color: #1b4d22; color: #ffffff;'
    elif "PENDIENTE" in estado:
        color = 'background-color: #2b2b2b; color: #ffffff;'
    else:
        color = 'background-color: transparent; color: #ffffff;'
        
    for i in range(len(row)):
        estilos[i] = color
    return estilos

# --- 4. CARGA DE DATOS ---
try:
    records = table.all()
except Exception as e:
    st.error(f"Error al conectar con Airtable: {e}")
    st.stop()

lista_datos = []
for r in records:
    id_rec = r.get('id')
    f = r.get('fields', {})
    
    lista_datos.append({
        'id_interno': id_rec,
        'autonumero': str(f.get('autonumero', '')),
        'Cliente': str(f.get('Cliente', '')).upper(),
        'Producto': str(f.get('Producto', '')),
        'Serial': str(f.get('Serial', '')),
        'Compra': f.get('Compra', ''),
        'Motivo del trámite': f.get('Motivo del trámite', ''),
        'Falla': f.get('Falla', ''),
        'diagnostico': f.get('diagnostico', ''),
        'comentario': f.get('comentario', ''),
        'Telefono': str(f.get('Telefono', '')),
        'Email': str(f.get('Email', '')).strip().lower(),
        'Estado del RMA': str(f.get('Estado del RMA', 'PENDIENTE')).strip().upper(),
        'Ingreso': f.get('Ingreso', ''),
        'Resolucion': f.get('Resolucion', ''),
        'Aceptado': corregir_bool(f.get('Aceptado')),
        'Finalizado': corregir_bool(f.get('Finalizado'))
    })

df_base = pd.DataFrame(lista_datos)

if df_base.empty:
    st.info("No hay registros en la base de datos.")
    st.stop()

df1 = df_base[~df_base['Aceptado'] & ~df_base['Finalizado']].copy()
df2 = df_base[df_base['Aceptado'] & ~df_base['Finalizado']].copy()
df3 = df_base[df_base['Finalizado']].copy()

# --- 5. INTERFAZ EN PANTALLA ---
st.title("🛡️ PANEL DE GESTIÓN RMA - ALTAVISTA SA")

with st.expander("📥 1. SOLICITUDES NUEVAS (Sin Aceptar)", expanded=not df1.empty):
    if not df1.empty:
        df1['Compra'] = df1['Compra'].apply(formatear_para_leer)
        df1['Ingreso'] = df1['Ingreso'].apply(formatear_para_leer)
        
        with st.form("f1"):
            c1_cols = ['autonumero', 'Aceptado', 'Cliente', 'Producto', 'Serial', 'Motivo del trámite', 'Falla', 'Compra', 'Ingreso', 'Email', 'Telefono']
            st_df1 = df1[['id_interno'] + c1_cols]
            
            deshabilitados_t1 = ['autonumero', 'Cliente', 'Producto', 'Serial', 'Motivo del trámite', 'Falla', 'Compra', 'Ingreso', 'Email', 'Telefono']
            
            ed1 = st.data_editor(
                st_df1,
                column_config={
                    "id_interno": None,
                    "autonumero": st.column_config.TextColumn("🔢 Nº RMA", width="small"),
                    "Aceptado": st.column_config.CheckboxColumn("✅ ¿Aceptar?", default=False, width="small"),
                    "Cliente": st.column_config.TextColumn("👤 Cliente"),
                    "Falla": st.column_config.TextColumn("❌ Falla Reportada", width="medium")
                },
                disabled=deshabilitados_t1,
                hide_index=True,
                use_container_width=True
            )
            
            if st.form_submit_button("ACEPTAR CASOS SELECCIONADOS"):
                con_cambios = 0
                for _, r in ed1.iterrows():
                    if r['Aceptado'] == True:
                        id_target = r['id_interno']
                        orig = df1[df1['id_interno'] == id_target].iloc[0]
                        
                        try:
                            table.update(id_target, {"Aceptado": True})
                            con_cambios += 1
                            
                            dest_c = str(orig['Email']).strip()
                            if dest_c:
                                n_rma = orig['autonumero']
                                msg_c = (
                                    f"Hola {orig['Cliente']}.\n\n"
                                    f"Le informamos que su solicitud para el producto {orig['Producto']} (Serial: {orig['Serial']}) "
                                    f"ha sido ACEPTADA por nuestro servicio técnico bajo el Número de RMA: {n_rma}.\n\n"
                                    f"El estado actual del caso es: EN PROCESO.\n"
                                    f"Puede realizar el seguimiento en tiempo real desde nuestra web:\n"
                                    f"https://rma-altavista.streamlit.app/"
                                )
                                despachar_correo("EMAIL_CLIENTE", dest_c, f"RMA {n_rma} Aceptado - Altavista SA", msg_c)
                        except Exception as e:
                            st.error(f"Error al actualizar ID {id_target}: {e}")
                if con_cambios > 0:
                    st.success(f"¡Se aceptaron {con_cambios} casos correctamente!")
                    st.rerun()

with st.expander("⚙️ 2. CASOS ACEPTADOS (En Proceso)", expanded=not df2.empty):
    if not df2.empty:
        df2['Ingreso'] = df2['Ingreso'].apply(formatear_para_leer)
        
        with st.form("f2"):
            # MODIFICACIÓN SOLICITADA: Quitamos 'diagnostico' y agregamos 'Serial'
            c2_cols = ['autonumero', 'comentario', 'Cliente', 'Producto', 'Serial', 'Estado del RMA', 'Finalizado', 'Ingreso']
            st_df2 = df2[['id_interno'] + c2_cols]
            
            # MODIFICACIÓN SOLICITADA: Quitamos 'diagnostico' y agregamos 'Serial' a deshabilitados
            deshabilitados_t2 = ['autonumero', 'Cliente', 'Producto', 'Serial', 'Ingreso']
            
            opciones_estado = [
                "PENDIENTE", "REVISANDO EN TALLER", "PRESUPUESTO ENVIADO", 
                "ESPERANDO REPUESTO", "FUERA DE GARANTIA", "REPARADO", 
                "RECAMBIO LISTO", "NOTA DE CREDITO", "PRODUCTO NO FALLO"
            ]
            
            ed2 = st.data_editor(
                st_df2.style.apply(estilo_filas, axis=1),
                column_config={
                    "id_interno": None,
                    "autonumero": st.column_config.TextColumn("🔢 Nº RMA", width="small"),
                    "comentario": st.column_config.TextColumn("💬 Comentario Interno", width="medium"),
                    "Cliente": st.column_config.TextColumn("👤 Cliente"),
                    "Producto": st.column_config.TextColumn("📦 Producto"),
                    "Serial": st.column_config.TextColumn("🔑 Número de Serie"), # Configuración visual del Serial
                    "Estado del RMA": st.column_config.SelectboxColumn("📊 Estado del RMA", options=opciones_estado, required=True, width="medium"),
                    "Finalizado": st.column_config.CheckboxColumn("🏁 ¿Finalizar?", default=False, width="small"),
                    "Ingreso": st.column_config.TextColumn("📅 Ingreso", width="small")
                },
                disabled=deshabilitados_t2,
                hide_index=True,
                use_container_width=True
            )
            
            if st.form_submit_button("GUARDAR CAMBIOS / FINALIZAR SELECCIONADOS"):
                con_cambios = 0
                for _, r in ed2.iterrows():
                    id_target = r['id_interno']
                    orig = df2[df2['id_interno'] == id_target].iloc[0]
                    
                    est_nuevo = str(r['Estado del RMA']).strip().upper()
                    est_viejo = str(orig['Estado del RMA']).strip().upper()
                    com_nuevo = str(r['comentario']).strip()
                    com_viejo = str(orig['comentario']).strip()
                    fin_nuevo = bool(r['Finalizado'])
                    
                    campos_update = {}
                    
                    if est_nuevo != est_viejo:
                        campos_update["Estado del RMA"] = est_nuevo
                    if com_nuevo != com_viejo:
                        campos_update["comentario"] = com_nuevo
                    if fin_nuevo:
                        campos_update["Finalizado"] = True
                        campos_update["Resolucion"] = str(date.today())
                        
                    if campos_update:
                        try:
                            table.update(id_target, campos_update)
                            con_cambios += 1
                            
                            dest_c = str(orig['Email']).strip()
                            n_rma = orig['autonumero']
                            
                            if fin_nuevo and dest_c:
                                msg_c = (
                                    f"Hola {orig['Cliente']}.\n\n"
                                    f"Le notificamos que su caso de RMA Número: {n_rma} para el producto {orig['Producto']} "
                                    f"ha sido FINALIZADO con el estado: {est_nuevo}.\n\n"
                                    f"Puede pasar a retirar el producto o coordinar la entrega según corresponda.\n"
                                    f"Consulte el historial de sus casos en nuestra web:\n"
                                    f"https://rma-altavista.streamlit.app/"
                                )
                                despachar_correo("EMAIL_CLIENTE", dest_c, f"RMA {n_rma} FINALIZADO - Altavista SA", msg_c)
                            elif est_nuevo != est_viejo and dest_c:
                                msg_c = (
                                    f"Hola {orig['Cliente']}.\n\n"
                                    f"Hubo una actualización en el estado de su RMA Número: {n_rma} ({orig['Producto']}).\n"
                                    f"El nuevo estado actual es: {est_nuevo}.\n\n"
                                    f"Siga la evolución del caso en vivo desde:\n"
                                    f"https://rma-altavista.streamlit.app/"
                                )
                                despachar_correo("EMAIL_CLIENTE", dest_c, f"Actualización de RMA {n_rma} - Altavista SA", msg_c)
                        except Exception as e:
                            st.error(f"Error al actualizar ID {id_target}: {e}")
                if con_cambios > 0:
                    st.success(f"¡Se actualizaron {con_cambios} registros correctamente!")
                    st.rerun()

with st.expander("📦 3. CASOS RESUELTOS (Histórico)"):
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
                    up = {k: r[k] for k in ['comentario'] if str(r[k]).strip() != str(orig[k]).strip()}
                    if up:
                        table.update(r['id_interno'], up)
                st.success("Historial actualizado.")
                st.rerun()
