# Chat (AI navigation): `POST /api/chat`

The AI only phrases things. Codes, dollars, routing, chips, the "because" list and the reply kind
are decided by code from the content files (`data/questions/questions.yaml`,
`data/redflags/redflags.json`, `data/care_paths/paths/*.yaml`, the catalog). The response is
`app.chat.contracts.ChatResponse`, validated once with a `ChatContext`; the route has no
`response_model`.

## Order of one turn (`backend/app/chat/service.py`)

1. **Identity.** Client IP from one configured trusted proxy header (else the socket peer); IPv6
   keyed by its /64; IP and email HMAC-SHA256'd with `CARECOST_CHAT_HMAC_SECRET`. Raw values are
   never stored.
2. **Turn count.** The server issues the conversation id and counts turns (SQLite). An unknown id,
   or one issued to another IP, starts a new conversation.
3. **Red flags, code only** (`redflags.screen_text` over every user turn). A hit is a `red_flag`
   reply with no LLM call. It runs before the budget and the conversation cap on purpose: a person
   over a cap who writes about suicide still gets the 988 page (the contract was changed to allow a
   code red flag past turn 12).
4. **Conversation cap** (12 turns, contract constant) -> `ai_paused(conversation_cap)`.
5. **Not configured** (no key, no HMAC secret, provider `off`, no price for the model) ->
   `ai_paused(provider_unavailable)`. Browsing prices still works (D3).
6. **Budget.** Reserve the worst-case cost of the call in the ledger (atomic), else
   `ai_paused(ip_daily_cap | wallet_exhausted)`.
7. **LLM** (at most 2 attempts, both reserved and settled). The model fills one JSON object:
   understood answers (verbatim evidence), which allowed question to ask, ai_ranked path ids,
   catalog service ids, glossary keys, one short message, and an optional escalation. Escalation
   goes through `redflags.combine()` (one way up only). The service builds the reply; a reply that
   fails the chat guard or the contract is retried once with the error, then `llm_invalid`.

How the reply kind is chosen (code):

| Condition | Reply |
|---|---|
| `focus` set (a receipt line) | `text` with `focus_line_id`; the step's own plain text is pasted into the prompt |
| Q1 = other, or no question left and no path | `text` (+ live cards, catalog services) |
| a question can still change the path | `clarify`, ONE chip question (voice rule), candidates if any |
| chip answers match a path and the model asks nothing more | `care_paths` |

- `entry_matched` candidates come from the person's chip answers; `because` = those answers,
  labels verbatim from questions.yaml (D33). Paths matched only through the model's `understood`
  answers, or named by the model, are `ai_ranked` with an empty `because`.
- Turn 1 with nothing specific (no path matches even with the model's understood answers): the
  model's path guesses are dropped, so the first reply is a question (voice rule: two exchanges
  unless the first message is specific).
- The model may pick only from `allowed_next_questions` (distinguishing questions for the paths
  still possible, then refining questions of matched paths; never Q0 or Q14). A pick outside the
  set is replaced by the code's first distinguishing question and its sentence is not shown.

## D33 explanation

- Condition names: the contract's LlmText filter + deny-list (`data/chat/condition_names.yaml`).
  **Stronger cheap check (added, `backend/app/chat/guard.py`):** any word that has the shape of a
  condition name (-itis, -osis, -oma, -pathy, -algia, -emia, -ectomy, -plasia; syndrome, disease,
  disorder, cancer, tumor, tear, torn, infection, fracture, hernia, lesion, cyst; Chinese 癌 / 炎 /
  瘤 / 综合征) must appear in the reviewed text (title, intro, glossary terms) of a path the reply
  shows. It catches "osteonecrosis", "SLAP lesion", "thoracic outlet syndrome", "肩周炎", none of
  which the deny-list has. Cost: a regex per reply; a false positive costs one retry. Proposal:
  move it into the contract next to the deny-list.
- **Diagnostic cue rule (review 2026-10-24):** a cue phrase (might/could/may be, sounds/looks
  like, you probably have, likely, probably, consistent with, suggests, 可能是, 像是, 大概是 ...)
  must be followed within 5 words (8 characters in Chinese) by a word from the shown paths'
  reviewed text. A turn with no path shown has no such text, so every cue is rejected there. This
  catches "It might be a pinched nerve in your neck", which has no condition-shaped word.
  False positives on the 9 good messages available (contract fixtures + test messages): 0.
