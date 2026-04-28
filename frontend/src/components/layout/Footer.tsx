import { ShieldCheck } from 'lucide-react';

const Footer = () => (
  <footer className="border-t border-border py-6 sm:py-8 mt-auto pb-[max(1.5rem,env(safe-area-inset-bottom))]">
    <div className="container mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-muted-foreground">
      <p className="max-w-xl text-center sm:text-left">
        Estimates depend on your plan and insurer rules; confirm with your plan documents.
      </p>
      <div className="flex flex-col items-center sm:items-end gap-3 sm:gap-2">
        <p className="inline-flex items-center gap-1.5 text-center sm:text-right max-w-[20rem] sm:max-w-xs leading-snug">
          <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
          <span>
            Your account is secured with encrypted credentials. We never store your password in plain text.
          </span>
        </p>
        <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
          <a href="#" className="hover:text-foreground transition-colors">Privacy</a>
          <a href="#" className="hover:text-foreground transition-colors">Terms</a>
        </div>
      </div>
    </div>
  </footer>
);

export default Footer;
