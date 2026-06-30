import re
import httpx
from datetime import datetime
from typing import Optional

from config import get_settings
from database import fetch_one, execute
from services.email_validator import is_valid_email, extract_domain

settings = get_settings()

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
MAILTO_RE = re.compile(r'mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', re.IGNORECASE)
SCHEMA_RE = re.compile(r'"email"\s*:\s*"([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})"', re.IGNORECASE)

IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif', '.ico', '.avif', '.bmp', '.pdf')
SCRAPE_TIMEOUT = 8.0
API_TIMEOUT = 10.0

CONTACT_PATHS = [
    '/contacto', '/contact', '/contactenos', '/contactus',
    '/nosotros', '/about', '/quienes-somos', '/empresa',
    '/equipo', '/acerca-de', '/acerca', '/team',
]

WHOIS_TIMEOUT = 6.0


# ── Quota ────────────────────────────────────────────────────────────────────

def _quota_ok(servicio: str) -> bool:
    now = datetime.utcnow()
    row = fetch_one("SELECT mes, año, usados, limite FROM enrichment_quota WHERE servicio = %s", (servicio,))
    if not row:
        return False
    if row['mes'] != now.month or row['año'] != now.year:
        execute(
            "UPDATE enrichment_quota SET mes=%s, año=%s, usados=0 WHERE servicio=%s",
            (now.month, now.year, servicio)
        )
        return True
    return row['usados'] < row['limite']


def _increment_quota(servicio: str):
    execute("UPDATE enrichment_quota SET usados = usados + 1 WHERE servicio = %s", (servicio,))


# ── Scraping ─────────────────────────────────────────────────────────────────

def _is_image_email(email: str) -> bool:
    local = email.split('@')[0].lower()
    return any(local.endswith(ext) or email.lower().endswith(ext) for ext in IMAGE_EXTS)


def _extract_emails_from_html(html: str, domain: str) -> list[str]:
    result = []

    # Prioridad 1: mailto: links — más confiables
    for e in MAILTO_RE.findall(html):
        e = e.lower()
        if not _is_image_email(e) and is_valid_email(e) and domain in e and e not in result:
            result.append(e)

    # Prioridad 2: schema.org structured data
    for e in SCHEMA_RE.findall(html):
        e = e.lower()
        if not _is_image_email(e) and is_valid_email(e) and domain in e and e not in result:
            result.append(e)

    # Prioridad 3: regex general sobre el texto
    for e in EMAIL_RE.findall(html):
        e = e.lower()
        if not _is_image_email(e) and is_valid_email(e) and domain in e and e not in result:
            result.append(e)

    return result


def _find_contact_links(html: str, base_url: str) -> list[str]:
    """Extrae hrefs internos que parezcan páginas de contacto."""
    LINK_RE = re.compile(r'href=["\']([^"\']*)["\']', re.IGNORECASE)
    CONTACT_KEYWORDS = re.compile(r'contact|contacto|nosotros|about|empresa|equipo|acerca', re.IGNORECASE)
    found = []
    for href in LINK_RE.findall(html):
        if CONTACT_KEYWORDS.search(href):
            if href.startswith('http'):
                url = href
            elif href.startswith('/'):
                from urllib.parse import urlparse
                parsed = urlparse(base_url)
                url = f"{parsed.scheme}://{parsed.netloc}{href}"
            else:
                continue
            if url not in found:
                found.append(url)
    return found[:5]


def scrape_contact_emails(web_url: str) -> list[str]:
    domain = extract_domain(web_url)
    if not domain:
        return []

    base = web_url.rstrip('/')
    pages = [base] + [base + p for p in CONTACT_PATHS]
    seen_urls = set()
    emails = []

    with httpx.Client(timeout=SCRAPE_TIMEOUT, follow_redirects=True,
                      headers={'User-Agent': 'Mozilla/5.0 (compatible; Googlebot/2.1)'}) as client:
        # Primera pasada: rutas conocidas
        for url in pages:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                r = client.get(url)
                if r.status_code == 200:
                    found = _extract_emails_from_html(r.text, domain)
                    for e in found:
                        if e not in emails:
                            emails.append(e)
                    # Si aún no encontramos nada en la home, buscar links internos de contacto
                    if not emails and url == base:
                        for contact_url in _find_contact_links(r.text, base):
                            if contact_url not in seen_urls:
                                pages.append(contact_url)
                    if emails:
                        break
            except Exception:
                continue

    return emails


