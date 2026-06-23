import streamlit as st
import urllib.parse
from datetime import datetime
from sheets_operations import get_all_records
from utils import es_verdadero, formatear_fecha

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="RM3436220593	
3436220593	
3436220593	
3436987265	
	unclickweb@gmail.com
5493434298869	
3426156882	
3413422310	
3413422310	
3415595948	
3416611910	
3434726899	
3434726899	
3434726899	
3434658663	
3416611910	
3416611910	
3413422310	
543434693989	
543434693989	
3435358775	
3434405553	
3425215684	
CLAA	
CLAA	
CLAA	
CLAA	
CLAA	
	pcservicepamovil@gmail.com
3435613496	
3424632550	
3435093528	
3413422310	
3425198383	
3413422310	
3425198383	
3438407549	
3438407549	
3436220593	
3482 639224	
3482639224	
3482639224	
342-6399169	
3413422310	
3434658663	
5493425475600	
3482639224	
3425024085	
3425024085	
3413422310	
	pcservicepamovil@gmail.comA ALTAVISTA SA", layout="centered")

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

# --- FUNCIONES DE APOYO ---
def formatear_fecha_cliente(fecha_raw):
    """Convierte valores de fecha a formato legible DD/MM/YYYY"""
    return formatear_fecha(fecha_raw)

def obtener_fecha_ordenamiento(record):
    """Extrae la fecha de resolución para usarla como clave de ordenamiento"""
    fecha_raw = record.get('Resolucion', '')
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
entrada_usuario = st.text_input("Ingrese Código de Cliente o Número de RMA:", value="").strip()
busqueda = entrada_usuario.upper() 

if busqueda:
    try:
        # Obtener todos los registros
        records = get_all_records()
        
        if not records:
            st.warning("No hay registros en la base de datos.")
            st.stop()
        
        # Filtrar registros que coincidan con Cliente o autonumero
        results = []
        for record in records:
            cliente = str(record.get('Cliente', '')).upper()
            numero_rma = str(record.get('autonumero', '')).upper()
            
            if busqueda in cliente or busqueda == numero_rma:
                results.append(record)
        
        if results:
            # --- LÓGICA DE CLASIFICACIÓN Y ORDENAMIENTO DE CASOS ---
            en_proceso = []
            finalizados = []
            
            for record in results:
                es_aceptado = es_verdadero(record.get('Aceptado'))
                es_finalizado = es_verdadero(record.get('Finalizado'))
                
                if es_aceptado and not es_finalizado:
                    en_proceso.append(record)
                elif es_aceptado and es_finalizado:
                    finalizados.append(record)
                else:
                    en_proceso.append(record)
            
            # Ordenar los finalizados por fecha de 'Resolucion' (Más nuevos primero -> reverse=True)
            finalizados.sort(key=obtener_fecha_ordenamiento, reverse=True)
            
            # Combinamos: Primero En Proceso, abajo los Finalizados ordenados cronológicamente
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
                estado_valor = str(record.get('Estado del RMA', '')).strip().upper()
                diagnostico_texto = record.get('diagnostico', 'Sin diagnóstico registrado.')
                es_fuera_garantia = "FUERA DE GARANTIA" in estado_valor
                
                # Formatear las fechas a DD/MM/YYYY
                fecha_compra = formatear_fecha_cliente(record.get('Compra'))
                fecha_resolucion = formatear_fecha_cliente(record.get('Resolucion'))
                
                es_finalizado = record.get('Finalizado') in [True, 1, "True", "true", "SI", "Sí"]
                
                if es_finalizado:
                    titulo_ficha = f"Cliente: {record.get('Cliente', 'S/D')} - RMA: {record.get('autonumero', 'S/D')} | [CASO FINALIZADO]"
                else:
                    titulo_ficha = f"Cliente: {record.get('Cliente', 'S/D')} - RMA: {record.get('autonumero', 'S/D')} | [EN PROCESO]"
                
                debe_expandir = True
                if len(resultados_ordenados) > 2 and index > 0:
                    debe_expandir = False
                
                with st.expander(titulo_ficha, expanded=debe_expandir):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Producto:** {record.get('Producto', 'N/A')}")
                        st.markdown(f"**Serial:** {record.get('Serial', 'N/A')}")
                        if es_fuera_garantia:
                            st.markdown(f"**Compra:** :red[{fecha_compra}]")
                        else:
                            st.markdown(f"**Compra:** {fecha_compra}")
                        st.markdown(f"**Ingreso:** {record.get('Ingreso', 'N/A')}")
                    
                    with col2:
                        aceptado_icon = "✅" if record.get('Aceptado') else "❌"
                        st.markdown(f"**Aceptado:** {aceptado_icon}")
                        st.markdown(f"**Estado del RMA:** {record.get('Estado del RMA', 'N/A')}")
                        
                        if es_finalizado:
                            st.markdown(f"**Resolución:** :red[{fecha_resolucion}]")
                        else:
                            st.markdown(f"**Resolución:** {fecha_resolucion}")
                        
                        comentario_texto = record.get('comentario', '')
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
