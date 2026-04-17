import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from config import get_settings
from database import fetch_one

router = APIRouter()
settings = get_settings()


class TwentyLeadRequest(BaseModel):
    lead_id: int
    intento_id: Optional[int] = None  # para trazabilidad


class TwentyLeadResponse(BaseModel):
    lead_id: int
    company_id: Optional[str]
    opportunity_id: Optional[str]
    status: str
    message: str


def _gql(query: str, variables: dict) -> dict:
    """Ejecuta una mutación/query GraphQL contra Twenty CRM."""
    if not settings.twenty_api_token:
        raise HTTPException(
            status_code=503,
            detail="TWENTY_API_TOKEN no configurado. Agregar en variables de entorno."
        )

    url = f"{settings.twenty_api_url}/api"
    headers = {
        "Authorization": f"Bearer {settings.twenty_api_token}",
        "Content-Type": "application/json",
    }

    try:
        r = httpx.post(
            url,
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()

        if "errors" in data:
            raise HTTPException(
                status_code=422,
                detail=f"Twenty GraphQL error: {data['errors']}"
            )
        return data.get("data", {})

    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error conectando a Twenty CRM: {str(e)}"
        )


@router.post("/create_lead_record", response_model=TwentyLeadResponse)
def create_lead_record(req: TwentyLeadRequest):
    """
    Crea el registro en Twenty CRM cuando un lead responde al outreach.
    Crea: Company (con custom fields) + Opportunity en stage 'Respondió'.
    Llamado automáticamente desde webhooks/instantly cuando event_type = 'email_replied'.
    """
    # Cargar datos del lead
    lead = fetch_one(
        """
        SELECT id, nombre, ciudad, pais, vertical_consolidada, stack_categoria,
               score, web_url, emails_sitio, email_fuente, tech_stack
        FROM leads_brutos WHERE id = %s
        """,
        (req.lead_id,)
    )

    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {req.lead_id} no encontrado")

    nombre = lead['nombre'] or f"Lead #{req.lead_id}"
    dominio = lead['web_url'] or ""
    # Limpiar dominio
    if dominio.startswith("http"):
        from urllib.parse import urlparse
        parsed = urlparse(dominio)
        dominio = parsed.netloc.replace("www.", "") or dominio

    # ── 1. Crear Company ──────────────────────────────────────────────────────
    company_mutation = """
    mutation CreateCompany($data: CompanyCreateInput!) {
      createCompany(data: $data) {
        id
        name
      }
    }
    """
    company_vars = {
        "data": {
            "name": nombre,
            "domainName": {
                "primaryLinkUrl": dominio,
                "primaryLinkLabel": "",
            },
            # Campos custom — nombres según cómo fueron creados en Twenty UI
            # Si alguno falla, comentar y ajustar según el schema real de Twenty
            "vertical": lead['vertical_consolidada'] or "",
            "leadScore": lead['score'] or 0,
            "techStack": lead['tech_stack'] or "",
            "companyType": "Prospect",
            "market": lead['pais'] or "Colombia",
        }
    }

    company_data = _gql(company_mutation, company_vars)
    company_id = company_data.get("createCompany", {}).get("id")

    if not company_id:
        return TwentyLeadResponse(
            lead_id=req.lead_id,
            company_id=None,
            opportunity_id=None,
            status="error",
            message="No se pudo crear la Company en Twenty. Verificar schema de campos custom."
        )

    # ── 2. Crear Opportunity vinculada ────────────────────────────────────────
    opportunity_mutation = """
    mutation CreateOpportunity($data: OpportunityCreateInput!) {
      createOpportunity(data: $data) {
        id
        name
      }
    }
    """
    opp_name = f"{nombre} — Consultoría inicial"
    opportunity_vars = {
        "data": {
            "name": opp_name,
            "stage": "RESPONDIO",  # Ajustar al valor exacto del stage en Twenty
            "companyId": company_id,
        }
    }

    opp_data = _gql(opportunity_mutation, opportunity_vars)
    opportunity_id = opp_data.get("createOpportunity", {}).get("id")

    return TwentyLeadResponse(
        lead_id=req.lead_id,
        company_id=company_id,
        opportunity_id=opportunity_id,
        status="ok",
        message=f"Company '{nombre}' y Opportunity creadas en Twenty CRM."
    )