# ── WHOIS lookup ──────────────────────────────────────────────────────────────

def whois_lookup(domain: str) -> list[str]:
    """Busca emails en datos WHOIS del dominio via API gratuita."""
    try:
        r = httpx.get(
            f'https://www.whoisxmlapi.com/whoisserver/WhoisService',
            params={'apiKey': 'at_free', 'domainName': domain, 'outputFormat': 'JSON'},
            timeout=WHOIS_TIMEOUT,
        )
        if r.status_code == 200:
            text = r.text
            found = EMAIL_RE.findall(text)
            result = []
            for e in found:
                e = e.lower()
                # Filtrar emails de whoisxmlapi.com y dominios de registro
                if is_valid_email(e) and domain in e and e not in result:
                    result.append(e)
            return result
    except Exception:
        pass

    # Fallback: whoisjson.com
    try:
        r = httpx.get(f'https://whoisjson.com/api/v1/whois?domain={domain}', timeout=WHOIS_TIMEOUT)
        if r.status_code == 200:
            text = r.text
            found = EMAIL_RE.findall(text)
            result = []
            for e in found:
                e = e.lower()
                if is_valid_email(e) and domain in e and e not in result:
                    result.append(e)
            return result
    except Exception:
        pass

    return []


# ── Prospeo ──────────────────────────────────────────────────────────────────

def prospeo_domain_search(domain: str) -> list[str]:
    if not settings.prospeo_api_key or not _quota_ok('prospeo'):
        return []
    try:
        r = httpx.get(
            'https://api.prospeo.io/domain-search',
            params={'domain': domain},
            headers={'X-KEY': settings.prospeo_api_key},
            timeout=API_TIMEOUT,
        )
        if r.status_code == 200:
            _increment_quota('prospeo')
            emails = [e.get('email') for e in r.json().get('response', {}).get('emails', []) if e.get('email')]
            return [e for e in emails if is_valid_email(e)]
        if r.status_code == 429:
            execute("UPDATE enrichment_quota SET usados=limite WHERE servicio='prospeo'", ())
    except Exception:
        pass
    return []


# ── Hunter.io ────────────────────────────────────────────────────────────────

def hunter_domain_search(domain: str) -> list[str]:
    if not settings.hunter_api_key or not _quota_ok('hunter'):
        return []
    try:
        r = httpx.get(
            'https://api.hunter.io/v2/domain-search',
            params={'domain': domain, 'api_key': settings.hunter_api_key},
            timeout=API_TIMEOUT,
        )
        if r.status_code == 200:
            _increment_quota('hunter')
            data = r.json().get('data', {})
            emails = [e['value'] for e in data.get('emails', []) if e.get('value')]
            return [e for e in emails if is_valid_email(e)]
        if r.status_code == 429:
            execute("UPDATE enrichment_quota SET usados=limite WHERE servicio='hunter'", ())
    except Exception:
        pass
    return []


# ── Snov.io ──────────────────────────────────────────────────────────────────

def _snov_get_token() -> Optional[str]:
    if not settings.snov_client_id or not settings.snov_client_secret:
        return None
    try:
        r = httpx.post(
            'https://api.snov.io/v1/oauth/access_token',
            json={
                'grant_type': 'client_credentials',
                'client_id': settings.snov_client_id,
                'client_secret': settings.snov_client_secret,
            },
            timeout=API_TIMEOUT,
        )
        if r.status_code == 200:
            return r.json().get('access_token')
    except Exception:
        pass
    return None


