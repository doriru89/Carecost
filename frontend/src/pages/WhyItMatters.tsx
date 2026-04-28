import Navbar from '@/components/layout/Navbar';
import Footer from '@/components/layout/Footer';
import { WHY_IT_MATTERS_VIDEO_EMBED_URL, WHY_IT_MATTERS_VIDEO_SRC } from '@/config/whyItMatters';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { ArrowRight } from 'lucide-react';

/**
 * Figures from public and industry research on U.S. medical debt, hospital bad debt, cost-related care delays,
 * plan design, and consumer price-shopping behavior.
 * Each card names what is being counted before interpreting it.
 */
const STATS: { value: string; headline: string; text: string }[] = [
  {
    value: '$220B+',
    headline: 'Total medical debt owed by people in the United States',
    text: 'Government and census-based analyses estimate households together owe at least this much for medical bills. Medical debt is widespread among insured families, not only the uninsured.',
  },
  {
    value: '$17B+',
    headline: 'Annual bad debt from unpaid patient bills at U.S. hospitals and providers',
    text: 'National industry data put annual bad debt from unpaid patient bills in the tens of billions. Opaque pricing feeds surprise balances and write-offs. Clearer costs before care will not fix everything, but it can reduce unpaid balances and the bad debt hospitals absorb.',
  },
  {
    value: '36.3%',
    headline: 'Households that report holding medical debt',
    text: 'More than one in three U.S. households carry some amount owed for care. That scale shows billing after the fact is failing as a national way to pay for health.',
  },
  {
    value: '~38%',
    headline: 'Insured adults skipped or delayed care because of out-of-pocket costs',
    text: 'Multiple surveys summarized in industry research land around 37% to 40%: roughly four in ten people with insurance still avoided some care in the past year over deductibles, copays, or fear of the bill. That is not “uninsured only.” It is the middle class with a card in their wallet.',
  },
  {
    value: '$1,886',
    headline: 'Average annual deductible for employer single coverage in 2025',
    text: 'Before copays and coinsurance, many workers must spend this much on their own each year. “Having insurance” often still means paying thousands before full coverage kicks in.',
  },
  {
    value: '32%',
    headline: 'Workers whose plan has a deductible of $2,000 or more',
    text: 'That share has grown several times over since 2009. High deductibles are now normal, so knowing the price before you schedule care is not optional for household budgets.',
  },
  {
    value: '73%',
    headline: 'Share of commercial health spending on care that could be shoppable',
    text: 'Researchers classify this slice as non-emergency care where timing allows comparing providers or sites. The theoretical room to compare is large even when the tools are not.',
  },
  {
    value: '89%',
    headline: 'Consumers say they would shop for care with the right tools',
    text: 'Survey data consistently finds strong interest in comparing options when the experience is simple and reliable. Demand for clarity is already there.',
  },
  {
    value: '64%',
    headline: 'Consumers say they have never price-shopped for healthcare',
    text: 'In the same line of research, nearly two-thirds report never comparing prices across hospitals or clinicians for a service. People are not asked to shop in a normal way: opaque prices and broken directories come first.',
  },
];

