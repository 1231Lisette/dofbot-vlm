from __future__ import annotations

from pydantic import BaseModel, Field


class JointCommand(BaseModel):
    targets: dict[str, float] = Field(default_factory=dict)


class ToolCommand(BaseModel):
    xyz: tuple[float, float, float]


class GripperCommand(BaseModel):
    opening: float = Field(ge=0.0, le=1.0)


class PickPlaceCommand(BaseModel):
    object_name: str = "red_cube"
    target_xy: tuple[float, float] = (-0.2, 0.05)


class PixelCoordinate(BaseModel):
    u: float
    v: float


class NaturalLanguageCommand(BaseModel):
    text: str = Field(min_length=1, max_length=200)


class GestureFrame(BaseModel):
    gesture: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp_ms: float | None = Field(default=None, ge=0.0)
    source: str = Field(default="camera", max_length=32)


class CommandMessage(BaseModel):
    type: str
    targets: dict[str, float] | None = None
    xyz: tuple[float, float, float] | None = None
    opening: float | None = None
    object_name: str | None = None
    target_xy: tuple[float, float] | None = None
    text: str | None = None
    gesture: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    timestamp_ms: float | None = Field(default=None, ge=0.0)
    source: str | None = None
