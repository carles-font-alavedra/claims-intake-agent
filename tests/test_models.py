import pytest

from conversational_agents.conversation import Conversation
from conversational_agents.models import ConversationModel, ParserModel, ScriptExhaustedError


def test_conversation_model_returns_replies_in_order():
    model = ConversationModel(["Hi", "Bye"])
    conversation = Conversation()

    assert model.answer_user(conversation) == "Hi"
    assert model.answer_user(conversation) == "Bye"


def test_parser_model_returns_parsed_data_in_order():
    model = ParserModel([{"request": None}, {"request": "Change plan"}])
    conversation = Conversation()

    assert model.parse_data(conversation) == {"request": None}
    assert model.parse_data(conversation) == {"request": "Change plan"}


def test_parser_model_output_cannot_mutate_script():
    script = [{"request": "Change plan"}]
    model = ParserModel(script)

    model.parse_data(Conversation())["request"] = "otra cosa"

    assert script[0] == {"request": "Change plan"}


def test_model_raises_clear_error_when_script_is_exhausted():
    model = ConversationModel(["Hi"])
    model.answer_user(Conversation())

    with pytest.raises(ScriptExhaustedError, match="turn 2"):
        model.answer_user(Conversation())


def test_conversation_keeps_messages_in_order():
    conversation = Conversation()
    conversation.add_user_message("Hi")
    conversation.add_agent_message("How can I help you?")

    assert [m.content for m in conversation.messages] == ["Hi", "How can I help you?"]
    assert len(conversation) == 2
