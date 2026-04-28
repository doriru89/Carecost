import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import Navbar from '@/components/layout/Navbar';
import Footer from '@/components/layout/Footer';
import BundleLabel from '@/components/BundleLabel';
import { Heart, Layers, BarChart3, Tags, ArrowRight } from 'lucide-react';

const layers = [
  {
    icon: Layers,
    title: 'Bundle awareness',
    stat: '4–5 bills',
    desc: 'A colonoscopy is not one charge. It is facility + physician + anesthesia + pathology. We show every component.',
  },
  {
    icon: BarChart3,
    title: 'Per-item price range',
    stat: '13.4x range',
    desc: 'The same procedure on the same plan: $255 at one hospital, $3,411 at another. We show the full range.',
  },
  {
    icon: Tags,
    title: 'Bundled vs. standalone',
    stat: '41.9x trap',
    desc: '$60 vs. $2,519 for the same CPT? One is a single component, the other is a full package. We label the difference.',
  },
];

const Index = () => (
  <div className="min-h-screen flex flex-col">
    <Navbar />

    {/* Hero */}
    <section className="flex-1 flex items-center">
      <div className="container mx-auto px-4 py-12 sm:py-20 md:py-32 text-center max-w-3xl animate-fade-in">
        <div className="inline-flex items-center justify-center gap-2 bg-primary/10 text-foreground rounded-full px-3 sm:px-4 py-1.5 text-xs sm:text-sm font-medium mb-5 sm:mb-6 max-w-[min(100%,20rem)] mx-auto text-center leading-snug">
          <Heart className="w-4 h-4 shrink-0 fill-primary stroke-primary" />
          <span>Healthcare cost transparency</span>
        </div>
        <h1 className="text-[1.75rem] leading-tight sm:text-4xl md:text-6xl font-bold mb-5 sm:mb-6">
          Care that doesn't
          <br />
          <span className="text-primary">surprise you</span>
        </h1>
        <p className="text-base sm:text-lg text-muted-foreground mb-8 sm:mb-10 max-w-xl mx-auto leading-relaxed px-1">
          See what you'll actually pay — every bill, every component, every source — before you walk in.
        </p>
        <div className="flex flex-col sm:flex-row gap-3 justify-center max-w-md mx-auto sm:max-w-none">
          <Link to="/signup" className="w-full sm:w-auto touch-manipulation">
            <Button size="lg" className="w-full sm:w-auto bg-primary text-primary-foreground hover:bg-primary-hover px-8 min-h-12 h-12 text-base rounded-full">
              See real prices
            </Button>
          </Link>
        </div>
        <p className="text-sm text-muted-foreground mt-6 tracking-wide">
          13 hospitals &middot; 37 CPT codes &middot; 6 independent data sources
        </p>
      </div>
    </section>

    {/* 3-Layer preview */}
    <section className="py-12 sm:py-20 bg-card border-t border-border">
      <div className="container mx-auto px-4 max-w-4xl">
        <p className="text-xs font-semibold uppercase tracking-widest text-primary text-center mb-3">
          Our approach
        </p>
        <h2 className="text-xl sm:text-2xl md:text-3xl font-bold text-center mb-3 px-2">
          Three layers of clarity no one else shows
        </h2>
        <p className="text-sm text-muted-foreground text-center mb-10 max-w-lg mx-auto">
          Healthcare pricing collapses three layers of complexity into one opaque number.
          We decompose them.
        </p>

        <div className="grid md:grid-cols-3 gap-6 mb-10">
          {layers.map((layer, i) => (
            <Card
              key={layer.title}
              className="p-5 animate-slide-up hover:border-primary/30 transition-colors"
              style={{ animationDelay: `${i * 100}ms` }}
            >
              <div className="flex items-center gap-2.5 mb-3">
                <div className="w-9 h-9 rounded-lg bg-primary/10 flex items-center justify-center">
                  <layer.icon className="w-4.5 h-4.5 text-primary" />
                </div>
                <span className="text-2xl font-bold text-primary tabular-nums">{layer.stat}</span>
              </div>
              <h3 className="font-semibold mb-1.5">{layer.title}</h3>
              <p className="text-sm text-muted-foreground leading-relaxed">{layer.desc}</p>
            </Card>
          ))}
        </div>

        {/* Mini scope demo */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 p-5 rounded-2xl bg-primary/5 border border-primary/10">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">Same CPT code, same hospital:</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <BundleLabel scope="standalone" />
              <span className="text-sm font-semibold tabular-nums">$60</span>
            </div>
            <span className="text-muted-foreground text-xs">vs</span>
            <div className="flex items-center gap-1.5">
              <BundleLabel scope="bundled" />
              <span className="text-sm font-semibold tabular-nums">$2,519</span>
            </div>
          </div>
          <Link to="/our-approach" className="shrink-0">
            <Button variant="ghost" size="sm" className="text-primary">
              See why <ArrowRight className="w-3.5 h-3.5 ml-1" />
            </Button>
          </Link>
        </div>
      </div>
    </section>

    <Footer />
  </div>
);

export default Index;
