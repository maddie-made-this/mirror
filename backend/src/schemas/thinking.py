"""'Mirror's thinking' click-through (product reshape §3.6 / P2.4). REAL pipeline artifacts
already used to generate a turn — never theater. The optional `summary` is a narrativized
'its read' on top, generated lazily + cached, null until enabled/opened."""
from pydantic import BaseModel, Field


class ThinkingNode(BaseModel):
    id: str
    name: str


class ThinkingInterpretation(BaseModel):
    id: str
    statement: str
    kind: str
    confidence: float | None = None


class ThinkingOffer(BaseModel):
    element: str
    source_tag: str
    uptake: str | None = None


class ThinkingView(BaseModel):
    input_nodes: list[ThinkingNode] = Field(default_factory=list)
    interpretations: list[ThinkingInterpretation] = Field(default_factory=list)
    steering_objective: str | None = None
    piece_brief: dict | None = None      # curated real director fields (not theater)
    element_offers: list[ThinkingOffer] = Field(default_factory=list)
    summary: str | None = None           # optional narrativized read; null until generated
