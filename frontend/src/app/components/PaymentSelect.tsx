import type { Payment } from "@/generated/contracts/quote_api";
import { PAYMENT_CHOICES, paymentId } from "../lib/payments";

/** One native <select>: fast on phones, keyboard friendly, and the same control everywhere. */
export function PaymentSelect({
  value,
  onChange,
  id = "payment",
  className,
}: {
  value: Payment | null;
  onChange: (p: Payment) => void;
  id?: string;
  className?: string;
}) {
  const current = value ? paymentId(value) : "";
  return (
    <select
      id={id}
      data-testid="payment-select"
      value={current}
      onChange={(e) => {
        const c = PAYMENT_CHOICES.find((x) => x.id === e.target.value);
        if (c) onChange(c.payment);
      }}
      className={
        className ??
        "w-full rounded-xl border border-border bg-card px-3 py-2.5 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-ink/40"
      }
    >
      {!value && (
        <option value="" disabled>
          Choose how you're paying…
        </option>
      )}
      <optgroup label="Insurance">
        {PAYMENT_CHOICES.filter((c) => c.group === "insurance").map((c) => (
          <option key={c.id} value={c.id}>
            {c.label}
            {c.note ? ` (${c.note})` : ""}
          </option>
        ))}
      </optgroup>
      <optgroup label="Other">
        {PAYMENT_CHOICES.filter((c) => c.group === "other").map((c) => (
          <option key={c.id} value={c.id}>
            {c.label}
          </option>
        ))}
      </optgroup>
    </select>
  );
}
