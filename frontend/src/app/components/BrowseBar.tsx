import { useMemo, useState } from "react";
import { List, Map as MapIcon } from "lucide-react";
import type { Catalog, CatalogPath } from "@/generated/contracts/catalog";
import { t } from "@/contracts/copy";
import { KIND_LABEL_KEY } from "@/contracts/exhaustive";
import { cn } from "@/lib/utils";
import {
  pathServiceArea,
  SERVICE_GROUPS,
  serviceOptions,
  type BrowseValue,
  type KindFilter,
  type ShowFilter,
} from "../lib/browse";

const AREAS: { id: string; label: string }[] = [
  { id: "all", label: t("browse.area_all") },
  { id: "ortho", label: "Bones & joints" },
  { id: "gi", label: "Stomach & colon" },
  { id: "skin", label: "Skin" },
];
const KINDS = Object.keys(KIND_LABEL_KEY) as (keyof typeof KIND_LABEL_KEY)[];

const field = "w-full rounded-lg border border-border bg-card px-2 py-1.5 text-sm";
const caption = "block text-[11px] font-medium text-muted-foreground";

/**
 * Browse without the AI: a service or CPT code (or a whole care path) from a dropdown, then filters on the
 * places. The code box narrows the dropdown; Enter picks the first match.
 */
export function BrowseBar({
  catalog,
  paths,
  value,
  onPick,
  kind,
  onKind,
  show,
  onShow,
  mode,
  onMode,
}: {
  catalog: Catalog | null;
  paths: CatalogPath[] | null;
  value: BrowseValue | "";
  onPick: (v: BrowseValue) => void;
  kind: KindFilter;
  onKind: (k: KindFilter) => void;
  show: ShowFilter;
  onShow: (s: ShowFilter) => void;
  /** the Map / List switch; left out in the Workspace sidebar, where the map is always the main canvas */
  mode?: "map" | "list";
  onMode?: (m: "map" | "list") => void;
}) {
  const [area, setArea] = useState("all");
  const [q, setQ] = useState("");
  const options = useMemo(() => serviceOptions(catalog, area, q), [catalog, area, q]);
  const pathOptions = useMemo(
    () => (q.trim() ? [] : (paths ?? []).filter((p) => area === "all" || pathServiceArea(p.area) === area)),
    [paths, area, q],
  );
  // the quote on screen stays selectable even when the area or the typed code hides it
  const shownValues = new Set<string>([...options.map((o) => o.value), ...pathOptions.map((p) => `path:${p.id}`)]);
  const currentLabel = useMemo(() => {
    if (!value || shownValues.has(value)) return null;
    if (value.startsWith("path:")) return paths?.find((p) => p.id === value.slice(5))?.title ?? null;
    return serviceOptions(catalog, "all", "").find((o) => o.value === value)?.label ?? null;
  }, [value, catalog, paths, options, pathOptions]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={cn("space-y-2", onMode && "rounded-xl border border-border bg-card/60 p-3")} data-testid="browse-bar">
      <div className={cn("grid gap-2", onMode ? "sm:grid-cols-[9rem_8rem_minmax(0,1fr)]" : "grid-cols-2")}>
        <label className="space-y-0.5">
          <span className={caption}>{t("browse.area")}</span>
          <select value={area} onChange={(e) => setArea(e.target.value)} className={field} data-testid="browse-area">
            {AREAS.map((a) => (
              <option key={a.id} value={a.id}>
                {a.label}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-0.5">
          <span className={caption}>CPT code</span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && options[0]) {
                e.preventDefault();
                onPick(options[0].value);
              }
            }}
            placeholder={t("browse.code_search")}
            className={field}
            data-testid="browse-code"
          />
        </label>
        <label className={cn("min-w-0 space-y-0.5", !onMode && "col-span-2")}>
          <span className={caption}>{t("browse.service")}</span>
          <select
            value={value}
            onChange={(e) => e.target.value && onPick(e.target.value as BrowseValue)}
            className={field}
            data-testid="browse-service"
          >
            {!value && <option value="">…</option>}
            {currentLabel && <option value={value}>{currentLabel}</option>}
            {pathOptions.length > 0 && (
              <optgroup label={t("browse.group_paths")}>
                {pathOptions.map((p) => (
                  <option key={p.id} value={`path:${p.id}`}>
                    {p.title}
                  </option>
                ))}
              </optgroup>
            )}
            {SERVICE_GROUPS.map((g) => {
              const opts = options.filter((o) => o.group === g);
              return opts.length ? (
                <optgroup key={g} label={t(`browse.group_${g}`)}>
                  {opts.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </optgroup>
              ) : null;
            })}
          </select>
          {q.trim() && options.length === 0 && <span className="text-[11px] text-warn">{t("browse.no_code")}</span>}
        </label>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="space-y-0.5">
          <span className={caption}>{t("browse.place_kind")}</span>
          <select value={kind} onChange={(e) => onKind(e.target.value as KindFilter)} className={field} data-testid="browse-kind">
            <option value="all">{t("browse.kind_all")}</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {t(KIND_LABEL_KEY[k])}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-0.5">
          <span className={caption}>{t("browse.show")}</span>
          <select value={show} onChange={(e) => onShow(e.target.value as ShowFilter)} className={field} data-testid="browse-show">
            <option value="offered">{t("browse.show_offered")}</option>
            <option value="priced">{t("browse.show_priced")}</option>
          </select>
        </label>
        {onMode && (
        <div className="ml-auto flex gap-1 rounded-lg bg-muted p-0.5 text-xs" role="radiogroup" aria-label="Show as">
          {(["map", "list"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              onClick={() => onMode(m)}
              className={cn("inline-flex items-center gap-1 rounded-md px-2.5 py-1 font-medium", mode === m ? "bg-card text-ink shadow-sm" : "text-muted-foreground")}
            >
              {m === "map" ? <MapIcon className="h-3.5 w-3.5" /> : <List className="h-3.5 w-3.5" />}
              {t(`browse.${m}`)}
            </button>
          ))}
        </div>
        )}
      </div>
    </div>
  );
}
