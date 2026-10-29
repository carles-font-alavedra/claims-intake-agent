# Conversational Agents

Conversational agents that, turn by turn, reply to the user, extract structured
data from the conversation and, when the business rules are met, execute an
action against an external (simulated) API.

- **`DebtAgent`**: registers payment commitments (`commitment_date` + `committed_amount`)
  at `POST https://api.example.com/debt/v1/commitment`.
- **`AssistanceAgent`**: registers requests for human agents (`request`)
  at `POST https://api.example.com/assistance/v1/request`.

## Getting started

Requires Python 3.10 or later. No runtime dependencies.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                       # 68 tests
ruff check . && ruff format --check .

AGENTS_API_TOKEN=test_token_9f3a2c1d python -m conversational_agents.demo
```

The demo runs one conversation with each agent and prints, turn by turn, the
decision taken and the HTTP requests that would have been sent.

## Usage

```python
from conversational_agents.factory import AgentFactory, Settings
from conversational_agents.http_client import FakeHttpClient
from conversational_agents.models import ConversationModel, ParserModel

factory = AgentFactory(Settings.from_env(), FakeHttpClient())
agent = factory.debt_agent(
    ConversationModel(["¿Cuándo podría pagar?", "Registrado, gracias."]),
    ParserModel([
        {"commitment_date": None, "committed_amount": None},
        {"commitment_date": "2030-01-15", "committed_amount": 150},
    ]),
)

agent.handle_turn("Hola")                      # outcome = NOT_REQUIRED
result = agent.handle_turn("El 15 de enero pago 150 €")  # outcome = EXECUTED
result.reply                                   # "Registrado, gracias."
```

## Architecture

```
src/conversational_agents/
├── conversation.py      Conversation / Message: conversation history
├── models.py            ConversationModel, ParserModel (simulated) + Protocols
├── validation.py        Validation and normalization of parsed fields
├── actions.py           Action (abstract), PaymentCommitment, AssistanceRequest
├── integrations.py      Integration (abstract), HttpIntegration, BearerTokenAuth
├── http_client.py       HttpRequest/HttpResponse, HttpClient (abstract), FakeHttpClient
├── agents/
│   ├── base.py          BaseAgent: turn lifecycle, deduplication
│   ├── debt.py          DebtAgent
│   └── assistance.py    AssistanceAgent
├── factory.py           Settings + AgentFactory: dependency composition
└── demo.py
```

Each layer has a single responsibility and only knows the layer below it through
an abstraction:

```
BaseAgent ──decides──▶ Action ──delivered by──▶ Integration ──uses──▶ HttpClient
   │                                             (HttpIntegration)     (FakeHttpClient)
   ├── ConversationModel.answer_user()
   └── ParserModel.parse_data()
```

| Component | Knows | Does **not** know |
|---|---|---|
| ConversationModel / ParserModel | How to reply to the user / extract data from the conversation | Business rules, that an API exists |
| Agent | Business rules: which fields it needs, when to act | URLs, HTTP, tokens |
| Action | The validated data of the action | How or where it is sent |
| Integration | How to build the request: URL, headers, auth | Business rules |
| HttpClient | How to send bytes | What they mean |
| AgentFactory | Which integration and URL each agent uses | — |

### Lifecycle of a turn (`BaseAgent.handle_turn`)

```
ConversationModel  →  ParserModel  →  Agent  →  Action  →  HttpIntegration
   (replies)        (extracts data)  (decides) (payload)      (sends)
