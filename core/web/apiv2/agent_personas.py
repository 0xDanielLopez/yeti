from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from core.schemas import audit, rbac, roles
from core.schemas.agent_persona import AgentPersona

router = APIRouter()


class NewPersonaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: AgentPersona


class PatchPersonaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: AgentPersona


class PersonaSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    enabled: bool | None = None
    count: int = 50
    page: int = 0


class PersonaSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personas: list[AgentPersona]
    total: int


def _all_personas() -> list[AgentPersona]:
    """Every persona, unpaginated.

    ArangoYetiConnector.filter() matches values with LIKE, so a boolean
    query_arg silently matches nothing rather than failing -- there is no way
    to ask it for `default == True`. Personas are a handful per deployment, so
    the fields it cannot express are filtered here instead.
    """
    personas, _ = AgentPersona.filter(query_args={}, count=0)
    return personas


def _clear_other_defaults(persona: AgentPersona) -> None:
    """Leaves `persona` as the only default.

    Enforced against the personas themselves rather than by a separate
    setting, so there is no way for a "which persona is default" value to
    disagree with them.
    """
    for other in _all_personas():
        if other.id == persona.id or not other.default:
            continue
        other.default = False
        other.save()


@router.post("/")
@rbac.global_permission(roles.Permission.WRITE)
def new(httpreq: Request, request: NewPersonaRequest) -> AgentPersona:
    """Creates a new agent persona."""
    if AgentPersona.find(name=request.persona.name):
        raise HTTPException(
            status_code=409,
            detail=f"Persona {request.persona.name} already exists",
        )

    persona = request.persona.save()
    if persona.default:
        _clear_other_defaults(persona)
    rbac.set_acls(persona, user=httpreq.state.user)
    audit.log_timeline(httpreq.state.username, persona)
    return persona


@router.patch("/{id}")
@rbac.permission_on_target(roles.Permission.WRITE)
def patch(httpreq: Request, request: PatchPersonaRequest, id: str) -> AgentPersona:
    """Updates an agent persona."""
    existing = AgentPersona.get(id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Persona {id} not found")

    update = request.persona.model_dump(exclude={"id", "created"})
    persona = existing.model_copy(update=update).save()
    if persona.default:
        _clear_other_defaults(persona)
    audit.log_timeline(httpreq.state.username, persona, old=existing)
    return persona


@router.get("/{id}")
@rbac.permission_on_target(roles.Permission.READ)
def details(httpreq: Request, id: str) -> AgentPersona:
    """Returns a single agent persona."""
    persona = AgentPersona.get(id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona {id} not found")
    return persona


@router.delete("/{id}")
@rbac.permission_on_target(roles.Permission.WRITE)
def delete(httpreq: Request, id: str) -> None:
    """Deletes an agent persona.

    The default is refused: deleting it would leave requests that name no
    persona with nothing to fall back to, and the agents service would silently
    revert to its built-in instructions. Mark another as default first.
    """
    persona = AgentPersona.get(id)
    if not persona:
        raise HTTPException(status_code=404, detail=f"Persona {id} not found")
    if persona.default:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the default persona; mark another as default first",
        )
    persona.delete()


@router.post("/search")
def search(httpreq: Request, request: PersonaSearchRequest) -> PersonaSearchResponse:
    """Searches for agent personas."""
    personas, _ = AgentPersona.filter(
        query_args={"name": request.name},
        count=0,
        user=httpreq.state.user,
    )

    # `enabled` is applied here, not in the query: filter() matches with LIKE,
    # so a boolean matches nothing at all. Paginating afterwards for the same
    # reason -- slicing before the filter would return short pages.
    if request.enabled is not None:
        personas = [p for p in personas if p.enabled == request.enabled]

    total = len(personas)
    start = request.page * request.count
    return PersonaSearchResponse(
        personas=personas[start : start + request.count], total=total
    )
