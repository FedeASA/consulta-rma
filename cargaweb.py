import streamlit as st
import urllib.parse
from datetime import datetime
from sheets_operations import get_all_records
from utils import es_verdadero, formatear_fecha

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

def _tiene_valor(v):
    return bool(v) and str(v).strip() not in ["None", "none", "nan", "NaN", ""]

def historial_html(record):
    """Línea de tiempo del caso: Solicitud cargada → Aceptado → Producto recibido → Finalizado."""
    aceptado   = es_verdadero(record.get('Aceptado'))
    recibido   = es_verdadero(record.get('Recibido')) or _tiene_valor(record.get('FechaRecibido'))
    finalizado = es_verdadero(record.get('Finalizado'))

    pasos = [
        ("📝", "Solicitud cargada",
         True, formatear_fecha_cliente(record.get('Ingreso')) if _tiene_valor(record.get('Ingreso')) else ""),
        ("✅", "Caso aceptado",
         aceptado, f"N° {record.get('autonumero')}" if aceptado and _tiene_valor(record.get('autonumero')) else ""),
        ("📦", "Producto recibido",
         recibido, formatear_fecha_cliente(record.get('FechaRecibido')) if _tiene_valor(record.get('FechaRecibido')) else ""),
        ("🏁", "Caso finalizado",
         finalizado, formatear_fecha_cliente(record.get('Resolucion')) if finalizado and _tiene_valor(record.get('Resolucion')) else ""),
    ]
    celdas = []
    for icono, titulo, hecho, detalle in pasos:
        color = "#28a745" if hecho else "#8a8a8a"
        estado = detalle if (hecho and detalle) else ("Listo" if hecho else "Pendiente")
        celdas.append(
            f"<div style='flex:1;min-width:110px;text-align:center;padding:8px 4px;"
            f"border-top:4px solid {color};opacity:{1 if hecho else 0.6};'>"
            f"<div style='font-size:20px;line-height:1.2;'>{icono}</div>"
            f"<div style='font-size:12px;font-weight:700;'>{titulo}</div>"
            f"<div style='font-size:12px;color:{color};font-weight:600;'>{estado}</div>"
            f"</div>"
        )
    return ("<div style='display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 12px 0;'>"
            + "".join(celdas) + "</div>")

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
            # Los tickets anulados desde el panel no se muestran al cliente
            if es_verdadero(record.get('Anulado')):
                continue
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
                
                es_finalizado = es_verdadero(record.get('Finalizado'))
                
                if es_finalizado:
                    titulo_ficha = f"Cliente: {record.get('Cliente', 'S/D')} - RMA: {record.get('autonumero', 'S/D')} | [CASO FINALIZADO]"
                else:
                    titulo_ficha = f"Cliente: {record.get('Cliente', 'S/D')} - RMA: {record.get('autonumero', 'S/D')} | [EN PROCESO]"
                
                debe_expandir = True
                if len(resultados_ordenados) > 2 and index > 0:
                    debe_expandir = False
                
                with st.expander(titulo_ficha, expanded=debe_expandir):
                    # Historial del caso con sus fechas (carga, aceptación, recepción, resolución)
                    st.markdown(historial_html(record), unsafe_allow_html=True)

                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Producto:** {record.get('Producto', 'N/A')}")
                        st.markdown(f"**Serial:** {record.get('Serial', 'N/A')}")
                        if es_fuera_garantia:
                            st.markdown(f"**Compra:** :red[{fecha_compra}]")
                        else:
                            st.markdown(f"**Compra:** {fecha_compra}")
                    
                    with col2:
                        st.markdown(f"**Estado del RMA:** {record.get('Estado del RMA', 'N/A')}")
                        
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
