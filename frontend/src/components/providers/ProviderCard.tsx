import { useState, useEffect } from 'react';
import { MapPin, Phone, Bookmark, ExternalLink, Info, ChevronDown, ChevronRight, Layers } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { getAllPriceSources } from '@/lib/payerPrice';
import { computeFairHealthTotal } from '@/lib/fairHealth';
import { computeOop, type OopResult } from '@/lib/oopRules';
import type { HospitalApi, CostComponentsResponse } from '@/api/client';
import { fetchCostComponents } from '@/api/client';
import CostBreakdown from './CostBreakdown';
import type { PlanConfig } from '@/lib/planConfig';
import type { Provider, CostEstimate } from '@/types';

interface ProviderCardProps {
  provider: Provider;
  estimate?: CostEstimate;
  /** Shown above your-plan pricing (e.g. carrier from onboarding). */
  insuranceLabel?: string;
  /** Hospital-level negotiated rate from hospital_rates (primary price source). */
  hospitalPayerPrice?: number | null;
  /** Full hospital record for multi-source transparency display. */
  hospital?: HospitalApi;
  /** Plan config for rule-aware OOP calculation. */
  planConfig?: PlanConfig;
  /** Scenario ID from procedure selection (e.g. 'colonoscopy_screening'). */
  scenarioId?: string | null;
  /** Selected CPT code. */
  cptCode?: string | null;
  onSave?: () => void;
  saved?: boolean;
  compact?: boolean;
  onRequestInsurance?: () => void;
}

interface PriceDisplay {
  label: string;
  sectionTitle: string;
  lineLabel: string;
  tooltip: string;
}

export function buildPriceDisplay(
  hospitalPayerPrice: number | null | undefined,
  estimate: CostEstimate | undefined,
  oopResult?: OopResult | null,
): PriceDisplay {
  // Priority 1: hospital_rates price (most reliable)
  if (hospitalPayerPrice != null) {
    if (oopResult) {
      return {
        label: oopResult.ruleType === 'preventive'
          ? '$0'
          : `$${oopResult.estimate.toLocaleString()}`,
        sectionTitle: 'Your plan',
        lineLabel: 'Est. cost (your insurance)',
        tooltip: oopResult.explanation,
      };
    }
    return {
      label: `$${Math.round(hospitalPayerPrice).toLocaleString()}`,
      sectionTitle: 'Negotiated rate',
      lineLabel: 'Base price',
      tooltip: 'Negotiated rate between your insurer and this hospital. Add your insurance info to see your estimated cost.',
    };
  }

  // Priority 2: estimate pipeline's allowed amount (fallback)
  if (estimate) {
    const allowed = estimate.allowedMaxDollars ?? estimate.allowedMinDollars;
    if (allowed != null && allowed >= 0) {
      return {
        label: `$${allowed.toLocaleString()}`,
        sectionTitle: 'Negotiated rate',
        lineLabel: 'Base price',
        tooltip: 'Provider-level negotiated rate. Add your insurance info to see your estimated cost.',
      };
    }
  }

  return {
    label: '—',
    sectionTitle: 'Pricing',
    lineLabel: 'Price',
    tooltip: 'Price data is not available for this provider.',
  };
}

const SOURCE_TIPS: Record<string, string> = {
  negotiated: 'Rate published by the hospital in their Machine-Readable File. This is what your insurer agreed to pay.',
  tic: 'Rate published by the insurer in their Transparency in Coverage file. May differ from hospital-reported rate.',
  de_identified: 'Range of rates this hospital accepts from all insurers. Required under the Hospital Price Transparency rule.',
  gross: "The hospital's list price before insurance discounts. Almost no one pays this.",
  cash: 'Discounted price for self-pay / uninsured patients.',
  benchmark: 'Aggregated pricing data from an external benchmark source.',
};

