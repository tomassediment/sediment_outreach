from typing import Optional
from database import fetch_one, fetch_all
from services.email_validator import build_email_cascade, next_email_in_cascade


def get_lead_cascade(lead_id: int) -> list[str]:
    """
    Construye el cascade completo de emails para un lead dado su ID.
    """
    lead = fetch_one(
        "SELECT emails_sitio, email_fuente, web_url FROM leads_brutos WHERE id = %s",
        (lead_id,)
    )
    if not lead:
        return []

    return build_email_cascade(
        emails_sitio=lead['emails_sitio'],
        email_fuente=lead['email_fuente'],
        web_url=lead['web_url'],
    )


def get_next_email(lead_id: int, email_fallido: str) -> tuple[Optional[str], str]:
    """
    Dado un lead y un email que hizo bounce_hard,
    devuelve (siguiente_email, razon).
    razon puede ser: "email_fuente", "patron_generico", "agotado"
    """
    cascade = get_lead_cascade(lead_id)

    if not cascade:
        return None, "agotado"

    siguiente = next_email_in_cascade(cascade, email_fallido)

    if siguiente is None:
        return None, "agotado"

    # Determinar razón para logging
    lead = fetch_one(
        "SELECT email_fuente, web_url FROM leads_brutos WHERE id = %s",
        (lead_id,)
    )
    if lead and siguiente == lead.get('email_fuente'):
        razon = "email_fuente"
    else:
        razon = "patron_generico"

    return siguiente, razon


def get_emails_intentados(lead_id: int) -> list[str]:
    """
    Devuelve la lista de emails ya intentados para un lead (para evitar repetir).
    """
    rows = fetch_all(
        "SELECT DISTINCT email_destino FROM outreach_intentos WHERE lead_id = %s",
        (lead_id,)
    )
    return [r['email_destino'] for r in rows] if rows else []
