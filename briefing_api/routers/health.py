from fastapi import APIRouter
from database import fetch_one, fetch_all
from config import get_settings
import httpx
import re

router = APIRouter()
EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')


@router.get("/health")
def health_check():
    try:
        fetch_one("SELECT 1 AS ok")
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
        "service": "briefing_api",
        "version": "1.0.0",
    }


@router.get("/health/enrichment-debug")
def enrichment_debug():
    settings = get_settings()

    # 1. Config
    config = {
        "hunter_api_key": "SET" if settings.hunter_api_key else "EMPTY",
        "snov_client_id": "SET" if settings.snov_client_id else "EMPTY",
        "snov_client_secret": "SET" if settings.snov_client_secret else "EMPTY",
        "zerobounce_api_key": "SET" if settings.zerobounce_api_key else "EMPTY",
        "abstract_api_key": "SET" if settings.abstract_api_key else "EMPTY",
    }

    # 2. Quota
    quota_rows = fetch_all("SELECT servicio, usados, limite, mes, año FROM enrichment_quota ORDER BY servicio", ())
    quota = [dict(r) for r in quota_rows] if quota_rows else []

    # 3. Candidatos disponibles
    candidatos = fetch_all("""
        SELECT id, web_url, score FROM leads_brutos
        WHERE mx_records = 'TRUE'
          AND (emails_sitio IS NULL OR emails_sitio = '')
          AND email_enrich_tried_at IS NULL
          AND contacto_status = 'pendiente'
        ORDER BY score DESC NULLS LAST LIMIT 3
    """, ())
    candidatos = [dict(r) for r in candidatos] if candidatos else []

    # 4. Test scraping con primer candidato
    scraping_test = {}
    if candidatos:
        web_url = candidatos[0]['web_url']
        domain = web_url.replace('https://','').replace('http://','').replace('www.','').split('/')[0]
        try:
            r = httpx.get(web_url, timeout=8, follow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'})
            emails = [e for e in EMAIL_RE.findall(r.text) if domain in e]
            scraping_test = {"url": web_url, "status": r.status_code, "emails_found": emails[:5]}
        except Exception as e:
            scraping_test = {"url": web_url, "error": str(e)}

    # 5. Test Hunter con primer candidato
    hunter_test = {}
    if candidatos and settings.hunter_api_key:
        domain = candidatos[0]['web_url'].replace('https://','').replace('http://','').replace('www.','').split('/')[0]
        try:
            r = httpx.get('https://api.hunter.io/v2/domain-search',
                params={'domain': domain, 'api_key': settings.hunter_api_key}, timeout=10)
            hunter_test = {"status": r.status_code, "body_preview": r.text[:300]}
        except Exception as e:
            hunter_test = {"error": str(e)}
    else:
        hunter_test = {"skip": "key empty or no candidates"}

    return {
        "config": config,
        "quota": quota,
        "candidatos_disponibles": len(candidatos),
        "candidatos": candidatos,
        "scraping_test": scraping_test,
        "hunter_test": hunter_test,
    }