- **Money in words (review 2026-10-24):** dollar(s), buck(s), usd, cent(s), grand, 美元, 美金,
  块钱, 人民币, 元 (not 单元 / 公元 / 元素) are rejected with or without a number. LlmText already
  rejected symbols and number + unit.
- **No digits (review round 2, Austin option A):** any ASCII or full-width digit (０-９) in model
  text is rejected and retried ("The visit runs roughly 150"). Chinese number words stay allowed
  unless a currency unit follows. Austin accepts the residual risk of crafted sentences without
  digits or currency words ("a few hundred out of pocket", "a classic case of a pinched nerve")
  and over-rejections of good sentences ("It could be helpful to know..."); he judges them from the
  review log during local testing.
- **Re-asking with paths shown:** when a clarify reply shows candidates and `understood` answers,
  a lead_in that ends with a question mark is dropped (the chip already carries the question).
  Proxy for "asks for an answer already understood" (live zh run: "请确认疼痛的具体部位？").
- The model's message is checked even when the service decides not to show it.
- Fixed copy: `copy.not_a_diagnosis` + `copy.when_to_see_a_doctor` on every reply with candidates
  (contract). Proposed wording in `data/chat/copy.yaml` (pending Austin + 1 reader, P10); the UI copy
  file is stream D's.
- The receipt-line Why texts are untouched.

## Voice rules (Kenza 2026-04, `git show b4c63f3:backend/app/services/gi_symptom_refinement.py`)

Borrowed into `backend/app/chat/prompt.py` (voice only, D32): no stock acknowledgements (also
enforced: `guard.check_voice` rejects openers like "I understand", "Thanks for sharing", "Got it",
"明白"), one focused question per turn (enforced: one chip), ask one distinguishing question when
unsure (enforced: the allowed set), two exchanges unless specific (enforced for turn 1, above).

## LLM (D26, D15)

- Provider `gemini` (default): `models.generateContent`, JSON forced with `responseMimeType` +
  `responseSchema`, key in the `x-goog-api-key` header. Model `gemini-3.8-flash`, the page's "New
  Stable" and recommended Flash for new projects (2.5 models are limited to users who used them
  before). Source: https://ai.google.dev/gemini-api/docs/models (Last updated 2026-10-22 UTC, read
  2026-10-24).
- Price (paid tier, per 1M tokens, text): input $0.75, output incl. thinking $3.75 through
  2026-12-31; $1.50 / $7.50 from 2027-01-01. Paid-tier content is not used to improve Google
  products; free-tier content is. Source: https://ai.google.dev/gemini-api/docs/pricing (Last
  updated 2026-10-22 UTC, read 2026-10-24). The table is `PRICES` in `backend/app/chat/llm.py`.
