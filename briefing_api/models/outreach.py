from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class PrepareRequest(BaseModel):
    lead_id: int
    tipo: str  # "primer_contacto" | "seguimiento"
    slot_1: str  # viene de n8n con Google Calendar ya resuelto, ej: "martes 15 de abril a las 3:00 PM"
    slot_2: str
    programado_para: Optional[datetime] = None  # si None → NOW(). El planner semanal pasa timestamp futuro.


class PrepareResponse(BaseModel):
    lead_id: int
    intento_id: int
    email_destino: str         # email al que se enviará (en dev puede ser el override)
    email_real: Optional[str]  # solo en dev: el email real del lead (para verificación)
    asunto: str
    cuerpo: str
    matrix_id: int
    tipo: str
    programado_para: Optional[datetime] = None
    is_dry_run: bool = False   # True en environment=development


class CascadeRequest(BaseModel):
    lead_id: int
    intento_id: int  # el intento que hizo bounce_hard
    email_fallido: str


class CascadeResponse(BaseModel):
    lead_id: int
    siguiente_email: Optional[str]
    hay_siguiente: bool
    razon: Optional[str]  # "email_fuente", "patron_info", "patron_contacto", "agotado"


class IntentoEstado(BaseModel):
    intento_id: int
    lead_id: int
    tipo: str
    email_destino: str
    asunto: str
    estado: str
    enviado_at: Optional[datetime]
    respondio_at: Optional[datetime]
    bounce_at: Optional[datetime]
