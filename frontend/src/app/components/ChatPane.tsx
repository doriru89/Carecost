import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import { t } from "@/contracts/copy";
import { PAUSE_REASON_KEY, assertNever } from "@/contracts/exhaustive";
import type { CandidatePath, ChatResponse, ChipQuestion, ServiceRef } from "@/generated/contracts/chat_api";
import { cn } from "@/lib/utils";
import cardsJson from "../content/cards.json";
import questionsJson from "../content/questions.json";
import { GlossaryChips } from "./Glossary";

const CARDS = (cardsJson as { cards: Record<string, { title: string; text: string }> }).cards;
const QUESTIONS = (questionsJson as { questions: Record<string, { text: string; answers: Record<string, string> }> }).questions;

export type ChatTurn = { role: "user"; text: string } | { role: "assistant"; res: ChatResponse };

export interface ChatActions {
  send(text: string): void;
  answer(questionId: string, values: string[], labels: string[]): void;
  pickPath(c: CandidatePath): void;
  pickService(s: ServiceRef): void;
  browse(): void;
}

export function ChatPane({
  turns,
  busy,
  error,
  answers,
  actions,
  activePathId,
}: {
  turns: ChatTurn[];
  busy: boolean;
  error: string | null;
  answers: Record<string, string[]>;
  actions: ChatActions;
  activePathId: string | null;
}) {
  const [draft, setDraft] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [turns.length, busy]);

  const submit = () => {
    const text = draft.trim();
    if (!text || busy) return;
    actions.send(text);
    setDraft("");
  };

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="chat-pane">
      <div className="flex-1 min-h-0 space-y-3 overflow-y-auto pr-1">
        {turns.map((turn, i) =>
          turn.role === "user" ? (
            <div key={i} className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-ink px-3 py-2 text-sm text-white">
              {turn.text}
            </div>
          ) : (
            <AssistantTurn
              key={i}
              res={turn.res}
              answers={answers}
              actions={actions}
              latest={i === turns.length - 1}
              activePathId={activePathId}
            />
          ),
        )}
        {busy && <p className="text-xs text-muted-foreground animate-pulse">Thinking…</p>}
        {error && <p className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-800">{error}</p>}
        <div ref={end} />
      </div>
      <form
        className="mt-3 flex items-end gap-2 rounded-2xl border border-border bg-card p-2"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={2}
          maxLength={1000}
          placeholder="Ask a follow-up or describe more…"
          className="flex-1 resize-none bg-transparent px-2 py-1 text-sm outline-none"
          aria-label="Message"
        />
        <button type="submit" disabled={busy || !draft.trim()} className="rounded-full bg-ink p-2 text-white disabled:opacity-40" aria-label="Send">
          <Send className="h-4 w-4" />
        </button>
      </form>
    </div>
  );
}

function Bubble({ children }: { children: React.ReactNode }) {
  return <div className="max-w-[95%] space-y-2 rounded-2xl rounded-bl-sm bg-muted px-3 py-2 text-sm">{children}</div>;
}

function CopyKeys({ keys }: { keys: string[] }) {
  if (!keys.length) return null;
  return (
    <div className="space-y-1 border-t border-border pt-2 text-xs text-muted-foreground" data-testid="d33-copy">
      {keys.map((k) => (
        <p key={k}>{t(k)}</p>
      ))}
    </div>
  );
}

function Cards({ ids }: { ids: string[] }) {
  const known = ids.filter((id) => CARDS[id]);
  if (!known.length) return null;
  return (
    <div className="space-y-1.5">
      {known.map((id) => (
        <div key={id} className="rounded-lg border border-border bg-card p-2 text-xs">
          <p className="font-semibold">{CARDS[id].title}</p>
          <p className="text-muted-foreground">{CARDS[id].text}</p>
        </div>
      ))}
    </div>
  );
}

function Candidates({
  list,
  actions,
  activePathId,
}: {
  list: CandidatePath[];
  actions: ChatActions;
  activePathId: string | null;
}) {
  if (!list.length) return null;
  return (
    <div className="space-y-1.5">
      {list.map((c) => (
        <div key={c.path_id} className={cn("rounded-lg border bg-card p-2", c.path_id === activePathId ? "border-ink" : "border-border")}>
          <p className="text-sm font-medium">{c.title}</p>
          {c.review_status !== "approved" && <p className="text-[11px] text-warn">{t("notice.care_path_draft")}</p>}
          {c.because.length > 0 && (
            <p className="text-[11px] text-muted-foreground" data-testid="because">
              Because you said: {c.because.map((b) => b.label.en).join(" · ")}
            </p>
          )}
          <button
            type="button"
            onClick={() => actions.pickPath(c)}
            className="mt-1 rounded-full bg-ink px-3 py-1 text-xs font-medium text-white"
          >
            {c.path_id === activePathId ? "Showing prices" : "See prices"}
          </button>
        </div>
      ))}
    </div>
  );
}

