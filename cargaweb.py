import streamlit as st
from pyairtable import Api
import urllib.parse
from datetime import datetime

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="RMA ALTAVISTA SA", layout="centered")

# --- CSS PARA ELIMINAR EL CARTEL "PRESS ENTER TO APPLY" ---
st.markdown("""
    <style>
        /* Oculta la leyenda de 'Press Enter to apply' en los inputs de texto */
        div[data-testid="stTextInput"] aria-instructions, 
        div[data-testid="stTextInput"] div[data-testid="InputInstructions"] {
            display: none !important;
        }
    </style>
    """, unsafe_allow_html=True)

# --- CREDENCIALES SEGURAS (SECRETS) ---
try:
    AIRTABLE_TOKEN = st.secrets["AIRTABLE_TOKEN"]
    BASE_ID = st.secrets["BASE_ID"]
    TABLE_NAME = f"{st.secrets['TABLE_NAME']}"
except Exception:
    st.error("Error: No se encontraron las credenciales en los Secrets de Streamlit.")
    st.stop()

api = Api(AIRTABLE_TOKEN)
table = api.table(BASE_ID, TABLE_NAME)

# --- FUNCIONES DE APOYO ---
def formatear_fecha_cliente(fecha_raw):
    """Convierte fechas YYYY-MM-DD de Airtable a formato legible DD/MM/YYYY"""
    if not fecha_raw or str(fecha_raw).strip() in ["None", "none", "nan", "NaN", ""]: 
        return "N/A"
    
    fecha_str = str(fecha_raw).replace('-', '/').strip()
    for formato in ['%Y/%m/%d', '%Y-%m-%d', '%d/%m/%Y']:
        try:
            dt = datetime.strptime(fecha_str, formato)
            return dt.strftime('%d/%m/%Y')
        except ValueError:
            continue
    return str(fecha_raw)

def obtener_fecha_ordenamiento(record):
    """Extrae la fecha de resolución para usarla como clave de ordenamiento"""
    f = record.get('fields', {})
    fecha_raw = f.get('Resolucion', '')
    if not fecha_raw or str(fecha_raw).strip() in ["None", "none", "nan", "NaN", ""]:
        return datetime.min # Si no tiene fecha, lo manda al final de los finalizados
    
    fecha_str = str(fecha_raw).replace('-', '/').strip()
    for formato in ['%Y/%m/%d', '%Y-%m-%d', '%d/%m/%Y']:
        try:
            return datetime.strptime(fecha_str, formato)
        except ValueError:
            continue
    return datetime.min

# --- CABECERA ---
st.markdown("<h1 style='text-align: center;'>RMA ALTAVISTA SA</h1>", unsafe_allow_html=True)

# --- BARRA DE BÚSQUEDA ---
entrada_usuario = st.text_input("Ingrese Código de Cliente o Número de Caso:", value="").strip()
busqueda = entrada_usuario.upper() 

