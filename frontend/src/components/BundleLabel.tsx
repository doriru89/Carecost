import { cn } from '@/lib/utils';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

export type BundleScope = 'standalone' | 'bundled' | 'unknown';

const config: Record<BundleScope, { label: string; tip: string; classes: string }> = {
  standalone: {
    label: 'Standalone',
    tip: 'This price covers a single billing component (e.g. facility fee only). Other charges like physician, anesthesia, or pathology are billed separately.',
    classes: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  },
  bundled: {
    label: 'Bundled',
    tip: 'This price includes multiple billing components in one package (e.g. facility + physician + anesthesia). Check which services are included.',
    classes: 'bg-blue-50 text-blue-700 border-blue-200',
  },
  unknown: {
    label: 'Scope unclear',
    tip: 'The data source does not specify whether this price covers a single service or a bundle. Treat with caution.',
    classes: 'bg-muted text-muted-foreground border-border',
  },
};

interface BundleLabelProps {
  scope: BundleScope;
  className?: string;
}

const BundleLabel = ({ scope, className }: BundleLabelProps) => {
  const c = config[scope];
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            'inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium leading-tight cursor-help',
            c.classes,
            className,
          )}
        >
          {c.label}
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-64 text-xs leading-relaxed">
        {c.tip}
      </TooltipContent>
    </Tooltip>
  );
};

export default BundleLabel;
