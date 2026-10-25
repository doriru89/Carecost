import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ChatResponse } from "@/generated/contracts/chat_api";
import { t } from "@/contracts/copy";
import { ChatPane, type ChatActions } from "../components/ChatPane";
import paused from "../../../../contracts/fixtures/chat_ai_paused.json";

const actions = (): ChatActions => ({ send: vi.fn(), answer: vi.fn(), pickPath: vi.fn(), pickService: vi.fn(), browse: vi.fn() });

describe("chat states in api mode", () => {
  it("ai_paused(provider_unavailable), what the server sends with no key: fixed copy, no time, browse prices", () => {
    // the Chat service's _paused("provider_unavailable", None) (wave2/chat backend/app/chat/service.py)
    const res = {
      ...(paused as unknown as ChatResponse),
      llm_called: false,
      reply: { kind: "ai_paused", reason: "provider_unavailable", message_key: "ai.paused_provider", resumes_at: null, browse_prices_available: true },
    } as ChatResponse;
    const a = actions();
    render(<ChatPane turns={[{ role: "user", text: "my shoulder clicks" }, { role: "assistant", res }]} busy={false} error={null} answers={{}} actions={a} activePathId={null} />);
    expect(screen.getByText(t("ai.paused_provider"))).toBeTruthy();
    expect(screen.queryByText(/Back after/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: t("start.skip_ai") }));
    expect(a.browse).toHaveBeenCalledOnce();
  });

  it("a chat route that fails (the merged base has no /api/chat yet: 404) shows a plain error with browse prices", () => {
    const a = actions();
    render(<ChatPane turns={[]} busy={false} error={t("chat.unreachable", { status: 404 })} answers={{}} actions={a} activePathId={null} />);
    expect(screen.getByTestId("chat-error").textContent).toMatch(/could not answer \(server error 404\)/);
    fireEvent.click(screen.getByRole("button", { name: t("start.skip_ai") }));
    expect(a.browse).toHaveBeenCalledOnce();
  });
});
