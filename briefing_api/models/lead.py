from pydantic import BaseModel
from typing import Optional


class LeadStatus(BaseModel):
    lead_id: int
    nombre: str
    ciudad: Optional[str]
    vertical_consolidada: Optional[str]
    stack_categoria: Optional[str]
    score: int
    emails_sitio: Optional[str]
    email_fuente: Optional[str]
    web_url: Optional[str]
    contacto_status: str
