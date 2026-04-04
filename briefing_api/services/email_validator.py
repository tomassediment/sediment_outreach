import re
from urllib.parse import urlparse
from typing import Optional

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')
IMAGE_EXTENSIONS = re.compile(r'\.(jpg|jpeg|png|gif|webp|svg|bmp|ico|pdf)', re.IGNORECASE)

PLACEHOLDER_DOMAINS = {
    'dominio.com', 'correo.com', 'address.com', 'empresa.com',
    'example.com', 'tudominio.com', 'correoelectronico.com',
    'mail.com', 'correo.co', 'midominio.com', 'yourdomain.com',
}

GENERIC_PERSONAL_DOMAINS = {
    'gmail.com', 'hotmail.com', 'outlook.com', 'yahoo.com',
    'yahoo.es', 'hotmail.es', 'icloud.com', 'live.com',
    'yahoo.co', 'live.com.co',
}


def is_valid_email(email: str) -> bool:
    email = email.strip()
    # Formato básico
    if not EMAIL_REGEX.match(email):
        return False
    # Imagen con @ en el nombre
    if IMAGE_EXTENSIONS.search(email):
        return False
    # URL-encoding basura
    if '%' in email or 'u00' in email.lower():
        return False
    domain = email.split('@')[1].lower()
    # Placeholder de template
    if domain in PLACEHOLDER_DOMAINS:
        return False
    return True


def extract_domain(web_url: str) -> Optional[str]:
    try:
        parsed = urlparse(web_url)
        host = parsed.netloc or parsed.path
        host = host.replace('www.', '').strip('/')
        return host if host else None
    except Exception:
        return None


def build_email_cascade(emails_sitio: Optional[str], email_fuente: Optional[str], web_url: Optional[str]) -> list[str]:
    """
    Construye la lista ordenada de emails a intentar para un lead.
    Orden: emails_sitio → email_fuente (si distinto) → patrones genéricos del dominio
    Filtra emails inválidos en cada paso.
    """
    cascade = []

    # 1. emails_sitio (campo principal)
    if emails_sitio:
        for raw in emails_sitio.split(';'):
            email = raw.strip()
            if is_valid_email(email) and email not in cascade:
                cascade.append(email)

    # 2. email_fuente si es distinto a los ya encontrados
    if email_fuente:
        email = email_fuente.strip()
        if is_valid_email(email) and email not in cascade:
            cascade.append(email)

    # 3. Patrones genéricos del dominio (si hay web_url)
    if web_url:
        domain = extract_domain(web_url)
        if domain:
            for prefix in ['info', 'contacto', 'ventas', 'comercial']:
                generic = f"{prefix}@{domain}"
                if generic not in cascade:
                    cascade.append(generic)

    return cascade


def next_email_in_cascade(cascade: list[str], email_fallido: str) -> Optional[str]:
    """
    Dado un email que hizo bounce_hard, devuelve el siguiente en el cascade.
    Retorna None si no hay más opciones.
    """
    try:
        idx = cascade.index(email_fallido)
        if idx + 1 < len(cascade):
            return cascade[idx + 1]
        return None
    except ValueError:
        # email_fallido no estaba en el cascade — no debería pasar
        return None
