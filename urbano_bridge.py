"""
urbano_bridge.py
================
Servidor puente local que automatiza Urbano SQL via pywinauto.
Corre en la PC local junto al admin panel (o en la misma red).

Instalación:
    pip install fastapi uvicorn pywinauto

Uso:
    python urbano_bridge.py
    → Escucha en http://localhost:8765
"""

import time
import re
import subprocess
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
URBANO_EXE = r"C:\Program Files (x86)\Acc. Informática\Urbano"   # ← Ajustá esta ruta al ejecutable real
URBANO_WINDOW_TITLE = "Software Urbano"
HISTORIAL_WINDOW_TITLE = "Historial por Nº de Serie"
ESPERA_CARGA = 1.5   # segundos de espera tras abrir ventana
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Urbano Bridge", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_urbano_app():
    """Conecta a la instancia de Urbano ya abierta, o la lanza si no está."""
    try:
        from pywinauto import Application, findwindows
        # Intentar conectarse a la ventana ya abierta
        try:
            app_win = Application(backend="win32").connect(title_re=f".*{URBANO_WINDOW_TITLE}.*", timeout=3)
            return app_win
        except Exception:
            pass

        # Si no está abierta, intentar lanzarla
        if os.path.exists(URBANO_EXE):
            subprocess.Popen([URBANO_EXE])
            time.sleep(4)
            app_win = Application(backend="win32").connect(title_re=f".*{URBANO_WINDOW_TITLE}.*", timeout=10)
            return app_win
        else:
            raise HTTPException(status_code=503, detail=f"Urbano no está abierto y no se encontró el ejecutable en: {URBANO_EXE}")

    except ImportError:
        raise HTTPException(status_code=500, detail="pywinauto no está instalado. Ejecutá: pip install pywinauto")


def parsear_cliente(clie_prov_text: str):
    """
    Separa código y nombre del cliente desde el texto de la grilla.
    Ejemplo: 'I1054 FERRARIS LUCIANO' → ('I1054', 'FERRARIS LUCIANO')
    """
    texto = str(clie_prov_text).strip()
    # Código: primer token alfanumérico (puede tener letras como I, C, etc.)
    match = re.match(r'^([A-Z]?\d+)\s+(.+)$', texto)
    if match:
        return match.group(1), match.group(2).title()
    return texto, ""


def parsear_proveedor(clie_prov_text: str):
    """
    Separa código y nombre del proveedor.
    Ejemplo: '433-NETMAK S.R.L' → ('433', 'NETMAK S.R.L')
    """
    texto = str(clie_prov_text).strip()
    match = re.match(r'^(\d+)-(.+)$', texto)
    if match:
        return match.group(1), match.group(2).strip().title()
    return texto, ""