```

1. The user's message is appended to the conversation.
2. `ConversationModel.answer_user(conversation)` generates the reply, which is also appended.
3. `ParserModel.parse_data(conversation)` returns a dict with the extracted data.
4. `build_action(parsed_data)` validates, normalizes and decides. It is **the only
   method each agent implements**, and it returns an `Action` or `None`.
5. If the action was already executed successfully in this conversation, it is not resent (`DUPLICATE`).
6. Otherwise it is executed through the `Integration`, which returns `EXECUTED` or `FAILED`.

The turn returns a `TurnResult` with the reply, the parsed data, the action and
its outcome (`NOT_REQUIRED`, `DUPLICATE`, `EXECUTED` or `FAILED`). That way the
caller, whether an orchestrator or the tests, can tell what happened without
inspecting internal state.

## Key decisions

**Template Method in `BaseAgent`.** The order of the steps is the same for every
agent and should not be breakable by a subclass. That is why `handle_turn` is
concrete and subclasses only implement `build_action`. A new agent is about ten
lines (see `tests/test_extensibility.py`).

**Dependency injection and a composition root.** Agents receive their models and
integration already built. All configuration (URLs, token, HTTP client) is
resolved in a single place, `AgentFactory`. This makes everything testable without
magic mocks (`unittest.mock.patch` does not appear in any test).

**Actions are immutable value objects.** `PaymentCommitment` and
`AssistanceRequest` are `dataclass(frozen=True)`: two actions with the same data
are equal and hashable, so deduplication is a plain `set`.

**Two-level deduplication.**
- Client side: the agent remembers actions executed **successfully** and does not repeat them.
  Since comparison happens after normalization, `150` and `150.0`, or `"Cambiar  tarifa"` and
  `"Cambiar tarifa"`, count as the same action.
- Server side: every request carries a deterministic `Idempotency-Key` header
  (hash of conversation + action). It covers the case the agent's memory cannot:
  the request reaches the server but the response is lost (timeout) and is retried.

**A failure does not break the turn.** `Integration.execute` reports delivery
problems as `ActionResult(success=False)` instead of raising. If the integration
fails (network error or non-2xx response), the user still gets their reply, the
outcome is `FAILED` and the action is not marked as executed. If the parser keeps
returning it on the next turn, it is retried with the same `Idempotency-Key`. A
response counts as success if `HttpResponse.ok` is true:

| `status_code` | `ok` |
|---|---|
| 200, 201 (any 2xx) | `True` |
| 400, 500 (anything else) | `False` |

**Models behind a `Protocol`.** The agent depends on `SupportsAnswerUser` and
`SupportsParseData`, not on the simulated classes. Any object with `answer_user`
or `parse_data` works, so a real LLM client plugs in without inheriting from
anything in the project or touching the agents.

**Injectable clock.** `DebtAgent` receives `today` (defaults to `date.today`) to
reject past dates. Tests pass a fixed date and do not depend on the day they run.

**The token does not leak.** `BearerTokenAuth.token` and `Settings.api_token` use
`field(repr=False)`, so they do not show up when the object is printed, in logs or
in tracebacks.

**Strict validation: invalid data equals missing data.** An action is never
executed with doubtful data. If the parser returns a date in another format, a
negative amount or a wrong type, a warning is logged and the field is treated as
`None`. The agent simply keeps the conversation going until it gets valid data.

**Abstract integrations.** The agent depends on `Integration`, not on HTTP. An
integration via a message queue, email or CRM requires no changes to any agent
(see `InMemoryQueueIntegration` in the tests). Authentication is also pluggable
(`Authenticator`).

## Design assumptions

| Question | Decision |
|---|---|
| What do `answer_user` and `parse_data` receive? | The full `Conversation`, as a real LLM would need. The simulated ones ignore it. |
| Does the parser return only data from the last message, or everything accumulated? | Everything accumulated. It is the natural behavior for an LLM with the history, and it spares the agent from merging partial data. |
| What counts as a "duplicate"? | The same action with the same normalized data in the same conversation. If the user changes the amount or asks for something else, it is a new action and is sent. |
| What goes in the body? | The same normalized data as in the headers, as JSON. |
| Past dates | A payment commitment dated before today is invalid. Today is valid. |
| Amounts | Positive, finite, rounded to cents. `bool` is rejected even though it is an `int` in Python. Strings such as `"150"` are rejected: the contract says `float`. |
| `None` values in headers | Omitted. |

### On sending parsed data as headers

The API contract asks for the parser's data to be sent as headers "with the same
names". I implemented it that way, but it carries risks I would raise with the API
team in a real setting:

- **Header injection and encoding.** `request` is free text from the user: it can
  contain line breaks or non-ASCII characters ("dirección"), and headers only allow
  printable ASCII. So values are normalized (whitespace and line breaks are
  collapsed) and also percent-encoded (`direcci%C3%B3n`). The body keeps the
  original value and is the source of truth.
- **Underscores in names.** Proxies such as nginx drop headers containing `_` by
  default (`underscores_in_headers off`), so `commitment_date` might never arrive.
  The convention would be `Commitment-Date` or `X-Commitment-Date`.
- **Size.** Servers limit header size (around 8 KB) and a long request could exceed it.
- **Personal data in logs.** Proxies and gateways usually log headers. Amounts,
  payment dates or the text of a request are personal data (GDPR), so in production
  they should not travel in headers.

My recommendation would be to send the data in the body only.

## Limitations and next steps

- **In-memory state.** Deduplication lives in the agent instance (one per
  conversation). If a conversation could continue in another process, that state
  would need to be persisted (Redis, a database). The `Idempotency-Key` already
  mitigates the risk on the server.
- **Not thread-safe.** Turns within a conversation are assumed to be sequential,
  as in a phone call.
- **Money as `float`.** The API contract is respected and amounts are rounded to
  cents. In production I would use `Decimal` internally.
- **Reply before action.** The turn lifecycle fixes the order: reply, parse, act.
  So the turn's reply cannot know whether the action was executed. An improvement
  would be to parse before replying, or to tell the `ConversationModel` the outcome
  on the next turn.
- **Retries.** An action is only retried if the parser returns it again on a later
  turn: if the conversation ends after a failure, the action is lost. For critical
  actions, the agent should put the action in a persistent queue (outbox pattern)
  and a separate worker should send it with exponential backoff, reusing the same
  `Idempotency-Key` and moving it to a dead-letter queue after N attempts. This fits
  as just another `Integration`, without touching the agents.
- **Changing commitments.** If the user goes from 300 € to 200 €, two commitments
  are registered via `POST`. If the business wants a single one per conversation,
  the API should offer an update (`PUT`/`PATCH`) of the existing commitment.
- **Agent ↔ parser contract.** The keys each agent expects are implicit in its
  `build_action`. An improvement would be for each agent to declare its fields
  (`required_fields`) and use them to configure the parser's prompt or schema, so
  the contract lives in one place.
- **One agent per conversation.** If a collections call needed to hand off to
  customer support, an orchestrator would have to pick the agent on each turn over
  the same `Conversation` (the constructor already accepts it). Deduplication would
  then move from the agent to the conversation.
- **Real HTTP client.** It would be enough to implement `HttpClient.send` with
  `httpx` or `requests`, mapping network errors to `HttpTransportError`.
