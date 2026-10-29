from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from conversational_agents.actions import AssistanceRequest
from conversational_agents.agents.base import BaseAgent
from conversational_agents.validation import parse_text


class AssistanceAgent(BaseAgent):
    """Answers questions and registers requests to be handled by a human."""

    def build_action(self, parsed_data: Mapping[str, Any]) -> AssistanceRequest | None:
        request = self._read_field(parsed_data, "request", parse_text)
        if request is None:
            return None
        return AssistanceRequest(request)
