"""Order of the turn steps and deduplication across a whole conversation."""

from conversational_agents.agents import ActionOutcome, DebtAgent
from conversational_agents.conversation import Conversation
from conversational_agents.http_client import FakeHttpClient
from conversational_agents.integrations import BearerTokenAuth, HttpIntegration
from conversational_agents.models import ParserModel
from tests.constants import DEBT_URL, TEST_TOKEN, TODAY

DATE = "2026-11-05"


class RecordingConversationModel:
    """Replies 'ok' and records the messages it could see when it replied."""

    def __init__(self) -> None:
        self.seen: list[list[tuple[str, str]]] = []

    def answer_user(self, conversation: Conversation) -> str:
        self.seen.append([(m.role.value, m.content) for m in conversation.messages])
        return "ok"


def _agent(client: FakeHttpClient, parsed_turns: list[dict], model=None) -> DebtAgent:
    return DebtAgent(
        model or RecordingConversationModel(),
        ParserModel(parsed_turns),
        HttpIntegration(DEBT_URL, client, BearerTokenAuth(TEST_TOKEN)),
        today=lambda: TODAY,
    )


class TestReplyKnowsActionOutcome:
    def test_reply_is_generated_after_a_failed_action_and_can_see_the_failure(self):
        model = RecordingConversationModel()
        agent = _agent(FakeHttpClient(status_code=500), [{"commitment_date": DATE, "committed_amount": 150}], model)

        result = agent.handle_turn("I will pay 150 on November 5")

        assert result.outcome == ActionOutcome.FAILED
        (seen,) = model.seen
        assert seen[-1][0] == "system"
        assert "failed" in seen[-1][1]

    def test_reply_can_see_an_executed_action(self):
        model = RecordingConversationModel()
        agent = _agent(FakeHttpClient(), [{"commitment_date": DATE, "committed_amount": 150}], model)

        agent.handle_turn("I will pay 150 on November 5")

        (seen,) = model.seen
        assert seen[-1][0] == "system"
        assert "executed" in seen[-1][1]

    def test_no_system_message_when_no_action_is_attempted(self):
        model = RecordingConversationModel()
        agent = _agent(FakeHttpClient(), [{"commitment_date": None, "committed_amount": None}], model)

        agent.handle_turn("Hi")

        assert [role for role, _ in model.seen[0]] == ["user"]
        assert [m.role.value for m in agent.conversation.messages] == ["user", "agent"]


class TestLatestCommitmentWins:
    def test_returning_to_a_previous_commitment_is_registered_again(self):
        client = FakeHttpClient()
        agent = _agent(
            client,
            [
                {"commitment_date": DATE, "committed_amount": 150},
                {"commitment_date": DATE, "committed_amount": 200},
                {"commitment_date": DATE, "committed_amount": 150},
            ],
        )

        outcomes = [agent.handle_turn("...").outcome for _ in range(3)]

        assert outcomes == [ActionOutcome.EXECUTED] * 3
        assert [r.json["committed_amount"] for r in client.sent_requests] == [150.0, 200.0, 150.0]

    def test_returning_to_a_previous_commitment_uses_a_new_idempotency_key(self):
        client = FakeHttpClient()
        agent = _agent(
            client,
            [
                {"commitment_date": DATE, "committed_amount": 150},
                {"commitment_date": DATE, "committed_amount": 200},
                {"commitment_date": DATE, "committed_amount": 150},
            ],
        )

        for _ in range(3):
            agent.handle_turn("...")

        first, _, third = client.sent_requests
        assert first.headers["Idempotency-Key"] != third.headers["Idempotency-Key"]
