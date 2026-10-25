import { useState, type ReactNode } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/**
 * Hover on desktop, tap on a phone: a Popover that also opens on pointer hover.
 * Hover text is a supplement, never the only explanation (D8).
 */
export function InfoTip({
  trigger,
  children,
  className,
  label,
}: {
  trigger: ReactNode;
  children: ReactNode;
  className?: string;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        asChild
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        <button type="button" aria-label={label} className={cn("inline-flex items-center text-left", className)}>
          {trigger}
        </button>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        className="w-72 text-xs leading-relaxed p-3"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        {children}
      </PopoverContent>
    </Popover>
  );
}