@app.get("/consultar/{serial}")
def consultar_serial(serial: str):
    """
    Consulta el historial de un número de serie en Urbano.
    
    Retorna:
    {
        "serial": "ASA1032530",
        "producto_sku": "79811",
        "producto_nombre": "CABLE NETMAK PATCH CORD 2MTR NM-C04-2",
        "cliente_codigo": "I1054",
        "cliente_nombre": "Ferraris Luciano",
        "fecha_compra": "28-04-2026",
        "proveedor_codigo": "433",
        "proveedor_nombre": "Netmak S.R.L",
        "filas_raw": [...]
    }
    """
    from pywinauto.keyboard import send_keys

    serial = serial.strip().upper()
    if not serial:
        raise HTTPException(status_code=400, detail="Serial vacío")

    urbano = get_urbano_app()
    ventana_principal = urbano.window(title_re=f".*{URBANO_WINDOW_TITLE}.*")

    # ── Hacer clic en "Seguimiento por Nº de Serie" ───────────────────────────
    try:
        # Buscar el botón/item de la lista por texto
        ventana_principal.set_focus()
        time.sleep(0.3)

        # El botón está en el panel izquierdo como un ListBox o similar
        # Intentamos por texto
        try:
            btn = ventana_principal.child_window(title="Seguimiento por Nº de Serie", control_type="ListItem")
            btn.click_input()
        except Exception:
            # Alternativa: doble click en el item de lista
            btn = ventana_principal.child_window(title_re=".*Seguimiento.*Serie.*")
            btn.double_click_input()

        time.sleep(ESPERA_CARGA)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo abrir 'Seguimiento por Nº de Serie': {str(e)}")

    # ── Operar la ventana Historial ───────────────────────────────────────────
    try:
        hist = urbano.window(title=HISTORIAL_WINDOW_TITLE)
        hist.set_focus()
        time.sleep(0.3)

        # Limpiar y escribir el serial en el campo "Nº de Serie:"
        campo_serial = hist.child_window(class_name="TEdit", found_index=0)
        campo_serial.set_focus()
        campo_serial.set_text("")
        campo_serial.type_keys(serial, with_spaces=True)
        send_keys("{ENTER}")
        time.sleep(ESPERA_CARGA)

        # ── Leer campo Producto (TEdit o TDBEdit a la derecha del serial) ─────
        try:
            campo_producto = hist.child_window(class_name="TEdit", found_index=1)
            producto_completo = campo_producto.window_text().strip()
        except Exception:
            producto_completo = ""

        if not producto_completo:
            # El serial no existe en Urbano
            hist.child_window(title="Cerrar").click_input()
            return {
                "serial": serial,
                "encontrado": False,
                "mensaje": "Serial no encontrado en Urbano"
            }

        # Separar SKU y nombre del producto
        # Formato: "79811 - CABLE NETMAK PATCH CORD..."
        sku = ""
        nombre_producto = producto_completo
        match_prod = re.match(r'^(\d+)\s*[-–]\s*(.+)$', producto_completo)
        if match_prod:
            sku = match_prod.group(1)
            nombre_producto = match_prod.group(2).strip()

        # ── Leer la grilla (ListView/TDBGrid) ────────────────────────────────
        filas_data = []
        fecha_compra = ""
        cliente_codigo = ""
        cliente_nombre = ""
        proveedor_codigo = ""
        proveedor_nombre = ""

        try:
            # Intentar con ListView
            grilla = hist.child_window(class_name="TDBGrid")
            # Usar "Copiar Grilla" para obtener los datos de forma confiable
            btn_copiar = hist.child_window(title="Copiar Grilla")
            btn_copiar.click_input()
            time.sleep(0.5)

            # Leer del portapapeles
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            clipboard_text = root.clipboard_get()
            root.destroy()

            # Parsear TSV del portapapeles
            lineas = clipboard_text.strip().split('\n')
            if len(lineas) > 1:
                headers = [h.strip() for h in lineas[0].split('\t')]
                for linea in lineas[1:]:
                    valores = [v.strip() for v in linea.split('\t')]
                    if len(valores) >= len(headers):
                        fila = dict(zip(headers, valores))
                        filas_data.append(fila)

            # Extraer datos relevantes de las filas
            for fila in filas_data:
                operacion = str(fila.get('Operación', fila.get('Operacion', ''))).strip()
                clie_prov = str(fila.get('Clie / Prov.', fila.get('Clie/Prov', ''))).strip()
                fecha = str(fila.get('Fecha', '')).strip()

                # Factura de Venta → cliente y fecha de compra
                if 'VENTA' in operacion.upper() and 'FACTURA' in operacion.upper():
                    if not fecha_compra:
                        fecha_compra = fecha
                    if not cliente_codigo and clie_prov:
                        cliente_codigo, cliente_nombre = parsear_cliente(clie_prov)

                # Remito de Venta → también puede dar cliente
                elif 'VENTA' in operacion.upper() and 'REMITO' in operacion.upper():
                    if not cliente_codigo and clie_prov:
                        cliente_codigo, cliente_nombre = parsear_cliente(clie_prov)

                # Remito Compra → proveedor
                elif 'COMPRA' in operacion.upper():
                    if not proveedor_codigo and clie_prov:
                        proveedor_codigo, proveedor_nombre = parsear_proveedor(clie_prov)

        except Exception as e:
            # Si falla la grilla, devolvemos lo que pudimos leer
            filas_data = [{"error_grilla": str(e)}]

        # ── Cerrar ventana Historial ──────────────────────────────────────────
        try:
            hist.child_window(title="Cerrar").click_input()
        except Exception:
            hist.close()

        return {
            "serial": serial,
            "encontrado": True,
            "producto_sku": sku,
            "producto_nombre": nombre_producto,
            "producto_completo": producto_completo,
            "cliente_codigo": cliente_codigo,
            "cliente_nombre": cliente_nombre,
            "fecha_compra": fecha_compra,
            "proveedor_codigo": proveedor_codigo,
            "proveedor_nombre": proveedor_nombre,
            "filas_raw": filas_data
        }

    except Exception as e:
        # Intentar cerrar la ventana si quedó abierta
        try:
            urbano.window(title=HISTORIAL_WINDOW_TITLE).close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Error al operar Historial: {str(e)}")


@app.get("/ping")
def ping():
    """Health check — el admin panel lo usa para verificar que el puente está activo."""
    return {"status": "ok", "servicio": "Urbano Bridge v1.0"}


@app.get("/test-urbano")
def test_urbano():
    """Verifica si Urbano está abierto y accesible."""
    try:
        get_urbano_app()
        return {"urbano_activo": True}
    except Exception as e:
        return {"urbano_activo": False, "detalle": str(e)}


if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  URBANO BRIDGE - Servidor Puente Local")
    print("  Escuchando en: http://localhost:8765")
    print("  Endpoints:")
    print("    GET /ping                → health check")
    print("    GET /test-urbano         → verifica Urbano abierto")
    print("    GET /consultar/{serial}  → consulta un serial")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8765)
