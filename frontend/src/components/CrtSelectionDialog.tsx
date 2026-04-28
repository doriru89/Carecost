import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

export interface CrtOption {
  cpt: string;
  label: string;
  desc: string;
  bundleId: string;
}

export const EGD_PROCEDURES: CrtOption[] = [
  { cpt: '43235', label: 'EGD diagnostic', desc: 'Upper endoscopy — diagnostic evaluation', bundleId: 'egd_with_biopsy' },
  { cpt: '43235', label: 'EGD with biopsy', desc: 'Upper endoscopy with tissue biopsy', bundleId: 'egd_with_biopsy' },
  { cpt: '43244', label: 'EGD band ligation', desc: 'Upper endoscopy with variceal banding', bundleId: 'egd_band_ligation' },
  { cpt: '43249', label: 'EGD with dilation', desc: 'Upper endoscopy with esophageal dilation', bundleId: 'egd_dilation' },
  { cpt: '43255', label: 'EGD bleeding control', desc: 'Upper endoscopy for hemorrhage management', bundleId: 'egd_bleeding' },
];

interface CrtSelectionDialogProps {
  open: boolean;
  onSelect: (cpt: string, label: string, bundleId: string) => void;
}

const CrtSelectionDialog = ({ open, onSelect }: CrtSelectionDialogProps) => {
  const [selected, setSelected] = useState<number | null>(null);

  return (
    <Dialog open={open} onOpenChange={() => {}}>
      <DialogContent
        className="sm:max-w-lg"
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => e.preventDefault()}
        hideClose
      >
        <DialogHeader>
          <DialogTitle className="text-xl">What procedure do you need?</DialogTitle>
          <DialogDescription>
            Select the specific procedure so we can show you accurate pricing from your insurer.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2 mt-2">
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
