import datetime
from typing import ClassVar, Literal

from pydantic import ConfigDict, Field, field_validator

from core import database_arango
from core.helpers import now
from core.schemas.model import YetiAclModel, YetiModel

MAX_NAME_LENGTH = 100
# A prompt is the agent's whole behaviour, so an empty or near-empty one is a
# mistake rather than a choice. Rejected on write: the alternative is an agent
# that answers oddly and gives no hint that its instructions are the reason.
MIN_INSTRUCTION_LENGTH = 20


class AgentPersona(YetiModel, YetiAclModel, database_arango.ArangoYetiConnector):
    """A configurable set of instructions for the conversational agent.

    Stored here rather than in the agents service so that changing how the
    agent behaves is an edit rather than a deployment: this inherits
    persistence, permissions and change history from every other Yeti object,
    and the agents service already authenticates here for its tools.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    _collection_name: ClassVar[str] = "agent_personas"
    _root_type: Literal["agent_persona"] = "agent_persona"
    _type_filter: ClassVar[str | None] = None

    name: str = Field(max_length=MAX_NAME_LENGTH)
    description: str = ""
    instruction: str

    # Tool *names*, resolved by the agents service against the tools it
    # implements. Names rather than definitions so that a persona can decline
    # capability but never invent it -- otherwise editing a persona would be a
    # way to widen what the agent can reach. Empty means every tool.
    tools: list[str] = []

    # Overrides the deployment's default model. A model named on the request
    # still wins over this.
    model: str | None = None

    enabled: bool = True
    # The persona used when a request names none. Exactly one carries it; the
    # API enforces that rather than keeping a separate "which is default"
    # setting that could disagree with the personas themselves.
    default: bool = False

    created: datetime.datetime = Field(default_factory=now)
    modified: datetime.datetime = Field(default_factory=now)

    @field_validator("instruction")
    @classmethod
    def instruction_is_substantial(cls, value: str) -> str:
        if len(value.strip()) < MIN_INSTRUCTION_LENGTH:
            raise ValueError(
                f"instruction must be at least {MIN_INSTRUCTION_LENGTH} characters"
            )
        return value

    @classmethod
    def load(cls, object: dict) -> "AgentPersona":
        return cls(**object)
