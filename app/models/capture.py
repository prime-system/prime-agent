from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Source(str, Enum):
    IPHONE = "iphone"
    IPAD = "ipad"
    MAC = "mac"


class InputType(str, Enum):
    VOICE = "voice"
    TEXT = "text"


class AppContext(str, Enum):
    PRIME = "prime"
    SHORTCUTS = "shortcuts"
    CLI = "cli"
    WEB = "web"


class Location(BaseModel):
    latitude: float
    longitude: float


class CaptureContext(BaseModel):
    app: AppContext
    location: Location | None = None


class CaptureRequest(BaseModel):
    text: str = Field(..., min_length=1)
    source: Source
    input: InputType
    captured_at: datetime
    context: CaptureContext


class CaptureResponse(BaseModel):
    ok: bool = True
    inbox_file: str
    dump_id: str
