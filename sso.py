"""
sso.py — Módulo de Single Sign-On entre apps Streamlit (HMAC-SHA256)

Configuración requerida en secrets.toml de AMBAS apps:
    [SSO]
    SECRET = "clave-secreta-larga-y-aleatoria"
    TTL    = 300   # segundos de validez del token (default: 300 = 5 min)

Uso en app emisora (admin_panel):
    from sso import generar_token
    token = generar_token(st.session_state.usuario, st.session_state.rol)
    url   = f"https://panelproveedores.streamlit.app/?sso={token}"

Uso en app receptora (app.py):
    from sso import auto_login_sso
    auto_login_sso()   # llamar ANTES del bloque de login manual
"""

import base64
import hashlib
import hmac
import time

import streamlit as st


# ── Constantes internas ───────────────────────────────────────────
_SEP = "|"   # separador interno (no puede aparecer en usuario/rol)


def _get_secret() -> str:
    try:
        return st.secrets["SSO"]["SECRET"]
    except Exception:
        raise RuntimeError(
            "Falta [SSO] SECRET en secrets.toml. "
            "Agregá la sección [SSO] con SECRET y TTL en ambas apps."
        )


def _get_ttl() -> int:
    try:
        return int(st.secrets["SSO"].get("TTL", 300))
    except Exception:
        return 300


# ── Generación de token ───────────────────────────────────────────

def generar_token(usuario: str, rol: str) -> str:
    """
    Genera un token SSO firmado con HMAC-SHA256.
    El token es URL-safe base64 y caduca después de TTL segundos.
    """
    secret = _get_secret()
    timestamp = str(int(time.time()))
    # Payload: usuario|rol|timestamp  (| no aparece en nombres normales)
    payload = _SEP.join([usuario.strip(), rol.strip(), timestamp])
    firma = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}{_SEP}{firma}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


# ── Validación de token ───────────────────────────────────────────

def validar_token(token: str) -> tuple[str | None, str | None]:
    """
    Valida un token SSO.

    Retorna (usuario, rol) si el token es auténtico y no expiró.
    Retorna (None, None) en cualquier caso de fallo (firma inválida,
    expirado, formato incorrecto, secret no configurado).
    """
    try:
        secret = _get_secret()
        ttl = _get_ttl()

        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        # Separar firma del payload (último campo)
        idx = decoded.rfind(_SEP)
        if idx == -1:
            return None, None

        payload = decoded[:idx]
        firma_recibida = decoded[idx + len(_SEP):]

        # Verificar firma con compare_digest (protege contra timing attacks)
        firma_esperada = hmac.new(
            secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(firma_recibida, firma_esperada):
            return None, None

        # Extraer campos del payload
        partes = payload.split(_SEP)
        if len(partes) != 3:
            return None, None

        usuario, rol, timestamp_str = partes

        # Verificar expiración
        if int(time.time()) - int(timestamp_str) > ttl:
            return None, None

        return usuario, rol

    except Exception:
        return None, None


# ── Helper de auto-login para app receptora ───────────────────────

def auto_login_sso() -> None:
    """
    Intenta hacer login automático desde el parámetro ?sso= de la URL.
    Si el token es válido, setea el session_state y limpia la URL.
    Llamar ANTES del bloque de login manual en app.py.
    """
    if st.session_state.get("autenticado"):
        return  # ya logueado, nada que hacer

    params = st.query_params
    token = params.get("sso", "")
    if not token:
        return

    usuario, rol = validar_token(token)
    if usuario:
        st.session_state.autenticado = True
        st.session_state.usuario = usuario
        st.session_state.rol = rol
        st.query_params.clear()   # eliminar token de la URL por seguridad
        st.rerun()
    else:
        # Token inválido o expirado — limpiar URL silenciosamente
        st.query_params.clear()
