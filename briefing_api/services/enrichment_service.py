import re
import httpx
from datetime import datetime
from typing import Optional

from config import get_settings
from database import fetch_one, execute
from services.email_validator import is_valid_email, extract_domain

settings = get_settings()

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
SCRAPE_TIMEOUT = 8.0
API_TIMEOUT = 10.0

CONTACT_PATHS = ['/contacto', '/contact', '/contactenos', '/contactus', '/nosotros', '/about']


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

def _extract_emails_from_html(html: str, domain: str) -> list[str]:
    found = EMAIL_RE.findall(html)
    result = []
    for e in found:
        e = e.lower()
        if is_valid_email(e) and domain in e and e not in result:
            result.append(e)
    return result


def scrape_contact_emails(web_url: str) -> list[str]:
    domain = extract_domain(web_url)
    if not domain:
        return []

    base = web_url.rstrip('/')
    pages = [base] + [base + p for p in CONTACT_PATHS]
    seen_urls = set()
    emails = []

    with httpx.Client(timeout=SCRAPE_TIMEOUT, follow_redirects=True,
                      headers={'User-Agent': 'Mozilla/5.0'}) as client:
        for url in pages:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                r = client.get(url)
                if r.status_code == 200:
                    for e in _extract_emails_from_html(r.text, domain):
                        if e not in emails:
                            emails.append(e)
                    if emails:
                        break
            except Exception:
                continue

    return emails


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
    Retorna el email encontrado y verificado, o None si no encontró nada útil.
    """
    web_url = lead.get('web_url', '')
    domain = extract_domain(web_url) if web_url else None

    # 1. Scraping
    if web_url:
        scraped = scrape_contact_emails(web_url)
        if scraped:
            return scraped[0]

    if not domain:
        return None

    # 2. Hunter
    hunter_emails = hunter_domain_search(domain)
    for email in hunter_emails:
        result = verify_email(email)
        if result is True:
            return email
        if result is None:
            return email  # sin verificar, pero encontrado — mejor que nada

    # 3. Snov
    snov_emails = snov_domain_search(domain)
    for email in snov_emails:
        result = verify_email(email)
        if result is True:
            return email
        if result is None:
            return email

    return None
