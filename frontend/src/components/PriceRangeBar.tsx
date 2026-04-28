import { cn } from '@/lib/utils';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

interface PriceRangeBarProps {
  label: string;
  min: number;
  max: number;
  /** Global min/max for the full scale across all items */
  scaleMin: number;
  scaleMax: number;
  /** Optional highlight value (e.g. your payer's negotiated rate) */
  highlight?: { value: number; label: string };
  source?: string;
  className?: string;
}

const fmt = (n: number) =>
  n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : `$${Math.round(n)}`;

const PriceRangeBar = ({
  label,
  min,
  max,
  scaleMin,
  scaleMax,
  highlight,
  source,
  className,
}: PriceRangeBarProps) => {
  const range = scaleMax - scaleMin || 1;
  const leftPct = ((min - scaleMin) / range) * 100;
  const widthPct = Math.max(((max - min) / range) * 100, 1);
  const highlightPct = highlight ? ((highlight.value - scaleMin) / range) * 100 : null;

  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-foreground">{label}</span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {fmt(min)} – {fmt(max)}
        </span>
      </div>

      <Tooltip>
        <TooltipTrigger asChild>
          <div className="relative h-3 rounded-full bg-muted overflow-hidden cursor-help">
            {/* Range bar */}
            <div
              className="absolute inset-y-0 rounded-full bg-primary/30"
              style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
            />
            {/* Filled core */}
            <div
              className="absolute inset-y-0 rounded-full bg-primary/60"
              style={{
                left: `${leftPct + widthPct * 0.15}%`,
                width: `${widthPct * 0.7}%`,
              }}
            />
            {/* Highlight marker */}
            {highlightPct !== null && (
              <div
                className="absolute top-0 bottom-0 w-0.5 bg-foreground"
                style={{ left: `${Math.min(Math.max(highlightPct, 0), 100)}%` }}
              />
            )}
          </div>
        </TooltipTrigger>
        <TooltipContent side="top" className="text-xs max-w-56">
          <p className="font-medium">{label}</p>
          <p>Range: {fmt(min)} – {fmt(max)}</p>
          {highlight && (
            <p>
              {highlight.label}: {fmt(highlight.value)}
            </p>
          )}
          {source && <p className="text-muted-foreground mt-1">Source: {source}</p>}
        </TooltipContent>
      </Tooltip>
    </div>
  );
};

export default PriceRangeBar;
