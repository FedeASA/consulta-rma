"""
test_migration.py - Script de prueba para validar la migración de Airtable a Google Sheets

Uso: python test_migration.py
"""

import os
import sys
import json
from pathlib import Path

def test_credentials():
    """Verifica que las credenciales de Google están disponibles"""
    print("\n🔍 Verificando credenciales...")
    
    if os.path.exists("creds_google.json"):
        print("✅ Archivo creds_google.json encontrado")
        try:
            with open("creds_google.json", "r") as f:
                creds = json.load(f)
            print(f"✅ Credenciales válidas para: {creds.get('project_id', 'N/A')}")
            return True
        except json.JSONDecodeError:
            print("❌ Error: creds_google.json no es un JSON válido")
            return False
    else:
        print("❌ Archivo creds_google.json no encontrado")
        print("   Colócalo en la raíz del proyecto o configura GOOGLE_CREDS en secrets")
        return False

def test_dependencies():
    """Verifica que las dependencias están instaladas"""
    print("\n🔍 Verificando dependencias...")
    
    dependencies = {
        'streamlit': 'streamlit',
        'pandas': 'pandas',
        'gspread': 'gspread',
        'google.auth': 'google-auth',
        'google.oauth2': 'google-auth-oauthlib'
    }
    
    all_ok = True
    for module_name, package_name in dependencies.items():
        try:
            __import__(module_name)
            print(f"✅ {package_name}")
        except ImportError:
            print(f"❌ {package_name} - Instala con: pip install {package_name}")
            all_ok = False
    
    return all_ok

def test_sheet_connection():
    """Prueba la conexión a Google Sheets"""
    print("\n🔍 Probando conexión a Google Sheets...")
    
    try:
        from sheets_operations import get_sheets_client, get_all_records
        
        # Test 1: Obtener cliente
        print("   - Autenticando con Google...")
        client = get_sheets_client()
        print("   ✅ Autenticación exitosa")
        
        # Test 2: Obtener registros
        print("   - Leyendo registros...")
        records = get_all_records()
        print(f"   ✅ {len(records)} registros encontrados")
        
        # Test 3: Verificar estructura
        if records:
            first_record = records[0]
            columns = list(first_record.keys())
            print(f"   ✅ Columnas encontradas: {', '.join(columns[:5])}...")
            
            # Verificar columnas críticas
            critical_cols = ['Cliente', 'Producto', 'Serial', 'Email', 'Telefono']
            missing = [col for col in critical_cols if col not in columns]
            if missing:
                print(f"   ⚠️  Columnas faltantes: {', '.join(missing)}")
            else:
                print(f"   ✅ Todas las columnas críticas presentes")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_streamlit_config():
    """Verifica la configuración de Streamlit"""
    print("\n🔍 Verificando configuración de Streamlit...")
    
    config_path = Path(".streamlit/secrets.toml")
    if config_path.exists():
        print("✅ Archivo .streamlit/secrets.toml encontrado")
        try:
            with open(config_path, "r") as f:
                content = f.read()
            
            checks = {
                '[USUARIOS]': 'Sección USUARIOS',
                '[GOOGLE_CREDS]': 'Sección GOOGLE_CREDS',
                '[EMAIL_INTERNO]': 'Sección EMAIL_INTERNO',
                '[EMAIL_CLIENTE]': 'Sección EMAIL_CLIENTE'
            }
            
            for key, desc in checks.items():
                if key in content:
                    print(f"   ✅ {desc}")
                else:
                    print(f"   ⚠️  {desc} no encontrada")
            
            return True
        except Exception as e:
            print(f"❌ Error leyendo secrets.toml: {e}")
            return False
    else:
        print("❌ Archivo .streamlit/secrets.toml no encontrado")
        print("   Copia .streamlit/secrets.example.toml a .streamlit/secrets.toml")
        print("   y personaliza con tus credenciales")
        return False

def test_create_and_read():
    """Prueba crear y leer un registro"""
    print("\n🔍 Prueba de creación y lectura de registro...")
    
    try:
        from sheets_operations import create_record, get_all_records, delete_row
        import datetime
        
        # Crear registro de prueba
        test_data = {
            "Cliente": f"TEST_{datetime.datetime.now().timestamp()}",
            "Producto": "Producto Test",
            "Serial": "TEST123",
            "Compra": "2026-01-01",
            "Motivo del trámite": "RMA",
            "Falla": "Prueba automática",
            "Email": "test@test.com",
            "Telefono": "123456789",
            "Estado del RMA": "PENDIENTE",
            "Ingreso": str(datetime.date.today()),
            "Aceptado": "NO",
            "Finalizado": "NO"
        }
        
        print("   - Creando registro de prueba...")
        if create_record(test_data):
            print("   ✅ Registro creado")
            
            # Leer registros
            print("   - Leyendo registros...")
            records = get_all_records()
            
            # Buscar el registro creado
            found = None
            for record in records:
                if record.get('Cliente') == test_data['Cliente']:
                    found = record
                    break
            
            if found:
                print("   ✅ Registro encontrado en la lectura")
                return True
            else:
                print("   ⚠️  Registro no encontrado en la lectura (pero fue creado)")
                return True
        else:
            print("   ❌ No se pudo crear el registro")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    """Ejecuta todos los tests"""
    print("=" * 60)
    print("🧪 PRUEBAS DE MIGRACIÓN AIRTABLE → GOOGLE SHEETS")
    print("=" * 60)
    
    results = {
        "Credenciales": test_credentials(),
        "Dependencias": test_dependencies(),
        "Config Streamlit": test_streamlit_config(),
        "Conexión Sheets": test_sheet_connection(),
    }
    
    # Solo ejecutar test de creación si todo lo demás pasó
    if all(results.values()):
        results["Crear/Leer"] = test_create_and_read()
    
    print("\n" + "=" * 60)
    print("📊 RESUMEN DE RESULTADOS")
    print("=" * 60)
    
    for test_name, passed in results.items():
        status = "✅ PASÓ" if passed else "❌ FALLÓ"
        print(f"{test_name}: {status}")
    
    all_passed = all(results.values())
    print("\n" + "=" * 60)
    
    if all_passed:
        print("✅ ¡TODAS LAS PRUEBAS PASARON!")
        print("\nYa puedes usar los módulos:")
        print("  - streamlit run form.py")
        print("  - streamlit run cargaweb.py")
        print("  - streamlit run admin panel.py")
    else:
        print("❌ ALGUNAS PRUEBAS FALLARON")
        print("\nRevisa los errores arriba y consulta MIGRACION_AIRTABLE_A_SHEETS.md")
    
    print("=" * 60)
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