if busqueda:
    try:
        condicion_cliente = f"{{Cliente}} = '{busqueda}'"
        if busqueda.isdigit():
            # Cambio: se busca por campo {autonumero} en lugar de {Numero RMA}
            condicion_rma = f"{{autonumero}} = {busqueda}"
            formula = f"OR({condicion_cliente}, {condicion_rma})"
        else:
            formula = condicion_cliente
        
        results = table.all(formula=formula)
        
        if results:
            # --- LÓGICA DE CLASIFICACIÓN Y ORDENAMIENTO DE CASOS ---
            en_proceso = []
            finalizados = []
            
            for record in results:
                f = record.get('fields', {})
                es_aceptado = f.get('Aceptado') in [True, 1, "True", "true"]
                es_finalizado = f.get('Finalizado') in [True, 1, "True", "true"]
                
                if es_aceptado and not es_finalizado:
                    en_proceso.append(record)
                elif es_aceptado and es_finalizado:
                    finalizados.append(record)
                else:
                    en_proceso.append(record)
            
            finalizados.sort(key=obtener_fecha_ordenamiento, reverse=True)
            resultados_ordenados = en_proceso + finalizados
            
            # --- INTERFAZ GRÁFICA DE CONTACTO ---
            numero_tel = "5493433002458"
            mensaje_wa = urllib.parse.quote(f"Hola Altavista SA, tengo una consulta sobre el RMA/Cliente: {busqueda}")
            link_wa = f"https://wa.me/{numero_tel}?text={mensaje_wa}"
            
            col_msg, col_ws = st.columns([2, 1])
            with col_msg:
                st.success(f"Se encontraron {len(resultados_ordenados)} coincidencia(s):")
            with col_ws:
                st.markdown(f"""
                <a href="{link_wa}" target="_blank" style="text-decoration: none;">
                    <div style="background-color: #25D366; color: white; padding: 10px; border-radius: 8px; text-align: center; font-weight: bold; display: flex; align-items: center; justify-content: center; gap: 8px;">
                        <img src="https://upload.wikimedia.org/wikipedia/commons/6/6b/WhatsApp.svg" width="18">
                        Contactarnos
                    </div>
                </a>
                """, unsafe_allow_html=True)

            # --- RENDERS DE LAS FICHAS ---
            for index, record in enumerate(resultados_ordenados):
                f = record['fields']
                estado_valor = str(f.get('Estado del RMA', '')).strip().upper()
                diagnostico_texto = f.get('diagnostico', 'Sin diagnóstico registrado.')
                es_fuera_garantia = "FUERA DE GARANTIA" in estado_valor
                
                fecha_compra = formatear_fecha_cliente(f.get('Compra'))
                fecha_resolucion = formatear_fecha_cliente(f.get('Resolucion'))
                
                es_finalizado = f.get('Finalizado') in [True, 1, "True", "true"]
                
                # Cambio: se muestra el campo {autonumero} en el título
                nro_caso = f.get('autonumero', 'S/D')
                if es_finalizado:
                    titulo_ficha = f"Cliente: {f.get('Cliente', 'S/D')} - Caso: {nro_caso} | [CASO FINALIZADO]"
                else:
                    titulo_ficha = f"Cliente: {f.get('Cliente', 'S/D')} - Caso: {nro_caso} | [EN PROCESO]"
                
                debe_expandir = True
                if len(resultados_ordenados) > 2 and index > 0:
                    debe_expandir = False
                
                with st.expander(titulo_ficha, expanded=debe_expandir):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Producto:** {f.get('Producto', 'N/A')}")
                        st.markdown(f"**Serial:** {f.get('Serial', 'N/A')}")
                        if es_fuera_garantia:
                            st.markdown(f"**Compra:** :red[{fecha_compra}]")
                        else:
                            st.markdown(f"**Compra:** {fecha_compra}")
                        st.markdown(f"**Ingreso:** {f.get('Ingreso', 'N/A')}")
                    
                    with col2:
                        aceptado_icon = "✅" if f.get('Aceptado') else "❌"
                        st.markdown(f"**Aceptado:** {aceptado_icon}")
                        st.markdown(f"**Estado del RMA:** {f.get('Estado del RMA', 'N/A')}")
                        
                        if es_finalizado:
                            st.markdown(f"**Resolución:** :red[{fecha_resolucion}]")
                        else:
                            st.markdown(f"**Resolución:** {fecha_resolucion}")
                        
                        comentario_texto = f.get('comentario', '')
                        if comentario_texto and str(comentario_texto).strip() not in ["None", "none", "nan", "NaN", ""]:
                            st.markdown(f"**Comentario:** {comentario_texto}")
                    
                    st.markdown("---")
                    st.markdown(f"**Diagnóstico:**")
                    if es_fuera_garantia:
                        st.error(diagnostico_texto)
                    elif "NO FALLO" in estado_valor:
                        st.warning(diagnostico_texto)
                    else:
                        st.info(diagnostico_texto)
        else:
            st.warning(f"No se encontraron resultados para '{busqueda}'.")
            
    except Exception as e:
        st.error(f"Error en la consulta: {e}")
else:
    st.info("Sistema de consulta de RMA. Ingrese sus datos para comenzar.")