- Thinking: `thinkingConfig.thinkingLevel = "low"` (thinking defaults to medium on 3.8 Flash and
  counts toward `maxOutputTokens` and output billing, per
  https://ai.google.dev/gemini-api/docs/thinking, Last updated 2026-10-14). That page documents it
  for the Interactions API; the generateContent field name is unverified until the live smoke runs.
  `CARECOST_GEMINI_THINKING_LEVEL=""` omits it.
- Lava switch: `CARECOST_CHAT_PROVIDER=lava` + `CARECOST_LAVA_API_KEY` uses Lava's
  OpenAI-compatible `/v1/chat/completions` (the 2026-04 call shape).
- Prompt size, measured 2026-10-24 on a turn-1 shoulder request with the fixture catalog: 12,712
  chars (about 3.2k tokens at 4 chars/token; the reservation's upper-bound estimate is 4,303). The
  hold per attempt is $0.0071 (4,303 in + 1,024 out at $0.75 / $3.75). Real per-turn cost is lower
  and is measured by the live smoke.

## Limits (D2, P8)

| Limit | Default | Env var | Where |
|---|---|---|---|
| per hashed IP, per provider day: soft | $1.00 (state `over_soft_cap`; `near_soft_cap` from $0.80) | `CARECOST_CHAT_IP_SOFT_USD` | ledger |
| per hashed IP: hard stop | $2.00 -> `ai_paused(ip_daily_cap)` | `CARECOST_CHAT_IP_HARD_USD` | ledger |
| all IPs together, per provider day | $5.00 -> `ai_paused(wallet_exhausted)` | `CARECOST_CHAT_GLOBAL_DAILY_USD` | ledger |
| LLM turns per hashed IP per day | 40 | `CARECOST_CHAT_IP_TURN_CAP` | ledger |
| turns per conversation | 12 | contract constant | ledger |
| LLM attempts per turn | 2 (both charged) | contract constant | service |
| email before AI use | required, unverified | contract (`EmailStr`) | request |

- Provider day = midnight America/Los_Angeles (Gemini's quota reset).
- Reserve before each call (worst case: estimated input + `maxOutputTokens`), settle with the
  provider's `usageMetadata` (thinking tokens counted as output). An unsettled hold counts as spent.
  Check + insert in one `BEGIN IMMEDIATE` transaction: no double spend across threads or workers.
- A provider error settles at $0, a timeout at the full hold (it may have been billed).

## Review log (local testing only)

Off by default. `CARECOST_CHAT_REVIEW_LOG=1` writes one JSON line per model attempt to
`CARECOST_CHAT_REVIEW_LOG_PATH` (default `carecost_chat_review.jsonl` in Python's temp dir; set
it explicitly when reviewing):
`ts`, `conversation_hash` (HMAC of the conversation id), `turn`, `attempt`, `message` (the model's
raw message), `outcome` (`shown` / `accepted_not_shown` / `rejected` / `provider_error`), `rule`
(`parse`, `voice`, `digits`, `money`, `condition_shapes`, `diagnostic_cues`, `contract`, `build`),
`reason`, `final_kind`. Never logged: the person's text, history, email, IP, chip answers, the
prompt, or unparsed model output (it may quote the person); contract reasons keep pydantic's
location + message, not the input value. A test dumps the whole log and checks the user text,
email and IP are absent.

Print the rejected lines:

```bash
jq -c 'select(.outcome == "rejected") | {ts, turn, attempt, rule, message, reason}' \
  "$CARECOST_CHAT_REVIEW_LOG_PATH"
```

## Env vars

All in `backend/app/chat/config.py` (docstring table). Required in production:
`CARECOST_GEMINI_API_KEY`, `CARECOST_CHAT_HMAC_SECRET` (any long random string),
`CARECOST_CHAT_LEDGER_PATH` (a path on the Railway volume, e.g. `/data/chat_ledger.sqlite`), and
`CARECOST_TRUSTED_PROXY_HEADER=X-Forwarded-For` + `CARECOST_TRUSTED_PROXY_HOPS=1` if Railway's edge
appends exactly one entry (verify on the deployed service before relying on it; if the hop count is
wrong, every visitor shares one key or a client can choose its own).

## Run locally (port 8101)

```bash
cd backend
# tests (no network, no key: every LLM is a FakeClient)
uv run --frozen --extra dev pytest -q -p no:cacheprovider tests/chat tests/contracts

# the router on a tiny local app (stream C's factory mounts the same router at /api)
CARECOST_CHAT_HMAC_SECRET=dev-only-secret CARECOST_CHAT_LEDGER_PATH=/tmp/cc_chat.sqlite \
  uv run --frozen uvicorn app.chat.local_app:app --host 127.0.0.1 --port 8101

curl -s -X POST http://127.0.0.1:8101/api/chat -H 'content-type: application/json' -d '{
  "conversation_id": null, "text": "My shoulder clicks", "payment": {"kind": "cash"},
  "email": "a@example.com", "answers": {}, "history": [], "focus": null, "locale": "en"}'

# live smoke (orchestrator only, key injected from env; spends at most --max-usd)
CARECOST_GEMINI_API_KEY=... uv run --frozen python -m app.chat.smoke_live --max-usd 0.20
```

## Spend cap (Austin, in Google AI Studio)

From https://ai.google.dev/gemini-api/docs/billing (Last updated 2026-09-28 UTC, read 2026-10-24):

1. Use an account with the project editor, owner or admin role.
2. Open Google AI Studio -> **Spend** page, with the CareCost project selected.
3. Under **Monthly spend cap**, click **Edit spend cap**.
4. Enter the monthly cap (suggested: $15, about 3x the expected $2–12/month) and save.

Caveats from the same page: project caps are experimental; billing data can lag about 10 minutes, so
spend can pass the cap in that window. The billing account's tier cap (Tier 1: $250/month) applies
on top and pauses every project on that account. The app's own ledger caps (above) are the
first line; the console cap is the backstop.
