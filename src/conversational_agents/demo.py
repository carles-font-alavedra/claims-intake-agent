"""Runs one scripted conversation per agent and prints the requests built."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from conversational_agents.agents import BaseAgent
from conversational_agents.factory import AgentFactory, Settings
from conversational_agents.http_client import FakeHttpClient
from conversational_agents.models import ConversationModel, ParserModel


def _run(title: str, agent: BaseAgent, user_messages: list[str]) -> None:
    print(f"\n=== {title} ===")
    for message in user_messages:
        result = agent.handle_turn(message)
        print(f"user:  {message}")
        print(f"agent: {result.reply}")
        print(f"       data={dict(result.parsed_data)} -> action: {result.outcome.value}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    client = FakeHttpClient()
    factory = AgentFactory(Settings.from_env(), client)
    payment_day = (date.today() + timedelta(days=7)).isoformat()

    debt_agent = factory.debt_agent(
        ConversationModel(
            [
                "Hello, I'm calling about your outstanding debt of €300. When could you pay it?",
                "Great. How much would you pay that day?",
                "Your commitment has been registered. Thank you!",
                "You're welcome, have a nice day.",
            ]
        ),
        ParserModel(
            [
                {"commitment_date": None, "committed_amount": None},
                {"commitment_date": payment_day, "committed_amount": None},
                {"commitment_date": payment_day, "committed_amount": 300},
                {"commitment_date": payment_day, "committed_amount": 300},
            ]
        ),
    )
    _run("DebtAgent", debt_agent, ["Hi", "Next week", "The full €300", "Thanks"])

    assistance_agent = factory.assistance_agent(
        ConversationModel(["How can I help you?", "I've registered your request, an agent will contact you."]),
        ParserModel([{"request": None}, {"request": "  Change billing address to Málaga "}]),
    )
    _run("AssistanceAgent", assistance_agent, ["Hi", "I want to change my billing address to Málaga"])

    print(f"\n=== Requests built ({len(client.sent_requests)}) ===")
    for request in client.sent_requests:
        print(f"{request.method} {request.url}")
        for name, value in request.headers.items():
            print(f"  {name}: {value}")
        print(f"  body: {json.dumps(dict(request.json), ensure_ascii=False)}")


if __name__ == "__main__":
    main()
