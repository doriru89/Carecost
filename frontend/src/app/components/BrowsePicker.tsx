import { useMemo, useState } from "react";
import type { Catalog, CatalogService } from "@/generated/contracts/catalog";
import { cn } from "@/lib/utils";
import { t } from "@/contracts/copy";

const AREA_LABEL: Record<string, string> = {
  msk_shoulder: "Shoulder",
  msk_knee: "Knee",
  msk_back: "Back",
  msk_ankle: "Ankle",
  skin: "Skin",
  gi_upper: "Stomach (upper)",
  gi_lower: "Colon",
};

/**
 * D3 "Skip AI → Browse prices": pick a care path, or a single service from the catalog.
 * Names come from the catalog (plain name first, technical name small, D8).
 */
export function BrowsePicker({
  catalog,
  onPickPath,
  onPickService,
}: {
  catalog: Catalog | null;
  onPickPath: (pathId: string) => void;
  onPickService: (svc: CatalogService) => void;
}) {
  const [q, setQ] = useState("");
  const services = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!catalog) return [];
    return catalog.services.filter(
      (x) =>
        !s ||
        x.plain_name.toLowerCase().includes(s) ||
        x.technical_name.toLowerCase().includes(s) ||
        x.codes.some((c) => c.code.includes(s)),
    );
  }, [catalog, q]);

  if (!catalog) return <p className="text-sm text-muted-foreground">Loading the list of care…</p>;
  return (
    <div className="space-y-5" data-testid="browse-picker">
      <section>
        <h3 className="text-sm font-semibold mb-2">Common problems we price step by step</h3>
        <div className="grid gap-2 sm:grid-cols-2">
          {catalog.care_paths.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => onPickPath(p.id)}
              className="rounded-xl border border-border bg-card p-3 text-left hover:border-ink/50"
            >
              <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                {AREA_LABEL[p.area] ?? p.area}
              </span>
              <span className="block text-sm font-medium leading-snug">{p.title}</span>
              {p.review_status !== "approved" && <span className="text-[11px] text-warn">{t("notice.care_path_draft")}</span>}
            </button>
          ))}
        </div>
      </section>
      <section>
        <h3 className="text-sm font-semibold mb-2">Or price one service</h3>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search: X-ray, MRI, colonoscopy, 73030…"
          className="w-full rounded-xl border border-border bg-card px-3 py-2 text-sm"
          aria-label="Search services"
        />
        <ul className="mt-2 divide-y divide-border rounded-xl border border-border bg-card">
          {services.map((s) => (
            <li key={s.service_id}>
              <button
                type="button"
                onClick={() => onPickService(s)}
                className={cn("w-full px-3 py-2 text-left hover:bg-muted")}
              >
                <span className="block text-sm font-medium">{s.plain_name}</span>
                <span className="block text-[11px] text-muted-foreground">
                  {s.technical_name} · {s.codes.map((c) => c.code).join(", ")}
                </span>
              </button>
            </li>
          ))}
          {services.length === 0 && <li className="px-3 py-2 text-sm text-muted-foreground">No match.</li>}
        </ul>
      </section>
    </div>
  );
}
