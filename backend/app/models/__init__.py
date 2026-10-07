"""
Registro de todos los modelos: importarlos acá garantiza que SQLAlchemy
conozca cada tabla antes de resolver relaciones y claves foráneas.
"""

from app.models.organizacion import Organizacion  # noqa: F401
from app.models.empresa import Empresa  # noqa: F401
from app.models.rol import Rol  # noqa: F401
from app.models.usuario import Usuario  # noqa: F401
from app.models.cliente import Cliente  # noqa: F401
from app.models.filial import Filial  # noqa: F401
from app.models.deudor import Deudor, ContactoDeudor  # noqa: F401
from app.models.tercero import Tercero, ContactoTercero, CobranzaTercero  # noqa: F401
from app.models.cobranza import Cobranza  # noqa: F401
from app.models.gestion import Gestion, TipoGestion  # noqa: F401
from app.models.acuerdo import AcuerdoPago, Cuota  # noqa: F401
from app.models.pago import Pago  # noqa: F401
from app.models.judicial import GestionJudicial  # noqa: F401
from app.models.campo_personalizado import CampoPersonalizado  # noqa: F401
from app.models.audit import AuditLog  # noqa: F401
from app.models.seguridad import Sesion, TokenUnUso, EventoAcceso  # noqa: F401
from app.models.agenda import Recordatorio, Indicador  # noqa: F401
