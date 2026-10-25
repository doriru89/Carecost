import type { SiteSummary } from "@/generated/contracts/quote_api";
import { Footprints, ExternalLink, Phone } from "lucide-react";

/** D7: links only. Reserve deep links, walk-in, phone, and the health system's patient portal. */
export function Booking({ site, compact }: { site: SiteSummary; compact?: boolean }) {
  const btn =
    "inline-flex items-center gap-1 rounded-full border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted touch-manipulation";
  return (
    <div className="flex flex-wrap gap-1.5" data-testid="booking">
      {site.booking.map((b, i) => {
        if (b.kind === "deep_link" || b.kind === "iframe_mgb")
          return b.url ? (
            <a key={i} href={b.url} target="_blank" rel="noreferrer" className={`${btn} bg-ink text-white border-transparent hover:bg-ink/90`}>
              {b.label} <ExternalLink className="h-3 w-3" />
            </a>
          ) : null;
        if (b.kind === "walk_in")
          return (
            <span key={i} className={btn}>
              <Footprints className="h-3 w-3" /> {b.label}
            </span>
          );
        const phone = b.phone ?? site.phone;
        return phone ? (
          <a key={i} href={`tel:${phone.replace(/[^\d+]/g, "")}`} className={btn} aria-label={`Call ${site.name}`}>
            <Phone className="h-3 w-3" /> {compact ? "" : phone}
          </a>
        ) : null;
      })}
      {!site.booking.some((b) => b.kind === "call") && site.phone && (
        <a href={`tel:${site.phone.replace(/[^\d+]/g, "")}`} className={btn} aria-label={`Call ${site.name}`}>
          <Phone className="h-3 w-3" /> {compact ? "" : site.phone}
        </a>
      )}
      {!compact &&
        site.portal_links.map((p) => (
          <a key={p.url} href={p.url} target="_blank" rel="noreferrer" className={btn}>
            {p.label} <ExternalLink className="h-3 w-3" />
          </a>
        ))}
    </div>
  );
}
