import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Menu } from 'lucide-react';
import { Button } from '@/components/ui/button';
import CareCostLogo from '@/components/CareCostLogo';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';

/** Site navigation. No accounts (D19): the price tool is open to everyone at /start. */
const LINKS = [
  { to: '/why-it-matters', label: 'Why it matters' },
  { to: '/team', label: 'Team' },
  { to: '/our-data', label: 'Our Data' },
];

const Navbar = () => {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [compactLogo, setCompactLogo] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)');
    const sync = () => setCompactLogo(mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  }, []);

  const closeMobile = () => setMobileOpen(false);
  const sheetBtnClass = 'w-full h-12 justify-start text-base text-foreground font-medium';

  return (
    <nav
      className={cn(
        'sticky top-0 z-[60] bg-card/80 backdrop-blur-md border-b border-border',
        'pt-[max(0px,env(safe-area-inset-top))]',
      )}
    >
      <div className="container mx-auto flex items-center justify-between gap-2 min-h-14 md:h-16 py-2 md:py-0 px-4">
        <Link to="/" className="flex items-center min-w-0 pr-2" onClick={closeMobile}>
          <CareCostLogo showTagline={!compactLogo} compact={compactLogo} />
        </Link>

        <div className="hidden md:flex items-center gap-2 lg:gap-3">
          {LINKS.map((l) => (
            <Link key={l.to} to={l.to}>
              <Button variant="ghost" size="sm">{l.label}</Button>
            </Link>
          ))}
          <Link to="/start">
            <Button size="sm" className="bg-primary text-primary-foreground hover:bg-primary-hover">
              Get started
            </Button>
          </Link>
        </div>

        <div className="flex md:hidden items-center shrink-0">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button
                variant="outline"
                size="icon"
                className="h-11 w-11 shrink-0 touch-manipulation"
                aria-label="Open menu"
              >
                <Menu className="h-5 w-5" />
              </Button>
            </SheetTrigger>
            <SheetContent side="right" className="w-[min(100vw-2rem,20rem)] flex flex-col">
              <SheetHeader className="text-left border-b border-border pb-4 mb-2">
                <SheetTitle className="text-base">Menu</SheetTitle>
              </SheetHeader>
              <div className="flex flex-col gap-1 py-2 overflow-y-auto flex-1">
                {LINKS.map((l) => (
                  <Link key={l.to} to={l.to} onClick={closeMobile}>
                    <Button variant="ghost" className={sheetBtnClass}>{l.label}</Button>
                  </Link>
                ))}
                <Link to="/start" onClick={closeMobile}>
                  <Button className={cn(sheetBtnClass, 'mt-1 bg-primary text-primary-foreground hover:bg-primary-hover')}>
                    Get started
                  </Button>
                </Link>
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </nav>
  );
};

export default Navbar;
