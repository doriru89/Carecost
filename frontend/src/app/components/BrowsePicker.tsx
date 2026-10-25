import { useEffect, useMemo, useState } from "react";
import type { Catalog, CatalogPath, CatalogService } from "@/generated/contracts/catalog";
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
 * D3 "Skip AI → Browse prices", in the server's two picker steps: a care path
 * (GET /api/catalog/paths), then its services (GET /api/catalog/paths/{id}/services), priced as the
 * whole path or one service. The search box looks across the full catalog (GET /api/catalog).
 * Names come from the catalog (plain name first, technical name small, D8).
 */
export function BrowsePicker({
  catalog,
  paths,
  loadServices,
  onPickPath,
  onPickService,
}: {
  catalog: Catalog | null;
  paths: CatalogPath[] | null;
  loadServices: (pathId: string) => Promise<CatalogService[]>;
  onPickPath: (pathId: string) => void;
  onPickService: (svc: CatalogService) => void;
}) {
  const [q, setQ] = useState("");
  const [openPath, setOpenPath] = useState<string | null>(null);
  const [pathServices, setPathServices] = useState<{ id: string; services: CatalogService[] | null; error?: string } | null>(null);
  useEffect(() => {
    if (!openPath) return;
    let live = true;
    setPathServices({ id: openPath, services: null });
    loadServices(openPath).then(
      (services) => live && setPathServices({ id: openPath, services }),
      (e: unknown) => live && setPathServices({ id: openPath, services: [], error: e instanceof Error ? e.message : String(e) }),
    );
    return () => {
      live = false;
    };
  }, [openPath, loadServices]);
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

  if (!paths) return <p className="text-sm text-muted-foreground">Loading the list of care…</p>;
  return (
    <div className="space-y-5" data-testid="browse-picker">
      <section>
        <h3 className="text-sm font-semibold mb-2">Common problems we price step by step</h3>
        <div className="grid gap-2 sm:grid-cols-2">
          {paths.map((p) => (
            <div
              key={p.id}
              className={cn("rounded-xl border bg-card p-3 text-left", openPath === p.id ? "border-ink sm:col-span-2" : "border-border")}
              data-testid="browse-path"
            >
              <button type="button" onClick={() => setOpenPath(openPath === p.id ? null : p.id)} className="w-full text-left" aria-expanded={openPath === p.id}>
                <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  {AREA_LABEL[p.area] ?? p.area}
                </span>
                <span className="block text-sm font-medium leading-snug">{p.title}</span>
                {p.review_status !== "approved" && <span className="text-[11px] text-warn">{t("notice.care_path_draft")}</span>}
              </button>
              {openPath === p.id && (
                <div className="mt-2 space-y-1.5" data-testid="path-services">
                  <button
                    type="button"
                    onClick={() => onPickPath(p.id)}
                    className="w-full rounded-lg bg-ink px-3 py-1.5 text-sm font-semibold text-white"
                  >
                    Price every step
                  </button>
                  {pathServices?.id !== p.id || pathServices.services == null ? (
                    <p className="text-xs text-muted-foreground">Loading its services…</p>
                  ) : pathServices.error ? (
                    <p className="text-xs text-warn">{pathServices.error}</p>
                  ) : (
                    <ul className="divide-y divide-border rounded-lg border border-border">
                      {pathServices.services.map((s) => (
                        <li key={s.service_id}>
                          <button type="button" onClick={() => onPickService(s)} className="w-full px-3 py-1.5 text-left hover:bg-muted">
                            <span className="block text-sm">Only: {s.plain_name}</span>
                            <span className="block text-[11px] text-muted-foreground">
                              {s.technical_name} · {s.codes.map((c) => c.code).join(", ")}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
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