const WhyItMatters = () => (
  <div className="min-h-screen flex flex-col">
    <Navbar />

    <main className="flex-1">
      <section className="border-b border-border bg-card/40">
        <div className="container mx-auto px-4 py-8 sm:py-10 md:py-14 max-w-4xl">
          <p className="text-xs font-semibold uppercase tracking-wider text-primary mb-2 text-center">Why it matters</p>
          <h1 className="text-2xl md:text-3xl font-bold text-center mb-8 max-w-2xl mx-auto leading-tight">
            You are expected to pay like a shopper. The system still behaves like a black box.
          </h1>
          {WHY_IT_MATTERS_VIDEO_SRC ? (
            <div className="relative w-full overflow-hidden rounded-2xl border border-border shadow-elevated aspect-video bg-black">
              <video
                className="h-full w-full object-contain"
                controls
                playsInline
                preload="metadata"
                src={WHY_IT_MATTERS_VIDEO_SRC}
              />
            </div>
          ) : WHY_IT_MATTERS_VIDEO_EMBED_URL ? (
            <div className="relative w-full overflow-hidden rounded-2xl border border-border shadow-elevated aspect-video bg-black">
              <iframe
                title="Why price transparency matters"
                src={WHY_IT_MATTERS_VIDEO_EMBED_URL}
                className="absolute inset-0 h-full w-full"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                allowFullScreen
              />
            </div>
          ) : (
            <div className="relative flex aspect-video w-full flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-primary/35 bg-muted/40 px-6 text-center">
              <p className="text-sm font-medium text-foreground">Video placeholder</p>
              <p className="max-w-md text-sm text-muted-foreground leading-relaxed">
                Add a file under{' '}
                <code className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground">
                  frontend/public/videos/
                </code>{' '}
                and set <span className="font-medium text-foreground">WHY_IT_MATTERS_VIDEO_SRC</span> in{' '}
                <code className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground">
                  src/config/whyItMatters.ts
                </code>{' '}
                to something like <span className="font-medium text-foreground">/videos/your-video.mp4</span>. Or set{' '}
                <span className="font-medium text-foreground">WHY_IT_MATTERS_VIDEO_EMBED_URL</span> for a YouTube or Vimeo
                embed.
              </p>
            </div>
          )}

          <div className="mt-12 md:mt-16 max-w-2xl mx-auto border-t border-border pt-12 md:pt-14">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-primary mb-4 text-center">Personal story</h2>
            <div className="space-y-5 text-muted-foreground leading-relaxed text-[15px] md:text-base">
              <p className="text-foreground font-medium">
                Someone we love lost a pregnancy. There are no words that fix that. There is only grief, and time, and
                the people who show up when the world goes quiet.
              </p>
              <p>
                She did what any of us would do. She went where her doctors sent her, where she could get care quickly,
                where she felt safe. She was insured. She believed that meant she would not have to carry the full weight
                of the hospital bill on her own. She was already carrying enough.
              </p>
              <p>
                Then the envelope came. The total was{' '}
                <span className="font-semibold tabular-nums text-foreground">$59,409.98</span>. Not a typo. Not a mistake
                she could laugh off. A number that sat on the kitchen table like a second trauma.
              </p>
              <p>
                Her plan did not step in the way she had been led to expect. The insurer argued she could have gone
                somewhere cheaper, as if grief came with a spreadsheet, as if anyone in that moment should have been
                comparison shopping between hospitals. They used price as a reason to say no. She had never seen those
                prices before she needed care. How was she supposed to choose what she could not see?
              </p>
              <p className="text-foreground">
                That bill is why we are building this. The system tells you to shop for care, then hides the price until
                after you are on the hook. We refuse to accept that as normal. Our job is to put real out-of-pocket
                estimates in front of people while they can still choose, not buried in files meant for regulators. We
                cannot change her past. We can make sure the next family sees the number before they walk in the door.
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="container mx-auto px-4 py-12 md:py-16 max-w-3xl space-y-6 text-muted-foreground leading-relaxed">
        <p className="text-lg text-foreground font-medium">
          A short story: costs moved to you before clarity moved with them.
        </p>
        <p>
          Employers and insurers held down premiums partly by raising deductibles and cost sharing. On paper you are
          covered. In practice you often pay thousands out of pocket before your plan behaves like full insurance. The
          fair next step would be obvious prices and accurate networks. Instead, many patients still get a bill they did
          not see coming, or they avoid care because they cannot guess what is safe to spend.
        </p>
        <p>
          Lawmakers required hospitals and payers to publish data. That helped researchers and regulators. It did not by
          itself give you a single screen that says, for your plan and your procedure, what you will owe at this hospital
          versus that one. Raw files are not a shopping experience.
        </p>
        <p>
          <span className="font-medium text-foreground">What we are building toward</span> is the missing layer: your
          coverage and real negotiated rates turned into estimates you can use before you book, so comparison is
          possible without a finance degree or hours on the phone.
        </p>
      </section>

      <section className="border-t border-border bg-muted/30 py-14 md:py-20">
        <div className="container mx-auto px-4 max-w-5xl">
          <ul className="grid gap-8 sm:grid-cols-2 lg:grid-cols-3">
            {STATS.map(row => (
              <li
                key={row.value + row.headline}
                className="rounded-2xl border border-border bg-card p-6 shadow-card"
              >
                <p className="text-4xl md:text-5xl font-bold tracking-tight text-primary mb-3 tabular-nums">{row.value}</p>
                <p className="text-sm font-semibold text-foreground mb-2 leading-snug">{row.headline}</p>
                <p className="text-sm text-muted-foreground leading-relaxed">{row.text}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="container mx-auto px-4 py-14 text-center max-w-xl">
        <p className="text-muted-foreground mb-6">
          See provider options with estimates tied to your plan, not generic list prices.
        </p>
        <Button asChild size="lg" className="rounded-full bg-primary text-primary-foreground hover:bg-primary-hover px-8">
          <Link to="/signup">
            Get started
            <ArrowRight className="ml-2 h-4 w-4" />
          </Link>
        </Button>
      </section>
    </main>

    <Footer />
  </div>
);

export default WhyItMatters;
