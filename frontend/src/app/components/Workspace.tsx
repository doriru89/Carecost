import { useEffect, useRef, type ReactNode } from "react";
import { ChevronDown, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { useIsPhone } from "../lib/useIsPhone";

export interface Section {
  id: string;
  title: string;
  icon: LucideIcon;
  /** a short status shown on the header while the section is closed (e.g. "73221 · Hospitals") */
  summary?: string | null;
  content: ReactNode;
}

/**
 * Austin 2026-11-09: the map is the main canvas; everything else (AI helper, Browse, Where to go, List,
 * Breakdown) is a section of one sidebar, stacked, several open at once. The sidebar folds to a rail of
 * icons; on a phone the map comes first and the sections stack under it.
 * `focus` (a section id + a counter) scrolls that section into view when it changes (a pin opens Breakdown).
 */
export function Workspace({
  head,
  sections,
  open,
  onToggle,
  map,
  collapsed,
  onCollapsed,
  focus,
}: {
  /** above the sections: the controls every section shares (payment, ZIP) */
  head: ReactNode;
  sections: Section[];
  open: Record<string, boolean>;
  onToggle: (id: string, open: boolean) => void;
  map: ReactNode;
  collapsed: boolean;
  onCollapsed: (c: boolean) => void;
  focus?: { id: string; n: number } | null;
}) {
  const phone = useIsPhone();
  const refs = useRef<Record<string, HTMLElement | null>>({});
  useEffect(() => {
    if (!focus) return;
    refs.current[focus.id]?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, [focus]);

  const list = (
    <div className="space-y-2" data-testid="sidebar-sections">
      {sections.map((s) => {
        const isOpen = !!open[s.id];
        const Icon = s.icon;
        return (
          <section
            key={s.id}
            ref={(el) => {
              refs.current[s.id] = el;
            }}
            className="scroll-mt-14 rounded-xl border border-border bg-card"
            data-testid="sidebar-section"
            data-section={s.id}
            data-open={isOpen}
          >
            <button
              type="button"
              onClick={() => onToggle(s.id, !isOpen)}
              aria-expanded={isOpen}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm font-semibold text-ink"
            >
              <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="shrink-0">{s.title}</span>
              {!isOpen && s.summary && <span className="min-w-0 truncate text-xs font-normal text-muted-foreground">{s.summary}</span>}
              <ChevronDown className={cn("ml-auto h-4 w-4 shrink-0 text-muted-foreground transition-transform", !isOpen && "-rotate-90")} />
            </button>
            {/* a closed section stays mounted (chat history, typed code, map state survive) */}
            <div className="border-t border-border px-3 py-2" hidden={!isOpen}>
              {s.content}
            </div>
          </section>
        );
      })}
    </div>
  );

  if (phone) {
    return (
      <div className="space-y-3 px-3 py-3" data-testid="workspace-layout" data-layout="phone">
        <div data-testid="main-map">{map}</div>
        {head}
        {list}
      </div>
    );
  }

  return (
    <div
      className="grid gap-3 px-3 py-3"
      style={{ gridTemplateColumns: collapsed ? "2.75rem minmax(0,1fr)" : "minmax(22rem,28rem) minmax(0,1fr)" }}
      data-testid="workspace-layout"
      data-layout="desktop"
      data-collapsed={collapsed}
    >
      <aside className="sticky top-14 h-[calc(100vh-4.25rem)] min-w-0" data-testid="sidebar">
        {collapsed ? (
          <div className="flex h-full flex-col items-center gap-1 rounded-xl border border-border bg-card py-2">
            <button type="button" onClick={() => onCollapsed(false)} title="Show the sidebar" aria-label="Show the sidebar" className="rounded-md p-1.5 text-muted-foreground hover:bg-muted" data-testid="sidebar-expand">
              <PanelLeftOpen className="h-4 w-4" />
            </button>
            {sections.map((s) => {
              const Icon = s.icon;
              return (
                <button
                  key={s.id}
                  type="button"
                  title={s.title}
                  aria-label={s.title}
                  onClick={() => {
                    onCollapsed(false);
                    onToggle(s.id, true);
                  }}
                  className={cn("rounded-md p-1.5 hover:bg-muted", open[s.id] ? "text-ink" : "text-muted-foreground")}
                >
                  <Icon className="h-4 w-4" />
                </button>
              );
            })}
          </div>
        ) : (
          <div className="flex h-full flex-col gap-2 overflow-y-auto pr-1">
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">{head}</div>
              <button type="button" onClick={() => onCollapsed(true)} title="Hide the sidebar" aria-label="Hide the sidebar" className="rounded-md p-1.5 text-muted-foreground hover:bg-muted" data-testid="sidebar-collapse">
                <PanelLeftClose className="h-4 w-4" />
              </button>
            </div>
            {list}
          </div>
        )}
      </aside>
      <div className="min-w-0" data-testid="main-map">
        {map}
      </div>
    </div>
  );
}
