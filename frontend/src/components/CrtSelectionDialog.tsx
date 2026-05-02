import { useEffect, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

import { GI_PROCEDURES, type CrtOption } from '@/lib/procedures';

export type { CrtOption };
export const EGD_PROCEDURES = GI_PROCEDURES;

interface CrtSelectionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (cpt: string, label: string, bundleId: string) => void;
}

const CrtSelectionDialog = ({ open, onOpenChange, onSelect }: CrtSelectionDialogProps) => {
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    if (!open) {
      setSelected(null);
    }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-xl">What procedure do you need?</DialogTitle>
          <DialogDescription>
            Select the specific procedure so we can show you accurate pricing from your insurer.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2 mt-2 max-h-[60vh] overflow-y-auto">
          {EGD_PROCEDURES.map((proc, i) => (
            <button
              key={`${proc.bundleId}-${i}`}
              type="button"
              onClick={() => setSelected(i)}
              className={`w-full text-left rounded-xl border px-4 py-3 transition-colors ${
                selected === i
                  ? 'border-primary bg-primary/5 ring-1 ring-primary'
                  : 'border-border hover:border-primary/40 hover:bg-muted/50'
              }`}
            >
              <p className="font-medium text-sm">{proc.label}</p>
              <p className="text-xs text-muted-foreground mt-0.5">{proc.desc}</p>
              <p className="text-xs text-muted-foreground font-mono mt-0.5">CPT {proc.cpt}</p>
            </button>
          ))}
        </div>

        <Button
          className="w-full mt-3"
          disabled={selected === null}
          onClick={() => {
            if (selected !== null) {
              const proc = EGD_PROCEDURES[selected];
              onSelect(proc.cpt, proc.label, proc.bundleId);
              onOpenChange(false);
            }
          }}
        >
          Show prices
        </Button>
      </DialogContent>
    </Dialog>
  );
};

export default CrtSelectionDialog;
