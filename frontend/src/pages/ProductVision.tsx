import { Link } from 'react-router-dom';
import Navbar from '@/components/layout/Navbar';
import Footer from '@/components/layout/Footer';
import BundleBreakdown from '@/components/BundleBreakdown';
import BundleLabel from '@/components/BundleLabel';
import PriceRangeBar from '@/components/PriceRangeBar';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  Layers,
  BarChart3,
  Tags,
  ArrowRight,
  AlertTriangle,
  Info,
} from 'lucide-react';

/* ─── Layer 3 demo data: same CPT, wildly different meaning ─── */
const SCOPE_DEMO = [
  {
    hospital: 'Dana-Farber',
    prices: [
      { label: 'BCBS (TiC insurer file)', amount: 60, scope: 'standalone' as const, note: 'Physician component only' },
      { label: 'Turquoise Health', amount: 2519, scope: 'bundled' as const, note: 'Facility + physician + anesthesia' },
    ],
    insight: 'A 41.9x apparent difference — but one is a single component and the other is the full package.',
  },
  {
    hospital: 'BMC',
    prices: [
      { label: 'BCBS (negotiated)', amount: 1251, scope: 'standalone' as const, note: 'Facility fee only' },
      { label: 'Turquoise Health', amount: 948, scope: 'bundled' as const, note: 'Full service package' },
    ],
    insight: 'The bundle is actually cheaper than the standalone facility fee. Scope reversal.',
  },
  {
    hospital: 'MGH',
    prices: [
      { label: 'BCBS (estimated)', amount: 3411, scope: 'unknown' as const, note: 'May include multiple components' },
      { label: 'Turquoise Health', amount: 2912, scope: 'bundled' as const, note: 'Facility + physician + anesthesia' },
    ],
    insight: 'Both high, but without scope labels you cannot tell which includes what.',
  },
];

/* ─── Layer 2 demo: per-item ranges ─── */
const RANGE_ITEMS = [
  { label: 'Facility fee', min: 948, max: 3411, source: 'Hospital MRFs, BCBS negotiated rates' },
  { label: 'Physician fee', min: 255, max: 1641, source: 'BCBS TiC, FAIR Health 80th pctl' },
  { label: 'Anesthesia', min: 400, max: 1359, source: 'FAIR Health + hospital MRFs' },
  { label: 'Pathology', min: 60, max: 250, source: 'FAIR Health 80th pctl' },
];

const fmt = (n: number) => `$${n.toLocaleString()}`;

const LAYERS = [
  {
    icon: Layers,
    num: '01',
    title: 'Bundle awareness',
    subtitle: 'What you actually pay for',
    desc: 'A procedure is not one bill. It is 4–5 separate charges from different providers. We show every component before you walk in.',
  },
  {
    icon: BarChart3,
    num: '02',
    title: 'Per-item price range',
    subtitle: 'How much each part costs',
    desc: 'For each component, prices vary dramatically across hospitals and insurers. We show the full range so you know where you stand.',
  },
  {
    icon: Tags,
    num: '03',
    title: 'Bundled vs. standalone clarity',
    subtitle: "What's included in that number",
    desc: 'One hospital quotes a bundled all-in price. Another quotes a standalone facility fee. Without labels, every comparison is apples to oranges.',
  },
];

