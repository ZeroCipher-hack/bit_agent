"""Tool framework. Each tool is a small class; drop a new file into app/tools/ and it is picked up automatically."""
from dataclasses import dataclass, field
from typing import Any


class ToolError(Exception):
    """Raise with a short message; the model sees it and can explain or retry."""


@dataclass
class ToolContext:
    memory: Any
    client_actions: list = field(default_factory=list)  # things the app must do on the device (open URL, play video...)
    pending: list = field(default_factory=list)          # actions waiting for the user's yes/no


class Tool:
    name: str = ""
    description: str = ""
    input_schema: dict = {"type": "object", "properties": {}}
    side_effect: bool = True   # changes something outside the chat
    risky: bool = False        # talks to other people, touches accounts or servers -> confirmation

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}

    def validate(self, args: dict) -> None:
        """Check arguments before anything is queued or run. Raise ToolError on bad input."""

    def summary(self, args: dict) -> str:
        """One line shown to the user in the confirmation card."""
        return f"{self.name}: {args}"

    async def run(self, args: dict, ctx: ToolContext) -> dict:
        raise NotImplementedError
