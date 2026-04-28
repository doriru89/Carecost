import Navbar from '@/components/layout/Navbar';
import Footer from '@/components/layout/Footer';

/**
 * Methodology summary: public price transparency mandates, multi source pipeline, labeled rates.
 * Prose avoids em-dashes per product copy rules.
 */
const OurData = () => (
  <div className="min-h-screen flex flex-col">
    <Navbar />

    <main className="flex-1">
      <section className="container mx-auto px-4 sm:px-4 py-10 sm:py-12 md:py-16 max-w-3xl pb-[max(2.5rem,env(safe-area-inset-bottom))]">
        <p className="text-xs font-semibold uppercase tracking-wider text-primary mb-3 text-center">Our Data</p>
        <h1 className="text-2xl md:text-3xl font-bold text-center mb-8 leading-tight">
          How we build what you see
        </h1>

        <div className="rounded-2xl border border-primary/25 bg-primary/5 p-6 md:p-8 mb-10 md:mb-12">
          <p className="text-sm font-semibold text-foreground mb-2">Transparency and accuracy lead everything we publish.</p>
          <p className="text-sm text-muted-foreground leading-relaxed mb-4">
            We only keep and show information that helps people compare real prices and understand where each number came from. We document our pipeline so users and anyone reviewing our methods can follow how each view is built from public sources.
          </p>
          <p className="text-sm text-muted-foreground leading-relaxed">
            If a figure would mislead without context, we add the caveat or we show both sources side by side. We do not hide disagreement between datasets.
          </p>
        </div>

        <div className="space-y-8 text-sm text-muted-foreground leading-relaxed">
          <div>
            <h2 className="text-base font-semibold text-foreground mb-2">Why this is hard</h2>
            <p className="mb-3">
              Since 2021, federal rules require hospitals and insurers to publish negotiated rates. The data is public, but it was built for compliance, not for shopping. Files range from small CSVs to multi gigabyte JSON. Column names, encodings, and bundling rules differ by site.
            </p>
            <p>
              Many tools show one plan behind a login, or a single blended number. We combine independent sources and label each line so you can see the spread, not a black box.
            </p>
          </div>

          <div>
            <h2 className="text-base font-semibold text-foreground mb-2">Our pipeline</h2>
            <p className="mb-3">
              We collect from multiple independent sources. Examples include hospital machine readable files, insurer transparency in coverage files, regional benchmarks where we use them as a cross check, state all payer data where relevant, cleaned commercial transparency feeds, and the federal NPI registry to match providers.
            </p>
            <p className="mb-3">
              For each geography and specialty we clean each format, stream parse large insurer files, match providers by NPI, cross validate hospital reported rates against insurer reported rates, flag discrepancies with short notes, and attach benchmark context per CPT when it helps.
            </p>
            <p>
              We do not pick a single best price. When a hospital and an insurer report different amounts for the same plan, both can appear with a plain language note on likely reasons, such as facility versus professional components.
            </p>
          </div>

          <div>
            <h2 className="text-base font-semibold text-foreground mb-2">What we do differently</h2>
            <ul className="list-disc pl-5 space-y-2">
              <li>Negotiated rates from multiple insurers at listed hospitals, in one view, without requiring a member login for that comparison.</li>
              <li>Benchmarks used as reference, not as a fake stand in for your hospital price.</li>
              <li>Raw compliance files parsed into labeled rows so each number states what it is and where it came from.</li>
            </ul>
          </div>

          <div>
            <h2 className="text-base font-semibold text-foreground mb-2">Coverage in this demo</h2>
            <p className="mb-3">
              Greater Boston area hospitals and selected CPT lists for gastroenterology and dermatology. Insurer rows vary by procedure and source availability. Per row you may see up to several independent price points when files overlap.
            </p>
            <p>
              Adding another specialty is mostly the same pipeline with a new CPT list and parsers rerun. The infrastructure is reusable. The underlying data stays public.
            </p>
          </div>

          <div>
            <h2 className="text-base font-semibold text-foreground mb-2">Trust and limits</h2>
            <p className="mb-3">
              A negotiated rate on a file is not always your out of pocket. Deductibles, coinsurance, network status, and whether a rate covers a full service or one component still matter. We show labeled prices so you are less surprised, not so you skip calling your plan.
            </p>
            <p>
              Messy source data means we invest in parsing, deduplication, and honest labeling. Accuracy for us means showing sources and caveats, not pretending one clean number exists when the system does not work that way.
            </p>
          </div>
        </div>
      </section>
    </main>

    <Footer />
  </div>
);

export default OurData;
