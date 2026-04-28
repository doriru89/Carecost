import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import BundleLabel from '@/components/BundleLabel';
import PriceRangeBar from '@/components/PriceRangeBar';
import { Stethoscope, Building2, Syringe, Microscope, CircleDollarSign } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export interface BundleComponent {
  id: string;
  label: string;
  icon: LucideIcon;
  fairHealth80th: number;
  rangeMin: number;
  rangeMax: number;
  description: string;
}

/** Pre-built data for colonoscopy polyp removal (CPT 45385) in Boston */
export const COLONOSCOPY_BUNDLE: BundleComponent[] = [
  {
    id: 'facility',
    label: 'Facility fee',
    icon: Building2,
    fairHealth80th: 2350,
    rangeMin: 948,
    rangeMax: 3411,
    description: 'The hospital or surgery center charges this for use of the room, equipment, nursing staff, and recovery area.',
  },
  {
    id: 'physician',
    label: 'Physician fee',
    icon: Stethoscope,
    fairHealth80th: 941,
    rangeMin: 255,
    rangeMax: 1641,
    description: 'The gastroenterologist bills separately for performing the procedure, reading results, and clinical interpretation.',
  },
  {
    id: 'anesthesia',
    label: 'Anesthesia',
    icon: Syringe,
    fairHealth80th: 770,
    rangeMin: 400,
    rangeMax: 1359,
    description: 'An anesthesiologist or CRNA administers and monitors sedation. This is a separate bill from the facility and physician.',
  },
  {
    id: 'pathology',
    label: 'Pathology / lab',
    icon: Microscope,
    fairHealth80th: 114,
    rangeMin: 60,
    rangeMax: 250,
    description: 'If tissue is removed (biopsy or polyp), a pathologist examines it. This is a separate bill from a separate doctor.',
  },
];

const fmt = (n: number) => `$${n.toLocaleString()}`;

interface BundleBreakdownProps {
  components?: BundleComponent[];
  procedureName?: string;
  className?: string;
}

const BundleBreakdown = ({
  components = COLONOSCOPY_BUNDLE,
  procedureName = 'Colonoscopy with polyp removal',
  className,
}: BundleBreakdownProps) => {
  const total = components.reduce((s, c) => s + c.fairHealth80th, 0);
  const globalMax = Math.max(...components.map((c) => c.rangeMax));

  return (
    <div className={className}>
      {/* Summary header */}
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <h3 className="text-lg font-semibold text-foreground">{procedureName}</h3>
          <p className="text-sm text-muted-foreground mt-1">
            {components.length} separate bills from {components.length} different providers
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Estimated total</p>
          <p className="text-2xl font-bold text-foreground tabular-nums">{fmt(total)}</p>
          <p className="text-[11px] text-muted-foreground">FAIR Health 80th pctl, Boston</p>
        </div>
      </div>

      {/* Component breakdown */}
      <Accordion type="multiple" className="space-y-2">
        {components.map((comp) => {
          const pct = Math.round((comp.fairHealth80th / total) * 100);
          return (
            <AccordionItem
              key={comp.id}
              value={comp.id}
              className="border rounded-xl px-4 bg-card shadow-[var(--shadow-card)]"
            >
              <AccordionTrigger className="hover:no-underline py-3">
                <div className="flex items-center gap-3 w-full pr-2">
                  <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                    <comp.icon className="w-4 h-4 text-primary" />
                  </div>
                  <div className="flex-1 text-left min-w-0">
                    <p className="text-sm font-medium text-foreground">{comp.label}</p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-sm font-semibold tabular-nums">{fmt(comp.fairHealth80th)}</p>
                    <p className="text-[11px] text-muted-foreground">{pct}% of total</p>
                  </div>
                </div>
              </AccordionTrigger>
              <AccordionContent className="pb-4 space-y-3">
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {comp.description}
                </p>
                <PriceRangeBar
                  label="Price range across Boston hospitals"
                  min={comp.rangeMin}
                  max={comp.rangeMax}
                  scaleMin={0}
                  scaleMax={globalMax}
                  highlight={{ value: comp.fairHealth80th, label: 'FAIR Health 80th' }}
                  source="Hospital MRFs + FAIR Health benchmarks"
                />
              </AccordionContent>
            </AccordionItem>
          );
        })}
      </Accordion>

      {/* Total bar */}
      <div className="mt-4 flex items-center gap-3 p-3 rounded-xl bg-primary/5 border border-primary/20">
        <CircleDollarSign className="w-5 h-5 text-primary shrink-0" />
        <p className="text-sm text-foreground">
          <span className="font-semibold">Most people expect one bill.</span>{' '}
          In reality, you receive {components.length} separate charges totaling{' '}
          <span className="font-semibold tabular-nums">{fmt(total)}</span> before
          insurance adjustments.
        </p>
      </div>
    </div>
  );
};

export default BundleBreakdown;
