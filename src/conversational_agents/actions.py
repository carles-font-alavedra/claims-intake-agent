"""Actions an agent can decide to execute."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any


class Action(ABC):
    """Validated data to send to an integration. Subclasses are frozen dataclasses."""

    @abstractmethod
    def to_payload(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PaymentCommitment(Action):
    commitment_date: date
    committed_amount: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "commitment_date": self.commitment_date.isoformat(),
            "committed_amount": self.committed_amount,
        }


@dataclass(frozen=True)
class AssistanceRequest(Action):
    request: str

    def to_payload(self) -> dict[str, Any]:
        return {"request": self.request}


def idempotency_key(conversation_id: str, action: Action, sequence: int = 0) -> str:
    """Deterministic key so the server can discard retried requests.

    `sequence` is the number of actions already executed in the conversation: a retry
    after a failure keeps the same key, while re-sending an earlier action after a
    different one (A -> B -> A) gets a new one.
    """
    raw = json.dumps(
        {
            "conversation": conversation_id,
            "sequence": sequence,
            "action": type(action).__name__,
            "payload": action.to_payload(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()