const ProviderCard = ({
  provider,
  estimate,
  insuranceLabel = 'Your plan',
  hospitalPayerPrice,
  hospital,
  planConfig,
  scenarioId,
  cptCode,
  onSave,
  saved = false,
  compact = false,
  onRequestInsurance,
}: ProviderCardProps) => {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [breakdownOpen, setBreakdownOpen] = useState(false);
  const [costData, setCostData] = useState<CostComponentsResponse | null>(null);
  const hasPrice = hospitalPayerPrice != null || estimate?.allowedMaxDollars != null;
  const oopResult = hospitalPayerPrice != null && planConfig
    ? computeOop(hospitalPayerPrice, planConfig, scenarioId ?? null, cptCode ?? null)
    : null;
  const price = buildPriceDisplay(hospitalPayerPrice, estimate, oopResult);

  useEffect(() => {
    if (!breakdownOpen || !hospital || costData) return;
    const payerId = hospital.payer_rates.find(r => r.negotiated_rate != null)?.payer_id;
    fetchCostComponents(hospital.hospital_id, hospital.cpt, payerId)
      .then(setCostData)
      .catch(() => {});
  }, [breakdownOpen, hospital, costData]);

  return (
    <div className="bg-card rounded-2xl border border-border shadow-card p-5 animate-fade-in">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="font-semibold text-lg leading-tight">{provider.name}</h3>
          <p className="text-sm text-muted-foreground mt-0.5">{provider.specialty.join(', ')}</p>
          {provider.hospital && <p className="text-xs text-muted-foreground">{provider.hospital}</p>}
        </div>
        {provider.distance !== undefined && (
          <span className="text-xs text-muted-foreground whitespace-nowrap ml-2">{provider.distance.toFixed(1)} mi</span>
        )}
      </div>

      <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
        <MapPin className="w-3.5 h-3.5 shrink-0" />
        <span>{provider.address}</span>
      </div>
      {provider.phone && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-3">
          <Phone className="w-3.5 h-3.5 shrink-0" />
          <span>{provider.phone}</span>
        </div>
      )}

      {provider.inNetwork !== undefined && (
        <span className={`inline-block text-xs font-medium px-2.5 py-1 rounded-full mb-3 ${
          provider.inNetwork ? 'bg-green-50 text-green-700' : 'bg-orange-50 text-orange-700'
        }`}>
          {provider.inNetwork ? 'In-network' : 'Out-of-network'}
        </span>
      )}

      {hasPrice && !compact && (
        <div className="bg-muted rounded-xl p-4 mb-4 space-y-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-1">{price.sectionTitle}</p>
            <p className="text-xs text-muted-foreground mb-2">{insuranceLabel}</p>
            <div className="space-y-1 text-sm">
              <div className="flex justify-between items-center font-semibold pt-1 border-t border-border">
                <span className="flex items-center gap-1">
                  {price.lineLabel}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="w-3.5 h-3.5 text-muted-foreground cursor-help" />
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-xs text-xs">
                      <p>{price.tooltip}</p>
                    </TooltipContent>
                  </Tooltip>
                </span>
                <span className="text-foreground">{price.label}</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {hasPrice && compact && (
        <div className="mb-3 space-y-1">
          <p className="text-sm font-medium">
            <span className="text-muted-foreground font-normal text-xs block">{insuranceLabel}</span>
            {price.sectionTitle === 'Your plan' ? 'Est.' : 'Rate'}{' '}
            <span className="text-foreground">{price.label}</span>
            <Tooltip>
              <TooltipTrigger asChild>
                <Info className="w-3 h-3 inline ml-1 -mt-0.5 text-muted-foreground" />
              </TooltipTrigger>
              <TooltipContent side="top" className="max-w-xs text-xs">
                <p>{price.tooltip}</p>
              </TooltipContent>
            </Tooltip>
          </p>
        </div>
      )}

      {/* Plan-rule OOP estimate (replaces naive formula when planConfig is available) */}
      {!compact && hospitalPayerPrice != null && planConfig && scenarioId && (
        <div className="bg-primary/5 border border-primary/15 rounded-xl p-4 mb-4">
          {(() => {
            const oop = computeOop(hospitalPayerPrice, planConfig, scenarioId, cptCode ?? null);
            return (
              <>
                <p className="text-xs font-semibold uppercase tracking-wider text-primary mb-2">Your out-of-pocket estimate</p>
                {oop.ruleType === 'preventive' ? (
                  <div className="flex justify-between text-sm font-semibold">
                    <span>Cost</span>
                    <span className="inline-flex items-center gap-1.5">
                      $0
                      <span className="text-xs font-normal bg-green-50 text-green-700 px-2 py-0.5 rounded-full">ACA preventive</span>
                    </span>
                  </div>
                ) : oop.ruleType === 'copay_only' ? (
                  <div className="flex justify-between text-sm font-semibold">
                    <span>Specialist copay</span>
                    <span>${oop.estimate.toLocaleString()}</span>
                  </div>
                ) : (
                  <>
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">If deductible not met</span>
                      <span className="font-semibold">${oop.estimate.toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground">If deductible already met</span>
                      <span className="font-semibold">${oop.estimateB.toLocaleString()}</span>
                    </div>
                  </>
                )}
                <p className="text-xs text-muted-foreground mt-2 flex items-start gap-1">
                  <Info className="w-3 h-3 mt-0.5 shrink-0" />
                  {oop.ruleType === 'preventive' && hospitalPayerPrice != null
                    ? `Insurer pays $${Math.round(hospitalPayerPrice).toLocaleString()} · You pay $0. ${oop.explanation} If a polyp is found, the plan may reclassify as diagnostic.`
                    : oop.explanation}
                </p>
              </>
            );
          })()}
        </div>
      )}

      {/* Insurance CTA — shown when no plan config and price data exists */}
      {!compact && hospitalPayerPrice != null && !planConfig && onRequestInsurance && (
        <button
          type="button"
          onClick={onRequestInsurance}
          className="bg-primary/5 border border-primary/15 rounded-xl p-4 mb-4 w-full text-left hover:bg-primary/10 transition-colors"
        >
          <p className="text-xs font-semibold uppercase tracking-wider text-primary mb-1">Your out-of-pocket estimate</p>
          <p className="text-sm text-muted-foreground">Add your insurance info to see your estimated cost</p>
        </button>
      )}

      {/* Multi-source price transparency (expanded view only) */}
      {!compact && hospital && (
        <div className="mb-4">
          <button
            type="button"
            onClick={() => setSourcesOpen(!sourcesOpen)}
            className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors w-full"
          >
            {sourcesOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            All price sources
          </button>
          {sourcesOpen && (
            <div className="bg-muted/50 rounded-xl p-4 mt-2 space-y-1.5 max-h-[300px] overflow-y-auto">
              {getAllPriceSources(hospital, insuranceLabel).map((src, i) => (
                <div key={i} className="flex justify-between text-sm">
                  <span className="text-muted-foreground flex items-center gap-1">
                    {src.label}
                    {src.plan_count != null && src.plan_count > 1 && (
                      <span className="opacity-50">({src.plan_count} plans)</span>
                    )}
                    <Tooltip>
                      <TooltipTrigger asChild><Info className="w-3 h-3 cursor-help" /></TooltipTrigger>
                      <TooltipContent className="text-xs max-w-xs">
                        <p>{SOURCE_TIPS[src.kind] ?? 'Price data from public transparency filings.'}</p>
                        {src.billing_class && <p className="mt-1">Billing class: {src.billing_class}</p>}
                      </TooltipContent>
                    </Tooltip>
                  </span>
                  <span className="font-medium">${Math.round(src.price).toLocaleString()}</span>
                </div>
              ))}

              {/* FAIR Health 80th percentile breakdown */}
              {(() => {
                const fh = computeFairHealthTotal(hospital.benchmarks);
                if (!fh) return null;
                return (
                  <div className="pt-2 mt-2 border-t border-border">
                    <div className="flex justify-between text-sm">
                      <span className="text-muted-foreground flex items-center gap-1">
                        FAIR Health 80th %ile
                        <Tooltip>
                          <TooltipTrigger asChild><Info className="w-3 h-3 cursor-help" /></TooltipTrigger>
                          <TooltipContent className="text-xs max-w-xs">
                            80% of patients pay this amount or less. National benchmark broken down by physician, facility, and anesthesia.
                          </TooltipContent>
                        </Tooltip>
                      </span>
                      <span className="font-medium">${fh.total.toLocaleString()}</span>
                    </div>
                    {fh.components.map(c => (
                      <div key={c.label} className="flex justify-between text-xs text-muted-foreground pl-4">
                        <span>{c.label}</span>
                        <span>${c.amount.toLocaleString()}</span>
                      </div>
                    ))}
                  </div>
                );
              })()}

              {getAllPriceSources(hospital, insuranceLabel).length === 0 && (
                <p className="text-xs text-muted-foreground italic">No price sources available for this hospital.</p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Cost component breakdown (RVU decomposition + provenance) */}
      {!compact && hospital && (
        <div className="mb-4">
          <button
            type="button"
            onClick={() => setBreakdownOpen(!breakdownOpen)}
            className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors w-full"
          >
            {breakdownOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            <Layers className="w-3.5 h-3.5" />
            Cost breakdown
          </button>
          {breakdownOpen && (
            <div className="bg-muted/50 rounded-xl p-4 mt-2">
              {costData ? (
                <CostBreakdown data={costData} />
              ) : (
                <p className="text-xs text-muted-foreground animate-pulse">Loading cost breakdown…</p>
              )}
            </div>
          )}
        </div>
      )}

      {!hasPrice && !compact && (
        <div className="bg-muted/30 border border-border rounded-xl px-4 py-3 mb-4">
          <p className="text-xs text-muted-foreground italic">{insuranceLabel} price not disclosed by this provider</p>
        </div>
      )}

      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          className="flex-1"
          onClick={onSave}
        >
          <Bookmark className={`w-4 h-4 mr-1 ${saved ? 'fill-primary' : ''}`} />
          {saved ? 'Saved' : 'Save'}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="flex-1"
          onClick={() => window.open(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(provider.address)}`, '_blank')}
        >
          <ExternalLink className="w-4 h-4 mr-1" />
          Directions
        </Button>
      </div>
    </div>
  );
};

export default ProviderCard;
