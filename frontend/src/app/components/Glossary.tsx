import { TERMS } from "../lib/glossary";
import { InfoTip } from "./InfoTip";

/**
 * Glossary chips for a line (hover on by default, plan §4.2). Text comes only from content/glossary.
 * D6: the chip shows the plain name; the technical term is one tap away, inside the tip.
 */
export function GlossaryChips({ keys }: { keys: string[] }) {
  const known = keys.filter((k) => TERMS[k]);
  if (!known.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {known.map((k) => {
        const term = TERMS[k];
        return (
          <InfoTip
            key={k}
            label={`What is ${term.technical_name}?`}
            trigger={
              <span className="rounded-full border border-border bg-card px-2 py-0.5 text-[11px] text-muted-foreground hover:text-foreground">
                ⓘ {term.plain_name}
              </span>
            }
          >
            <p className="font-semibold text-foreground">{term.plain_name}</p>
            <p className="text-[11px] text-muted-foreground mb-1">{term.technical_name}</p>
            <p>{term.short}</p>
            {term.link_out.length > 0 && (
              <p className="mt-1.5 space-x-2">
                {term.link_out.map((l) => (
                  <a key={l.url} href={l.url} target="_blank" rel="noreferrer" className="underline">
                    {l.label} ↗
                  </a>
                ))}
              </p>
            )}
          </InfoTip>
        );
      })}
    </span>
  );
}