function Questions({
  questions,
  answers,
  actions,
  enabled,
}: {
  questions: ChipQuestion[];
  answers: Record<string, string[]>;
  actions: ChatActions;
  enabled: boolean;
}) {
  const [multi, setMulti] = useState<Record<string, string[]>>({});
  return (
    <div className="space-y-2">
      {questions.map((q) => {
        const chosen = answers[q.question_id] ?? [];
        return (
          <div key={q.question_id}>
            <p className="font-medium">{q.text.en}</p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {q.answers.map((a) => {
                const on = (q.multi ? multi[q.question_id] ?? [] : chosen).includes(a.value) || chosen.includes(a.value);
                return (
                  <button
                    key={a.value}
                    type="button"
                    disabled={!enabled}
                    data-testid="chip"
                    onClick={() => {
                      if (!q.multi) return actions.answer(q.question_id, [a.value], [a.label.en]);
                      setMulti((m) => {
                        const cur = m[q.question_id] ?? [];
                        return { ...m, [q.question_id]: cur.includes(a.value) ? cur.filter((v) => v !== a.value) : [...cur, a.value] };
                      });
                    }}
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs",
                      on ? "border-ink bg-ink text-white" : "border-border bg-card hover:border-ink/50",
                      !enabled && "opacity-60",
                    )}
                  >
                    {a.label.en}
                  </button>
                );
              })}
              {q.multi && enabled && (
                <button
                  type="button"
                  className="rounded-full border border-ink px-3 py-1 text-xs font-medium"
                  onClick={() => {
                    const vals = multi[q.question_id] ?? [];
                    if (vals.length)
                      actions.answer(q.question_id, vals, q.answers.filter((a) => vals.includes(a.value)).map((a) => a.label.en));
                  }}
                >
                  Done
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Understood({ items }: { items: { question_id: string; value: string; evidence: string }[] }) {
  if (!items.length) return null;
  return (
    <p className="text-xs text-muted-foreground" data-testid="understood">
      I understood:{" "}
      {items.map((u, i) => (
        <span key={u.question_id}>
          {i > 0 && " · "}
          <span className="font-medium text-foreground">{QUESTIONS[u.question_id]?.answers[u.value] ?? u.value}</span> (“{u.evidence}”)
        </span>
      ))}
    </p>
  );
}

function AssistantTurn({
  res,
  answers,
  actions,
  latest,
  activePathId,
}: {
  res: ChatResponse;
  answers: Record<string, string[]>;
  actions: ChatActions;
  latest: boolean;
  activePathId: string | null;
}) {
  const r = res.reply;
  switch (r.kind) {
    case "red_flag":
      return (
        <Bubble>
          <p className="font-semibold">{r.headline.en}</p>
          <p>{r.text.en}</p>
        </Bubble>
      );
    case "clarify":
      return (
        <Bubble>
          {r.lead_in && <p>{r.lead_in}</p>}
          <Understood items={r.understood} />
          <Questions questions={r.questions} answers={answers} actions={actions} enabled={latest} />
          <Candidates list={r.candidates} actions={actions} activePathId={activePathId} />
          <Cards ids={r.card_ids} />
          <CopyKeys keys={r.copy_keys} />
        </Bubble>
      );
    case "care_paths":
      return (
        <Bubble>
          <p>{r.text}</p>
          <Understood items={r.understood} />
          <Candidates list={r.candidates} actions={actions} activePathId={activePathId} />
          <Cards ids={r.card_ids} />
          <CopyKeys keys={r.copy_keys} />
        </Bubble>
      );
    case "text":
      return (
        <Bubble>
          <p>{r.text}</p>
          {r.services.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {r.services.map((s) => (
                <button
                  key={s.service_id}
                  type="button"
                  onClick={() => actions.pickService(s)}
                  className="rounded-full border border-dashed border-ink px-3 py-1 text-xs"
                  title="Suggested by the AI: shown, never added to a total"
                >
                  ✦ Price: {s.plain_name}
                </button>
              ))}
            </div>
          )}
          <GlossaryChips keys={r.glossary_keys} />
          <Cards ids={r.card_ids} />
        </Bubble>
      );
    case "llm_invalid":
      return (
        <Bubble>
          <p>{t(r.message_key)}</p>
          <BrowseButton onClick={actions.browse} />
        </Bubble>
      );
    case "ai_paused":
      return (
        <Bubble>
          <p>{t(PAUSE_REASON_KEY[r.reason])}</p>
          {r.resumes_at && <p className="text-xs text-muted-foreground">Back after {new Date(r.resumes_at).toLocaleString()}</p>}
          <BrowseButton onClick={actions.browse} />
        </Bubble>
      );
    default:
      return assertNever(r);
  }
}

function BrowseButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="rounded-full border border-ink px-3 py-1 text-xs font-medium">
      {t("start.skip_ai")}
    </button>
  );
}