def snov_domain_search(domain: str) -> list[str]:
    if not _quota_ok('snov'):
        return []
    token = _snov_get_token()
    if not token:
        return []
    try:
        r = httpx.post(
            'https://api.snov.io/v1/get-domain-emails-with-info',
            json={'domain': domain, 'type': 'all', 'limit': 10},
            headers={'Authorization': f'Bearer {token}'},
            timeout=API_TIMEOUT,
        )
        if r.status_code == 200:
            _increment_quota('snov')
            emails = [e.get('email') for e in r.json().get('emails', []) if e.get('email')]
            return [e for e in emails if is_valid_email(e)]
        if r.status_code == 429:
            execute("UPDATE enrichment_quota SET usados=limite WHERE servicio='snov'", ())
    except Exception:
        pass
    return []


# ── Verificación ─────────────────────────────────────────────────────────────

def verify_zerobounce(email: str) -> Optional[bool]:
    if not settings.zerobounce_api_key or not _quota_ok('zerobounce'):
        return None
    try:
        r = httpx.get(
            'https://api.zerobounce.net/v2/validate',
            params={'api_key': settings.zerobounce_api_key, 'email': email, 'ip_address': ''},
            timeout=API_TIMEOUT,
        )
        if r.status_code == 200:
            _increment_quota('zerobounce')
            status = r.json().get('status', '')
            if status == 'valid':
                return True
            if status in ('invalid', 'spamtrap', 'abuse', 'do_not_mail'):
                return False
            return None  # catch-all / unknown
        if r.status_code == 429:
            execute("UPDATE enrichment_quota SET usados=limite WHERE servicio='zerobounce'", ())
    except Exception:
        pass
    return None


def verify_abstract(email: str) -> Optional[bool]:
    if not settings.abstract_api_key or not _quota_ok('abstract'):
        return None
    try:
        r = httpx.get(
            'https://emailreputation.abstractapi.com/v1/',
            params={'api_key': settings.abstract_api_key, 'email': email},
            timeout=API_TIMEOUT,
        )
        if r.status_code == 200:
            _increment_quota('abstract')
            deliverability = r.json().get('deliverability', '')
            if deliverability == 'DELIVERABLE':
                return True
            if deliverability == 'UNDELIVERABLE':
                return False
            return None  # RISKY / UNKNOWN
        if r.status_code == 429:
            execute("UPDATE enrichment_quota SET usados=limite WHERE servicio='abstract'", ())
    except Exception:
        pass
    return None


def verify_email(email: str) -> Optional[bool]:
    result = verify_zerobounce(email)
    if result is not None:
        return result
    return verify_abstract(email)


# ── Pipeline principal ────────────────────────────────────────────────────────

def enrich_lead(lead: dict) -> Optional[str]:
    """
    Corre el pipeline completo para un lead.
    Orden: scraping → WHOIS → Hunter → Snov → verificación.
    Retorna el primer email encontrado y no inválido, o None.
    """
    web_url = lead.get('web_url', '')
    domain = extract_domain(web_url) if web_url else None

    # 1. Scraping mejorado (gratis, ilimitado)
    if web_url:
        scraped = scrape_contact_emails(web_url)
        if scraped:
            return scraped[0]

    if not domain:
        return None

    # 2. WHOIS lookup (gratis, ilimitado)
    whois_emails = whois_lookup(domain)
    if whois_emails:
        return whois_emails[0]

    # 3. Hunter
    hunter_emails = hunter_domain_search(domain)
    for email in hunter_emails:
        result = verify_email(email)
        if result is True:
            return email
        if result is None:
            return email

    # 4. Snov
    snov_emails = snov_domain_search(domain)
    for email in snov_emails:
        result = verify_email(email)
        if result is True:
            return email
        if result is None:
            return email

    # 5. Prospeo
    prospeo_emails = prospeo_domain_search(domain)
    for email in prospeo_emails:
        result = verify_email(email)
        if result is True:
            return email
        if result is None:
            return email

    return None
