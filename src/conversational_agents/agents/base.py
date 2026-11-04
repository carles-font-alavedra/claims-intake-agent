"""Common turn lifecycle shared by every agent."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

from conversational_agents.actions import Action, idempotency_key
from conversational_agents.conversation import Conversation
from conversational_agents.integrations import ActionResult, Integration
from conversational_agents.models import SupportsAnswerUser, SupportsParseData
from conversational_agents.validation import InvalidFieldError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ActionOutcome(str, Enum):
    NOT_REQUIRED = "not_required"  # conditions not met yet
    DUPLICATE = "duplicate"  # same as the last action executed in this conversation
    EXECUTED = "executed"
    FAILED = "failed"  # will be retried if still required next turn


@dataclass(frozen=True)
class TurnResult:
    reply: str
    parsed_data: Mapping[str, Any]
    action: Action | None
    outcome: ActionOutcome
    action_result: ActionResult | None = None


class BaseAgent(ABC):
    """Runs a conversation turn. One instance handles one conversation."""

    def __init__(
        self,
        conversation_model: SupportsAnswerUser,
        parser_model: SupportsParseData,
        integration: Integration,
        conversation: Conversation | None = None,
    ) -> None:
        self._conversation_model = conversation_model
        self._parser_model = parser_model
        self._integration = integration
        self._conversation = conversation if conversation is not None else Conversation()
        self._last_executed: Action | None = None
        self._executed_count = 0

    @property
    def conversation(self) -> Conversation:
        return self._conversation

    def handle_turn(self, user_message: str) -> TurnResult:
        self._conversation.add_user_message(user_message)

        # Act first and reply last, so the reply can't claim something that failed.
        parsed_data = self._parser_model.parse_data(self._conversation)
        action = self.build_action(parsed_data)
        outcome, result = self._run_action(action)
        if outcome in (ActionOutcome.EXECUTED, ActionOutcome.FAILED):
            self._conversation.add_system_message(f"{type(action).__name__} {outcome.value}")

        reply = self._conversation_model.answer_user(self._conversation)
        self._conversation.add_agent_message(reply)
        return TurnResult(reply, parsed_data, action, outcome, result)

    def _run_action(self, action: Action | None) -> tuple[ActionOutcome, ActionResult | None]:
        if action is None:
            return ActionOutcome.NOT_REQUIRED, None
        if self._is_duplicate(action):
            logger.debug("Skipping duplicate %r", action)
            return ActionOutcome.DUPLICATE, None

        key = idempotency_key(self._conversation.id, action, self._executed_count)
        result = self._integration.execute(action, idempotency_key=key)
        if not result.success:
            # Not recorded as executed: it is retried (same key) if still required next turn.
            return ActionOutcome.FAILED, result

        self._last_executed = action
        self._executed_count += 1
        return ActionOutcome.EXECUTED, result

    @abstractmethod
    def build_action(self, parsed_data: Mapping[str, Any]) -> Action | None:
        """Return the action to execute, or None if the conditions are not met."""

    def _is_duplicate(self, action: Action) -> bool:
        """Whether this action is the latest one executed (the last decision is the one that counts)."""
        return action == self._last_executed

    def _read_field(self, parsed_data: Mapping[str, Any], name: str, parse: Callable[[Any], T]) -> T | None:
        """Read a field, treating missing, null or invalid values as not provided."""
        value = parsed_data.get(name)
        if value is None:
            return None
        try:
            return parse(value)
        except InvalidFieldError as exc:
            logger.warning("%s: ignoring invalid %s: %s", type(self).__name__, name, exc)
            return None
