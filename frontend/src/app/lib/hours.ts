/**
 * Open-now / open-today from a site's posted weekly hours, in Boston time (sites are all in MA).
 * Hours are the operator's posted hours, not live: the label says so (hours_label).
 */
import type { Hours, HoursSpan, SiteSummary } from "@/generated/contracts/quote_api";

type Day = HoursSpan["days"][number];
const DAYS: Day[] = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

export interface BostonNow {
  day: Day;
  /** minutes since local midnight */
  minutes: number;
}

export function bostonNow(now: Date = new Date()): BostonNow {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const day = get("weekday").slice(0, 3).toLowerCase() as Day;
  return { day, minutes: Number(get("hour")) * 60 + Number(get("minute")) };
}

const toMin = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + (m || 0);
};

function clock(hhmm: string): string {
  const mins = toMin(hhmm);
  const h = Math.floor(mins / 60) % 24;
  const m = mins % 60;
  const suffix = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return m ? `${h12}:${String(m).padStart(2, "0")} ${suffix}` : `${h12} ${suffix}`;
}

export interface OpenStatus {
  known: boolean;
  openNow: boolean;
  /** opens at some point today (now or later) */
  openToday: boolean;
  text: string;
}

export function openStatus(hours: Hours | null, now: BostonNow): OpenStatus {
  if (!hours || hours.weekly.length === 0) return { known: false, openNow: false, openToday: false, text: "Hours not listed" };
  const today = hours.weekly.filter((s) => s.days.includes(now.day));
  const open = today.find((s) => toMin(s.opens) <= now.minutes && now.minutes < toMin(s.closes));
  const later = today.filter((s) => toMin(s.opens) > now.minutes).sort((a, b) => toMin(a.opens) - toMin(b.opens))[0];
  const early = hours.may_close_early ? " · may close early" : "";
  if (open) return { known: true, openNow: true, openToday: true, text: `Open now until ${clock(open.closes)}${early}` };
  if (later) return { known: true, openNow: false, openToday: true, text: `Opens today at ${clock(later.opens)}${early}` };
  const next = nextOpenDay(hours, now.day);
  const closed = today.length ? "Closed now" : "Closed today";
  return { known: true, openNow: false, openToday: false, text: next ? `${closed} · opens ${next}` : "Closed" };
}

function nextOpenDay(hours: Hours, from: Day): string | null {
  const i = DAYS.indexOf(from);
  for (let k = 1; k <= 7; k++) {
    const d = DAYS[(i + k) % 7];
    const span = hours.weekly.find((s) => s.days.includes(d));
    if (span) return `${k === 1 ? "tomorrow" : d[0].toUpperCase() + d.slice(1)} ${clock(span.opens)}`;
  }
  return null;
}

/**
 * D6 item 8: which field an "open now" comes from. The quote carries `SiteSummary.hours` (weekly spans) and
 * `hours_label`; nothing else. `unknown` = no hours in the quote (we never guess them).
 */
export function hoursSourceKey(label: SiteSummary["hours_label"]): string {
  switch (label) {
    case "live_by_operator":
      return "hours.from_live";
    case "posted_hours":
      return "hours.from_posted";
    case "may_close_early":
      return "hours.may_close_early";
    case "unknown":
      return "hours.unknown";
  }
}
