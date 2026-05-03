import { Stethoscope, Building2, ShieldAlert, Info } from 'lucide-react';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import type { CostComponentsResponse, CostProvenance } from '@/api/client';

const COMPONENT_META: Record<string, { icon: typeof Stethoscope; label: string }> = {
  physician_work: { icon: Stethoscope, label: 'Physician work' },
  practice_expense: { icon: Building2, label: 'Practice expense' },
  malpractice: { icon: ShieldAlert, label: 'Malpractice' },
};

function ProvenanceBadge({ prov }: { prov: CostProvenance }) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="inline-flex items-center text-[10px] font-medium px-2 py-0.5 rounded-full bg-primary/10 text-primary">
        {prov.source_display}
      </span>
      {prov.data_vintage && (
        <span className="text-[10px] text-muted-foreground">{prov.data_vintage}</span>
      )}
      {prov.rate_year != null && prov.rate_year > 0 && (
        <span className="text-[10px] text-muted-foreground">CY{prov.rate_year}</span>
      )}
    </div>
  );
}

export default function CostBreakdown({ data }: { data: CostComponentsResponse }) {
  if (data.data_tier === 'no_rate') {
    return (
      <p className="text-xs text-muted-foreground italic">
        No negotiated rate available for cost breakdown.
      </p>
    );
  }

  const hasComponents = data.components.length > 0;

  return (
    <div className="space-y-3">
      {data.negotiated_rate != null && (
        <div className="flex justify-between items-start">
          <div>
            <p className="text-sm font-semibold">
              ${Math.round(data.negotiated_rate).toLocaleString()}
            </p>
            {data.rate_provenance && <ProvenanceBadge prov={data.rate_provenance} />}
          </div>
          {data.data_tier === 'gross_only' && (
            <span className="text-[10px] text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
              Gross charge only
            </span>
          )}
        </div>
      )}

      {hasComponents && (
        <div className="space-y-1.5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Cost components (RVU decomposition)
            <Tooltip>
              <TooltipTrigger asChild>
                <Info className="w-3 h-3 inline ml-1 -mt-0.5 cursor-help" />
              </TooltipTrigger>
              <TooltipContent className="text-xs max-w-xs">
                Breakdown based on CMS Relative Value Units. Each component reflects physician work, overhead, and liability costs adjusted for Boston geography.
              </TooltipContent>
            </Tooltip>
          </p>
          {data.components.map((c) => {
            const meta = COMPONENT_META[c.name] ?? { icon: Info, label: c.name };
            const Icon = meta.icon;
            return (
              <div key={c.name} className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-1.5 text-muted-foreground">
                  <Icon className="w-3.5 h-3.5" />
                  {meta.label}
                  {c.pct_of_total != null && (
                    <span className="text-[10px]">({Math.round(c.pct_of_total)}%)</span>
                  )}
                </span>
                <span className="font-medium">
                  {c.amount != null ? `$${Math.round(c.amount).toLocaleString()}` : '—'}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