const ProductVision = () => (
  <div className="min-h-screen flex flex-col">
    <Navbar />

    {/* Hero */}
    <section className="py-16 sm:py-24">
      <div className="container mx-auto px-4 max-w-3xl text-center animate-fade-in">
        <p className="text-xs font-semibold uppercase tracking-widest text-primary mb-4">Our approach</p>
        <h1 className="text-3xl sm:text-4xl md:text-5xl font-bold leading-tight mb-6">
          Three layers of clarity
          <br />
          <span className="text-primary">no one else shows</span>
        </h1>
        <p className="text-base sm:text-lg text-muted-foreground max-w-2xl mx-auto leading-relaxed">
          Healthcare pricing is not opaque because data is missing. It is opaque because three
          layers of complexity are collapsed into one number. We decompose them.
        </p>
      </div>
    </section>

    {/* Layer overview cards */}
    <section className="pb-16">
      <div className="container mx-auto px-4 max-w-4xl">
        <div className="grid md:grid-cols-3 gap-6">
          {LAYERS.map((layer, i) => (
            <Card
              key={layer.num}
              className="p-6 animate-slide-up border-border hover:border-primary/30 transition-colors"
              style={{ animationDelay: `${i * 100}ms` }}
            >
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center">
                  <layer.icon className="w-5 h-5 text-primary" />
                </div>
                <span className="text-xs font-bold text-primary tabular-nums">Layer {layer.num}</span>
              </div>
              <h3 className="font-semibold text-lg mb-1">{layer.title}</h3>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-3">
                {layer.subtitle}
              </p>
              <p className="text-sm text-muted-foreground leading-relaxed">{layer.desc}</p>
            </Card>
          ))}
        </div>
      </div>
    </section>

    {/* ─── Layer 1 deep dive ─── */}
    <section className="py-16 bg-card border-y border-border">
      <div className="container mx-auto px-4 max-w-3xl">
        <div className="flex items-center gap-3 mb-2">
          <span className="text-xs font-bold text-primary tabular-nums">Layer 01</span>
          <span className="text-xs text-muted-foreground">Bundle awareness</span>
        </div>
        <h2 className="text-2xl sm:text-3xl font-bold mb-3">
          A colonoscopy is not one bill
        </h2>
        <p className="text-muted-foreground mb-8 max-w-xl leading-relaxed">
          Most patients budget for the procedure. They are surprised by the facility fee,
          anesthesia, and pathology — which together cost{' '}
          <span className="font-semibold text-foreground">3.4x the physician fee</span>.
        </p>

        <BundleBreakdown />

        <p className="mt-6 text-xs text-muted-foreground flex items-start gap-1.5">
          <Info className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          FAIR Health 80th percentile in-network benchmarks for CPT 45385, Boston metro.
          Regional benchmarks — not hospital-specific negotiated rates.
          Range bars show actual variation across 12 Boston hospitals from published MRFs.
        </p>
      </div>
    </section>

    {/* ─── Layer 2 deep dive ─── */}
    <section className="py-16">
      <div className="container mx-auto px-4 max-w-3xl">
        <div className="flex items-center gap-3 mb-2">
          <span className="text-xs font-bold text-primary tabular-nums">Layer 02</span>
          <span className="text-xs text-muted-foreground">Per-item price range</span>
        </div>
        <h2 className="text-2xl sm:text-3xl font-bold mb-3">
          The same procedure: $255 to $3,411
        </h2>
        <p className="text-muted-foreground mb-8 max-w-xl leading-relaxed">
          Diagnostic colonoscopy (CPT 45378) at Boston hospitals on the same BCBS plan.
          That is a <span className="font-semibold text-foreground">13.4x range</span> —
          a $2,160 difference for the exact same service.
        </p>

        <Card className="p-6 space-y-5">
          {RANGE_ITEMS.map((item) => (
            <PriceRangeBar
              key={item.label}
              label={item.label}
              min={item.min}
              max={item.max}
              scaleMin={0}
              scaleMax={3500}
              source={item.source}
            />
          ))}
        </Card>

        <p className="mt-6 text-xs text-muted-foreground flex items-start gap-1.5">
          <Info className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          Ranges compiled from hospital MRFs (negotiated rates, de-identified min/max),
          BCBS TiC insurer files, and FAIR Health 80th percentile benchmarks.
          12 Boston-area hospitals, 2026 data.
        </p>
      </div>
    </section>

    {/* ─── Layer 3 deep dive ─── */}
    <section className="py-16 bg-card border-y border-border">
      <div className="container mx-auto px-4 max-w-3xl">
        <div className="flex items-center gap-3 mb-2">
          <span className="text-xs font-bold text-primary tabular-nums">Layer 03</span>
          <span className="text-xs text-muted-foreground">Bundled vs. standalone clarity</span>
        </div>
        <h2 className="text-2xl sm:text-3xl font-bold mb-3">
          $60 vs. $2,519 for the same procedure?
        </h2>
        <p className="text-muted-foreground mb-8 max-w-xl leading-relaxed">
          No. One is a physician-only component. The other is the full package.
          Without scope labels, <span className="font-semibold text-foreground">every price comparison is misleading</span>.
        </p>

        <div className="space-y-4">
          {SCOPE_DEMO.map((row) => (
            <Card key={row.hospital} className="p-5">
              <p className="text-sm font-semibold mb-3">{row.hospital} — CPT 45378</p>
              <div className="space-y-2.5">
                {row.prices.map((p) => (
                  <div
                    key={p.label}
                    className="flex items-center gap-3 flex-wrap"
                  >
                    <BundleLabel scope={p.scope} />
                    <span className="text-sm font-medium tabular-nums w-20">{fmt(p.amount)}</span>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span className="text-xs text-muted-foreground cursor-help border-b border-dotted border-muted-foreground/40">
                          {p.label}
                        </span>
                      </TooltipTrigger>
                      <TooltipContent side="top" className="text-xs max-w-52">
                        {p.note}
                      </TooltipContent>
                    </Tooltip>
                  </div>
                ))}
              </div>
              <div className="mt-3 flex items-start gap-2 p-2.5 rounded-lg bg-primary/5">
                <AlertTriangle className="w-3.5 h-3.5 text-primary mt-0.5 shrink-0" />
                <p className="text-xs text-foreground leading-relaxed">{row.insight}</p>
              </div>
            </Card>
          ))}
        </div>

        <p className="mt-6 text-xs text-muted-foreground flex items-start gap-1.5">
          <Info className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          Prices from hospital MRFs (HPT Rule), BCBS MA Transparency in Coverage file,
          and Turquoise Health service packages. All CPT 45378, diagnostic colonoscopy.
        </p>
      </div>
    </section>

    {/* ─── What makes this different ─── */}
    <section className="py-16">
      <div className="container mx-auto px-4 max-w-3xl">
        <h2 className="text-2xl sm:text-3xl font-bold mb-8 text-center">
          What no other tool shows
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-3 pr-4 font-medium text-muted-foreground">Capability</th>
                <th className="text-center py-3 px-3 font-medium text-primary">CareC❤️st</th>
                <th className="text-center py-3 px-3 font-medium text-muted-foreground">Insurer tools</th>
                <th className="text-center py-3 px-3 font-medium text-muted-foreground">GoodRx / MDsave</th>
                <th className="text-center py-3 px-3 font-medium text-muted-foreground">Turquoise</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {([
                ['Bundle decomposition', true, false, false, false],
                ['Per-item price ranges', true, false, false, true],
                ['Bundled vs. standalone labels', true, false, false, false],
                ['Source provenance on every number', true, false, false, false],
                ['Confidence / uncertainty display', true, false, false, false],
                ['Cross-insurer comparison', true, false, false, true],
                ['Plan-specific OOP estimate', true, true, false, false],
              ] as const).map(([cap, cc, ins, gd, tq]) => (
                <tr key={cap}>
                  <td className="py-2.5 pr-4 text-foreground">{cap}</td>
                  {[cc, ins, gd, tq].map((v, i) => (
                    <td key={i} className="py-2.5 px-3 text-center">
                      {v ? (
                        <span className="text-primary font-bold">✓</span>
                      ) : (
                        <span className="text-muted-foreground/40">—</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>

    {/* CTA */}
    <section className="py-16 bg-card border-t border-border">
      <div className="container mx-auto px-4 max-w-lg text-center">
        <h2 className="text-xl sm:text-2xl font-bold mb-4">See it in action</h2>
        <p className="text-muted-foreground mb-8">
          Enter your insurance details and explore cost breakdowns across Boston-area hospitals.
        </p>
        <Link to="/signup">
          <Button
            size="lg"
            className="bg-primary text-primary-foreground hover:bg-primary-hover rounded-full px-8 h-12 text-base"
          >
            Get started free
            <ArrowRight className="w-4 h-4 ml-2" />
          </Button>
        </Link>
      </div>
    </section>

    <Footer />
  </div>
);

export default ProductVision;
