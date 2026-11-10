import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { ArrowLeftRight, Bot, Columns2, PanelLeftClose, PanelLeftOpen, Rows2 } from "lucide-react";
import { t } from "@/contracts/copy";
import { cn } from "@/lib/utils";

export type Orientation = "side" | "stack";

export interface SplitState {
  orientation: Orientation;
  /** false: chat first (left / top); true: prices first */
  swapped: boolean;
  /** Austin 2026-11-09: the AI helper folds to a thin strip so the prices get the width */
  chatCollapsed?: boolean;
}

export function useIsPhone(): boolean {
  const q = "(max-width: 767px)";
  const [phone, setPhone] = useState(() => typeof window !== "undefined" && window.matchMedia(q).matches);
  useEffect(() => {
    const mq = window.matchMedia(q);
    const sync = () => setPhone(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return phone;
}

/**
 * Phone tabs share the window's scroll. Remember each tab's scroll position and put it back when the
 * person returns to that tab, so going to Chat and back does not lose their place in the prices.
 */
function usePhoneTabScroll(phone: boolean, tab: "chat" | "prices") {
  const pos = useRef<Record<string, number>>({});
  const cur = useRef(tab);
  useEffect(() => {
    if (!phone) return;
    const onScroll = () => {
      pos.current[cur.current] = window.scrollY;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [phone]);
  useLayoutEffect(() => {
    if (!phone || cur.current === tab) return;
    cur.current = tab;
    window.scrollTo(0, pos.current[tab] ?? 0);
  }, [phone, tab]);
}

/**
 * D9: two panes like an iPad split. Side by side or stacked, either pane first ("swap" / "flip").
 * On a phone the panes become two tabs.
 */
export function SplitView({
  chat,
  prices,
  state,
  onState,
  phoneTab,
  onPhoneTab,
}: {
  chat: ReactNode;
  prices: ReactNode;
  state: SplitState;
  onState: (s: SplitState) => void;
  phoneTab: "chat" | "prices";
  onPhoneTab: (t: "chat" | "prices") => void;
}) {
  const phone = useIsPhone();
  usePhoneTabScroll(phone, phoneTab);

  if (phone) {
    return (
      <div className="flex flex-col" data-testid="split-view" data-layout="tabs">
        <div className="sticky top-[var(--header-h,0px)] z-20 grid grid-cols-2 border-b border-border bg-background" role="tablist">
          {(["chat", "prices"] as const).map((tab) => (
            <button
              key={tab}
              role="tab"
              aria-selected={phoneTab === tab}
              onClick={() => onPhoneTab(tab)}
              className={cn(
                "py-2.5 text-sm font-semibold",
                phoneTab === tab ? "border-b-2 border-ink text-ink" : "text-muted-foreground",
              )}
            >
              {tab === "chat" ? "Chat" : "Prices"}
            </button>
          ))}
        </div>
        {/* Both panes stay mounted (a hidden one keeps its state: map, picks, typed ZIP); only one shows. */}
        <div className="px-4 py-3">
          <div className="h-[calc(100vh-9rem)]" hidden={phoneTab !== "chat"} data-pane="chat">
            {chat}
          </div>
          <div hidden={phoneTab !== "prices"} data-pane="prices">
            {prices}
          </div>
        </div>
      </div>
    );
  }

  const side = state.orientation === "side";
  const collapsed = !!state.chatCollapsed;
  const setCollapsed = (c: boolean) => onState({ ...state, chatCollapsed: c });
  const chatBody = collapsed ? (
    <button
      type="button"
      onClick={() => setCollapsed(false)}
      title={t("chat.expand")}
      aria-label={t("chat.expand")}
      data-testid="chat-expand"
      className={cn(
        "flex items-center gap-2 rounded-xl text-xs font-medium text-ink hover:bg-muted",
        side ? "h-full w-full flex-col justify-start py-2" : "w-full px-2 py-1.5",
      )}
    >
      <PanelLeftOpen className={cn("h-4 w-4 shrink-0", !side && "rotate-90")} />
      <Bot className="h-4 w-4 shrink-0" />
      <span className={cn(side && "[writing-mode:vertical-rl]")}>{t("chat.helper")}</span>
    </button>
  ) : (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className="inline-flex items-center gap-1 font-medium text-muted-foreground">
          <Bot className="h-3.5 w-3.5" />
          {t("chat.helper")}
        </span>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          title={t("chat.collapse")}
          aria-label={t("chat.collapse")}
          data-testid="chat-collapse"
          className="rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-ink"
        >
          <PanelLeftClose className={cn("h-4 w-4", !side && "rotate-90", side && state.swapped && "rotate-180")} />
        </button>
      </div>
      <div className="min-h-0 flex-1">{chat}</div>
    </div>
  );
  const panes = state.swapped ? [prices, chatBody] : [chatBody, prices];
  const chatCol = collapsed ? "2.75rem" : "minmax(0,1fr)";
  return (
    <div data-testid="split-view" data-layout={state.orientation} data-swapped={state.swapped}>
      <div className="flex items-center justify-end gap-1 px-4 pt-2 text-xs" aria-label="Layout">
        <span className="mr-1 text-muted-foreground">Layout</span>
        <LayoutBtn on={side} onClick={() => onState({ ...state, orientation: "side" })} label="Side by side">
          <Columns2 className="h-3.5 w-3.5" />
        </LayoutBtn>
        <LayoutBtn on={!side} onClick={() => onState({ ...state, orientation: "stack" })} label="Stacked">
          <Rows2 className="h-3.5 w-3.5" />
        </LayoutBtn>
        <LayoutBtn on={false} onClick={() => onState({ ...state, swapped: !state.swapped })} label={side ? "Swap sides" : "Flip"}>
          <ArrowLeftRight className={cn("h-3.5 w-3.5", !side && "rotate-90")} />
        </LayoutBtn>
      </div>
      <div
        className={cn(
          "grid gap-4 px-4 py-3",
          !side && "grid-cols-1",
        )}
        style={side ? { gridTemplateColumns: state.swapped ? `minmax(0,1.5fr) ${chatCol}` : `${chatCol} minmax(0,1.5fr)` } : undefined}
      >
        {panes.map((p, i) => {
          const isChat = state.swapped ? i === 1 : i === 0;
          return (
            <section
              key={isChat ? "chat" : "prices"}
              data-pane={isChat ? "chat" : "prices"}
              className={cn(
                "min-w-0 rounded-2xl border border-border bg-background/60 p-3",
                isChat && side && "sticky top-20 h-[calc(100vh-7.5rem)]",
                isChat && !side && !collapsed && "h-[26rem]",
                isChat && collapsed && "p-1",
              )}
            >
              {p}
            </section>
          );
        })}
      </div>
    </div>
  );
}

function LayoutBtn({ on, onClick, label, children }: { on: boolean; onClick: () => void; label: string; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      title={label}
      className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-1", on ? "border-ink bg-ink text-white" : "border-border bg-card")}
    >
      {children}
      <span className="hidden lg:inline">{label}</span>
    </button>
  );
}
