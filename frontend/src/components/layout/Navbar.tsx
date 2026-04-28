import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Menu, Settings, LogOut } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import { Button } from '@/components/ui/button';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import CareCostLogo from '@/components/CareCostLogo';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';

const Navbar = () => {
  const { isAuthenticated, profile, user, logout } = useAuth();
  const navigate = useNavigate();
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

  const initials = useMemo(() => {
    const name = profile?.fullName || user?.email || '';
    if (!name) return '?';
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    return name.slice(0, 2).toUpperCase();
  }, [profile?.fullName, user?.email]);

  const navLinkClass = 'text-foreground justify-start font-medium';
  const sheetBtnClass = 'w-full h-12 justify-start text-base';

  return (
    <nav
      className={cn(
        'sticky top-0 z-[60] bg-card/80 backdrop-blur-md border-b border-border',
        'pt-[max(0px,env(safe-area-inset-top))]',
      )}
    >
      <div className="container mx-auto flex items-center justify-between gap-2 min-h-14 md:h-16 py-2 md:py-0 px-4">
        <Link to="/" className="flex items-center min-w-0 pr-2" onClick={closeMobile}>
          <CareCostLogo
            showTagline={!isAuthenticated && !compactLogo}
            compact={isAuthenticated || compactLogo}
          />
        </Link>

        {/* Desktop nav */}
        <div className="hidden md:flex items-center gap-2 lg:gap-3">
          <Link to="/">
            <Button variant="ghost" size="sm">Home</Button>
          </Link>
          <Link to="/why-it-matters">
            <Button variant="ghost" size="sm">Why it matters</Button>
          </Link>
          <Link to="/team">
            <Button variant="ghost" size="sm">Team</Button>
          </Link>
          <Link to="/our-data">
            <Button variant="ghost" size="sm">Our Data</Button>
          </Link>
          <Link to="/map">
            <Button variant="ghost" size="sm">Map</Button>
          </Link>
          {isAuthenticated ? (
            <>
              <Link to="/saved">
                <Button variant="ghost" size="sm">Saved</Button>
              </Link>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon" className="rounded-full h-9 w-9">
                    <Avatar className="h-8 w-8">
                      <AvatarFallback className="bg-primary/10 text-primary text-xs font-semibold">
                        {initials}
                      </AvatarFallback>
                    </Avatar>
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48">
                  <DropdownMenuItem asChild>
                    <Link to="/settings" className="flex items-center gap-2 cursor-pointer">
                      <Settings className="h-4 w-4" />
                      Settings
                    </Link>
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="flex items-center gap-2 cursor-pointer"
                    onClick={() => { logout(); navigate('/'); }}
                  >
                    <LogOut className="h-4 w-4" />
                    Sign out
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          ) : (
            <>
              <Link to="/login">
                <Button variant="ghost" size="sm">Log in</Button>
              </Link>
              <Link to="/signup">
                <Button size="sm" className="bg-primary text-primary-foreground hover:bg-primary-hover">
                  Get started
                </Button>
              </Link>
            </>
          )}
        </div>

        {/* Mobile menu */}
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
                <Link to="/" onClick={closeMobile}>
                  <Button variant="ghost" className={cn(sheetBtnClass, navLinkClass)}>Home</Button>
                </Link>
                <Link to="/why-it-matters" onClick={closeMobile}>
                  <Button variant="ghost" className={cn(sheetBtnClass, navLinkClass)}>Why it matters</Button>
                </Link>
                <Link to="/team" onClick={closeMobile}>
                  <Button variant="ghost" className={cn(sheetBtnClass, navLinkClass)}>Team</Button>
                </Link>
                <Link to="/our-data" onClick={closeMobile}>
                  <Button variant="ghost" className={cn(sheetBtnClass, navLinkClass)}>Our Data</Button>
                </Link>
                <Link to="/map" onClick={closeMobile}>
                  <Button variant="ghost" className={cn(sheetBtnClass, navLinkClass)}>Map</Button>
                </Link>
                {isAuthenticated ? (
                  <>
                    <Link to="/saved" onClick={closeMobile}>
                      <Button variant="ghost" className={cn(sheetBtnClass, navLinkClass)}>Saved</Button>
                    </Link>
                    <Link to="/settings" onClick={closeMobile}>
                      <Button variant="ghost" className={cn(sheetBtnClass, navLinkClass)}>Settings</Button>
                    </Link>
                    <Button
                      variant="outline"
                      className={cn(sheetBtnClass, 'mt-2')}
                      onClick={() => {
                        closeMobile();
                        logout();
                        navigate('/');
                      }}
                    >
                      Sign out
                    </Button>
                  </>
                ) : (
                  <>
                    <Link to="/login" onClick={closeMobile}>
                      <Button variant="ghost" className={cn(sheetBtnClass, navLinkClass)}>Log in</Button>
                    </Link>
                    <Link to="/signup" onClick={closeMobile}>
                      <Button className={cn(sheetBtnClass, 'mt-1 bg-primary text-primary-foreground hover:bg-primary-hover')}>
                        Get started
                      </Button>
                    </Link>
                  </>
                )}
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </div>
    </nav>
  );
};

export default Navbar;
