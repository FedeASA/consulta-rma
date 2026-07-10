import streamlit as st
from datetime import date
import urllib.parse
import smtplib
import io
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from PIL import Image
from sheets_operations import create_record, subir_foto_a_drive
from utils import validar_email

# --- PREPARACIÓN DE FOTOS PARA SUBIR A GOOGLE DRIVE ---
def preparar_imagen_para_drive(archivo_subido, ancho_max=1600, calidad=85):
    """Redimensiona (si hace falta) y comprime la imagen antes de subirla a Drive."""
    try:
        archivo_subido.seek(0)
        imagen = Image.open(archivo_subido)
        imagen = imagen.convert("RGB")  # normaliza PNG con transparencia, modo P, etc.
    except Exception:
        return None

    if imagen.width > ancho_max:
        ratio = ancho_max / imagen.width
        nuevo_alto = max(1, int(imagen.height * ratio))
        imagen = imagen.resize((ancho_max, nuevo_alto))

    buffer = io.BytesIO()
    imagen.save(buffer, format="JPEG", quality=calidad, optimize=True)
    return buffer.getvalue()

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

# --- ENVIADOR DE CORREOS CONFIGURABLE (AUDITADO) ---
def despachar_correo(config_section, destinatario, asunto, cuerpo_texto):
    try:
        if config_section not in st.secrets:
            st.error(f"Falta la seccion [{config_section}] en Secrets.")
            return False

        if not validar_email(destinatario):
            st.error(f"El destinatario '{destinatario}' no es una dirección de email válida.")
            return False
            
        smtp_user = st.secrets[config_section]["SMTP_USER"]
        smtp_password = st.secrets[config_section]["SMTP_PASSWORD"]
        
        # Limpieza estricta de la dirección de destino para evitar fallos de sintaxis SMTP
        destinatario_limpio = str(destinatario).strip().lower()
        
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = destinatario_limpio
        msg['Subject'] = asunto
        msg.attach(MIMEText(cuerpo_texto, 'plain', 'utf-8'))
        
        # Conexión directa y cifrada mediante SSL en puerto 465
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15)
        server.login(smtp_user, smtp_password)
        
        # Enviamos y recolectamos posibles rechazos inmediatos del servidor
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
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
                        <path d="M12.004 2c-5.51 0-9.99 4.49-9.99 10 0 1.91.54 3.7 1.48 5.24l-1.4 5.1 5.23-1.37c1.48.81 3.16 1.27 4.93 1.27 5.51 0 10-4.49 10-10s-4.49-10-10-10zm4.87 14.15c-.21.58-1.22 1.13-1.68 1.19-.46.06-.91.08-2.84-.68-2.47-.97-4.05-3.48-4.17-3.64-.12-.17-1.04-1.38-1.04-2.63 0-1.25.65-1.87.88-2.12.23-.25.5-.31.67-.31.17 0 .33.01.48.01.16.01.37-.06.57.42.21.5.73 1.77.79 1.9.06.12.1.27.02.44-.08.16-.12.27-.25.42-.12.15-.26.33-.37.45-.12.12-.25.26-.11.5.15.24.66 1.09 1.42 1.76.98.86 1.8 1.13 2.06 1.25.25.13.4.1.55-.07.15-.17.65-.75.82-.1.17.15.34.42.92.71.58.29 3.46 1.71 3.54 1.75.08.04.13.19.05.42z"/>
                    </svg>
                    Contactanos
                </a>
                """, unsafe_allow_html=True)
            
    else:
        fila1_col1, fila1_col2 = st.columns(2)
        with fila1_col1:
            cliente = st.text_input("Nombre / Razón Social", placeholder="Ej: Juan Pérez o Empresa S.A.").upper()
        with fila1_col2:
            serial = st.text_input("Serial (SN - ASA)", placeholder="Ubicado en la etiqueta")

        fila2_col1, fila2_col2 = st.columns(2)
        with fila2_col1:
            producto = st.text_input("Producto", placeholder="Ingrese nombre de producto")
        with fila2_col2:
            fecha_compra = st.date_input("Fecha de Compra", max_value=date.today(), format="DD/MM/YYYY")
            st.markdown("<div style='color: #888888; font-size: 14px; margin-top: -10px; margin-bottom: 15px;'># Dejar fecha actual si no recuerda</div>", unsafe_allow_html=True)

        motivo = st.selectbox("Motivo del trámite", options=["RMA", "Devolución"])
        descripcion = st.text_area("Descripción de la falla", placeholder="Especifique el error / falla detalladamente...")

        st.markdown(
            "<div style='color:#888888; font-size:13px; margin-top:-8px; margin-bottom:4px;'>📎 Adjuntar fotos (opcional, máx. 2 - formato JPG o PNG)</div>",
            unsafe_allow_html=True
        )
        archivos_fotos = st.file_uploader(
            "Adjuntar fotos",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True,
            label_visibility="collapsed"
        )

        if archivos_fotos and len(archivos_fotos) > 2:
            st.warning("⚠️ Solo se pueden adjuntar hasta 2 fotos. Se usarán las primeras 2 seleccionadas.")
            archivos_fotos = archivos_fotos[:2]

        if archivos_fotos:
            cols_preview = st.columns(len(archivos_fotos))
            for col_p, archivo_p in zip(cols_preview, archivos_fotos):
                with col_p:
                    st.image(archivo_p, width=120)

        st.markdown("---")
        st.markdown("### Método de Contacto")
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
            contacto_lleno = False
            if opcion_contacto == "WhatsApp" and telefono_val.strip() != "":
                contacto_lleno = True
            elif opcion_contacto == "Correo Electrónico" and email_val.strip() != "":
                contacto_lleno = True
            
            if not cliente or not producto or not serial or not contacto_lleno:
                st.error("Por favor, complete todos los campos obligatorios para procesar la solicitud.")
            else:
                try:
                    st.session_state.resumen_rma = {
                        "cliente": cliente,
                        "producto": producto,
                        "serial": serial,
                        "falla": descripcion
                    }

                    # --- Subir las fotos adjuntas a Drive (si las hay) ---
                    foto1_id = ""
                    foto2_id = ""
                    if archivos_fotos:
                        for idx, archivo_f in enumerate(archivos_fotos[:2]):
                            bytes_img = preparar_imagen_para_drive(archivo_f)
                            if bytes_img is None:
                                st.warning(f"⚠️ La foto {idx + 1} no pudo procesarse y no fue adjuntada.")
                                continue
                            nombre_archivo = f"{(serial or 'SN').strip()}_{idx + 1}_{int(time.time())}.jpg"
                            file_id = subir_foto_a_drive(bytes_img, nombre_archivo)
                            if file_id:
                                if idx == 0:
                                    foto1_id = file_id
                                else:
                                    foto2_id = file_id
                            else:
                                st.warning(f"⚠️ No se pudo subir la foto {idx + 1} a Drive.")

                    nuevo_registro = {
                        "Cliente": cliente,
                        "Producto": producto,
                        "Serial": serial,
                        "Compra": str(fecha_compra),
                        "Motivo del trámite": motivo, 
                        "Falla": descripcion,        
                        "diagnostico": "",           
                        "Telefono": telefono_val,      
                        "Email": email_val.strip().lower() if opcion_contacto == "Correo Electrónico" else "",            
                        "Estado del RMA": "PENDIENTE",
                        "Ingreso": str(date.today()),
                        "Foto1": foto1_id,
                        "Foto2": foto2_id
                    }
                    
                    # 1. Guardar en Google Sheets
                    if not create_record(nuevo_registro):
                        st.error("Error al guardar en Google Sheets")
                        st.stop()
                    
                    # --- 2. AUTOMATIZACIONES DE CORREO INDEPENDIENTES ---
                    destinatario_cliente = email_val.strip().lower()
                    
                    if opcion_contacto == "WhatsApp":
                        # NUEVA FUNCIÓN AGREGADA: Estructura solicitada enviada desde EMAIL_INTERNO a federico@altavistasa.com.ar
                        asunto_ws = "Caso creado - Mensaje para cliente"
                        cuerpo_ws = (
                            f"SOLICITUD \xad - MENSAJE PARA CLIENTE\n"
                            f"wa.me/{telefono_val.strip()}\n"
                            f"---------------------------------------------------------------------------------------------------------------------------\n"
                            f"Has recibido una\n"
                            f"nueva solicitud de {motivo}. \n"
                            f"Revisa los datos en\n"
                            f"Panel RMA y acepta el caso si corresponde. \n"
                            f"Contacto cliente:\n"
                            f"{nuevo_registro['Email']} \n"
                            f" \n"
                            f"Mensaje para el\n"
                            f"cliente: \n"
                            f"asunto: \n"
                            f"ALTAVISTA SA -\n"
                            f"Solicitud {motivo} cargada con éxito. \n"
                            f"cuerpo del correo: \n"
                            f"¡Su solicitud para\n"
                            f"RMA\xad\xad ha sido cargada con éxito! \n"
                            f"---------------------------------------------------------------------------------------------------------------------------\n"
                            f"Producto:\n"
                            f"{producto} \n"
                            f"Serial: {serial} \n"
                            f"Falla: {descripcion} \n"
                            f"---------------------------------------------------------------------------------------------------------------------------\n"
                            f"En breve le\n"
                            f"asignaremos su número de RMA por este mismo canal. \n"
                            f"---------------------------------------------------------------------------------------------------------------------------\n"
                            f"Recuerde que nos\n"
                            f"puede contactar en: \n"
                            f"WhatsApp:\n"
                            f"3433002458 \n"
                            f"Email:\n"
                            f"federico@altavistasa.com.ar \n"
                            f" \n"
                            f"También puede\n"
                            f"consultar sus casos pendientes en el siguiente enlace: \n"
                            f"https://rma-altavista.streamlit.app/\n"
                        )
                        
                        ok_interno = despachar_correo(
                            config_section="EMAIL_INTERNO",
                            destinatario="federico@altavistasa.com.ar",
                            asunto=asunto_ws,
                            cuerpo_texto=cuerpo_ws
                        )
                        
                    else:
                        # FLUJO TRADICIONAL: Envío de correos por separado al elegir Correo Electrónico
                        contacto_interno_texto = destinatario_cliente
                        asunto_interno = f"Solicitud {motivo} - Cliente: {cliente} - Producto: {producto}"
                        cuerpo_interno = (
                            f"Has recibido una nueva solicitud de {motivo}.\n"
                            f"Revisa los datos en Panel RMA y acepta el caso si corresponde.\n"
                            f"Contacto cliente: {contacto_interno_texto}"
                        )
                        
                        ok_interno = despachar_correo(
                            config_section="EMAIL_INTERNO",
                            destinatario="federico@altavistasa.com.ar",
                            asunto=asunto_interno,
                            cuerpo_texto=cuerpo_interno
                        )
                        
                        # MENSAJE PARA EL CLIENTE (Solo si seleccionó Correo)
                        if ok_interno and destinatario_cliente != "":
                            asunto_cliente = f"ALTAVISTA SA - Solicitud {motivo} cargada con éxito."
                            cuerpo_cliente = (
                                f"¡Su solicitud para RMA ha sido cargada con éxito!\n"
                                f"---------------------------------------------------------------------------------------------------------------------------\n"
                                f"Producto: {producto}\n"
                                f"Serial: {serial}\n"
                                f"Falla: {descripcion}\n"
                                f"---------------------------------------------------------------------------------------------------------------------------\n"
                                f"En breve le asignaremos su número de RMA por este mismo canal.\n"
                                f"---------------------------------------------------------------------------------------------------------------------------\n"
                                f"Recuerde que nos puede contactar en:\n"
                                f"WhatsApp: 3433002458\n"
                                f"Email: federico@altavistasa.com.ar\n"
                                f"\n"
                                f"También puede consultar sus casos pendientes en el siguiente enlace:\n"
                                f"https://rma-altavista.streamlit.app/"
                            )
                            
                            despachar_correo(
                                config_section="EMAIL_CLIENTE",
                                destinatario=destinatario_cliente,
                                asunto=asunto_cliente,
                                cuerpo_texto=cuerpo_cliente
                            )
                    
                    # Evaluamos los estados de forma separada para no bloquear la experiencia de usuario
                    if ok_interno:
                        st.session_state.enviado = True
                        st.rerun()
                    else:
                        st.error("⚠️ No se pudo procesar la alerta de correo interno. Comprobá las credenciales en los Secrets.")
                    
                except Exception as e:
                    st.error(f"Error al procesar en Google Sheets: {e}")
