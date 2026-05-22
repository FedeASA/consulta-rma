import streamlit as st
from pyairtable import Api
from datetime import date
import urllib.parse
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Formulario RMA - ALTAVISTA SA", layout="centered")

# --- LIMPIEZA VISUAL Y ESTILOS ---
st.markdown("""
    <style>
    div[data-testid="stTextInput"] [data-testid="InputInstructions"],
    div[data-testid="stTextArea"] [data-testid="InputInstructions"],
    div[data-testid="stInputInstructions"],
    .stInputInstructions {
        display: none !important;
    }
    .block-container { padding-top: 2rem; }
    [data-testid="stVerticalBlockBorderControl"] {
        border: 1px solid rgba(49, 51, 63, 0.2);
        border-radius: 0.5rem;
        padding: 2rem;
    }
    .btn-whatsapp-custom {
        background-color: #25D366;
        color: white !important;
        border: 1px solid #25D366;
        padding: 0px 16px;
        text-align: center;
        text-decoration: none;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        border-radius: 8px;
        font-weight: 400;
        font-size: 14px;
        font-family: inherit;
        width: 100%;
        height: 38px;
        box-sizing: border-box;
        cursor: pointer;
        transition: background-color 0.16s ease 0s, border-color 0.16s ease 0s;
    }
    .btn-whatsapp-custom:hover {
        background-color: #20ba5a;
        border-color: #20ba5a;
        text-decoration: none;
    }
    </style>
    """, unsafe_allow_html=True)

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

# --- INICIALIZACIÓN DE ESTADO ---
if 'enviado' not in st.session_state:
    st.session_state.enviado = False
if 'resumen_rma' not in st.session_state:
    st.session_state.resumen_rma = {}

# --- CREDENCIALES AIRTABLE ---
try:
    AIRTABLE_TOKEN = st.secrets["AIRTABLE_TOKEN"]
    BASE_ID = st.secrets["BASE_ID"]
    TABLE_NAME = "RMA ALTAVISTA" 
    api = Api(AIRTABLE_TOKEN)
    table = api.table(BASE_ID, TABLE_NAME)
except Exception:
    st.error("Error: No se pudieron cargar las credenciales de Airtable.")
    st.stop()

# --- CABECERA ---
st.markdown("<h1 style='text-align: center;'>Solicitud de RMA / DEVOLUCION</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center;'>Recuerde que el producto debe contar su embalaje / blíster o caja. NO SE ACEPTARÁN PRODUCTOS SIN CAJA NI NUMERO DE SERIE.</p>", unsafe_allow_html=True)
st.markdown("---")

# --- CUERPO ---
with st.container(border=True):
    if st.session_state.enviado:
        st.success("¡Solicitud enviada con éxito! En breve le asignaremos su número de RMA.")
        
        d = st.session_state.resumen_rma
        texto_ws = (
            f"Hola ALTAVISTA SA, acabo de enviar una solicitud de RMA / DEVOLUCION:\n\n"
            f"- *Cliente:* {d.get('cliente', '')}\n"
            f"- *Producto:* {d.get('producto', '')}\n"
            f"- *Serial:* {d.get('serial', '')}\n"
            f"- *Falla:* {d.get('falla', '')}"
        )
        texto_encoded = urllib.parse.quote(texto_ws)
        link_whatsapp = f"https://wa.me/5493433002458?text={texto_encoded}"
        
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("CARGAR OTRO PRODUCTO", type="secondary", use_container_width=True):
                st.session_state.enviado = False
                st.session_state.resumen_rma = {}
                st.rerun()
                
        with col_btn2:
            st.markdown(f"""
                <a href="{link_whatsapp}" target="_blank" class="btn-whatsapp-custom">
                    Contactanos
                </a>
                """, unsafe_allow_html=True)
            
    else:
        fila1_col1, fila1_col2 = st.columns(2)
        with fila1_col1:
            cliente = st.text_input("Nombre / Razón Social", placeholder="Ej: Juan Pérez o Empresa S.A.").upper()
        with fila1_col2:
            serial_in = st.text_input("Serial (SN - ASA)", placeholder="Ubicado en la etiqueta")

        fila2_col1, fila2_col2 = st.columns(2)
        with fila2_col1:
            producto_in = st.text_input("Producto", placeholder="Ingrese nombre de producto")
        with fila2_col2:
            fecha_compra = st.date_input("Fecha de Compra", max_value=date.today(), format="DD/MM/YYYY")

        motivo = st.selectbox("Motivo del trámite", options=["RMA", "Devolución"])
        descripcion = st.text_area("Descripción de la falla", placeholder="Especifique el error / falla detalladamente...")

        st.markdown("---")
        opcion_contacto = st.radio("¿Cómo prefiere que nos contactemos?", options=["WhatsApp", "Correo Electrónico"], horizontal=True)

        telefono_val = ""
        email_val = ""
        if opcion_contacto == "WhatsApp":
            telefono_val = st.text_input("Número de WhatsApp", placeholder="Ej: +5493433002458")
        else:
            email_val = st.text_input("Dirección de Correo Electrónico", placeholder="Ej: ejemplo@correo.com")

        st.markdown("---")
        enviar = st.button("ENVIAR SOLICITUD", type="primary", use_container_width=True)

        if enviar:
            if not cliente or not producto_in or not serial_in:
                st.error("Por favor, complete todos los campos obligatorios.")
            else:
                try:
                    st.session_state.resumen_rma = {
                        "cliente": cliente,
                        "producto": producto_in,
                        "serial": serial_in,
                        "falla": descripcion
                    }
                    
                    nuevo_registro = {
                        "Cliente": cliente,
                        "Producto": producto_in,
                        "Serial": serial_in,
                        "Compra": str(fecha_compra),
                        "Motivo del trámite": motivo, 
                        "Falla": descripcion,        
                        "Telefono": telefono_val,      
                        "Email": email_val.strip().lower(),            
                        "Estado del RMA": "PENDIENTE",
                        "Ingreso": str(date.today())
                    }
                    
                    table.create(nuevo_registro)
                    
                    # CORRECCIÓN: Estructura de cuerpo_ws corregida y nombres de variables ajustados
                    cuerpo_ws = (
                        f"Has recibido una nueva solicitud de RMA.\n"
                        f"Revisa los datos en Panel RMA y acepta el caso si corresponde.\n"
                        f"-----------------------------------------------------------\n"
                        f"SOLICITUD - MENSAJE PARA CLIENTE\n"
                        f"wa.me/{telefono_val.strip()}\n"
                        f"-----------------------------------------------------------\n"
                        f"¡Su solicitud para RMA ha sido cargada con éxito!\n"
                        f"-----------------------------------------------------------\n"
                        f"Producto: {producto_in}\n"
                        f"Serial: {serial_in}\n"
                    )

                    st.session_state.enviado = True
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al enviar: {e}")
