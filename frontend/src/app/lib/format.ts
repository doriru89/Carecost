const usd0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const usd2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });

/** Whole dollars for totals and pins, cents for receipt lines. Both only ever format a contract number. */
export function money(n: number, cents = true): string {
  return (cents ? usd2 : usd0).format(n);
}

export function range(low: number, high: number, cents = true): string {
  return low === high ? money(low, cents) : `${money(low, cents)}–${money(high, cents)}`;
}

/** "2026-04-01" -> "Apr 1, 2026" without a time-zone shift. */
export function isoDate(d: string | null | undefined): string {
  if (!d) return "no date given";
  const [y, m, day] = d.slice(0, 10).split("-").map(Number);
  if (!y || !m || !day) return d;
  return new Date(Date.UTC(y, m - 1, day)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}
