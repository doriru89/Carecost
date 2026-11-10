import type { MapChoice } from "../lib/headline";
import { t } from "@/contracts/copy";
import { cn } from "@/lib/utils";

/** One row of chips, one per price item (Austin 2026-11-09: no "Places only"; the map always prices one). Shared by the chat and the results pane. */
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
      {choices.map((c) => (
        <button
          key={c.id}
          type="button"
          role="radio"
          aria-checked={step === c.id}
          onClick={() => onStep(c.id)}
          data-item={c.item.kind}
          className={cn("rounded-full border px-2.5 py-1", step === c.id ? "border-ink bg-ink text-white" : "border-border bg-card")}
        >
          {c.label}
        </button>
      ))}
    </div>
  );
}
