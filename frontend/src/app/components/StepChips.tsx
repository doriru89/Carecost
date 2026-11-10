import type { MapChoice } from "../lib/headline";
import { t } from "@/contracts/copy";
import { cn } from "@/lib/utils";

/** One row of chips: "Places only", then each price item. Shared by the chat and the results pane. */
export function StepChips({
  choices,
  step,
  onStep,
  label = t("steps.pick"),
  testId = "map-steps",
}: {
  choices: MapChoice[];
  step: string | null;
  onStep: (id: string | null) => void;
  label?: string;
  testId?: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1 text-xs" role="radiogroup" aria-label={label} data-testid={testId}>
      <span className="mr-1 text-muted-foreground">{label}</span>
      {[null, ...choices].map((c) => (
        <button
          key={c?.id ?? "none"}
          type="button"
          role="radio"
          aria-checked={step === (c?.id ?? null)}
          onClick={() => onStep(c?.id ?? null)}
          data-item={c?.item.kind ?? "none"}
          className={cn("rounded-full border px-2.5 py-1", step === (c?.id ?? null) ? "border-ink bg-ink text-white" : "border-border bg-card")}
        >
          {c == null ? t("map.no_step") : c.label}
        </button>
      ))}
    </div>
  );
}
