import { useState, useEffect } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import GiProcedureWizard from '@/components/GiProcedureWizard';
import { SPECIALTY_SELECT_OPTIONS } from '@/lib/specialties';
import { isGastroProcedureComplete } from '@/lib/specialties/gastro/intake';
import type { GiProcedureSelection } from '@/lib/giDecisionTree';
import { loadGiContinuity } from '@/lib/giContinuity';
import { useAuth } from '@/context/AuthContext';

interface ProcedureGateDialogProps {
  open: boolean;
  onComplete: (sel: { cpt: string; label: string; bundleId: string }) => void;
}

/** Top offset matching Navbar (`min-h-14` + mobile `py-2` + safe area) so the bar stays clear of the dimmer. */
const GATE_BACKDROP_TOP =
  'top-[max(4.75rem,calc(env(safe-area-inset-top)+3.25rem))] md:top-16';

/**
 * Map entry gate: specialty (Gastro vs Dermatology coming soon) → symptom + AI GI wizard → CPT/bundle for estimates.
 * Non-modal + inset backdrop: map stays gated, but Navbar (team, profile, etc.) stays clickable (Radix modal dialogs block all outside pointers).
 */
const ProcedureGateDialog = ({ open, onComplete }: ProcedureGateDialogProps) => {
  const { user } = useAuth();
  const [step, setStep] = useState<1 | 2>(1);
  const [specialty, setSpecialty] = useState('');
  const [procedureSelection, setProcedureSelection] = useState<GiProcedureSelection | null>(null);
  const [symptomNotes, setSymptomNotes] = useState('');

  useEffect(() => {
    if (!open) return;
    const c = loadGiContinuity(user?.email);
    const hasText = (c?.symptomNotes?.trim().length ?? 0) > 0;
    if (c?.procedure || hasText) {
      setStep(2);
      setSpecialty('Gastroenterology');
      setSymptomNotes(c?.symptomNotes ?? '');
      setProcedureSelection(
        c?.procedure
          ? {
              bundleId: c.procedure.bundleId,
              scenarioId: c.procedure.scenarioId,
              cptCode: c.procedure.cptCode,
              title: c.procedure.title,
              description: c.procedure.description ?? '',
              pathIds: c.procedure.pathIds ?? [],
            }
          : null,
      );
    } else {
      setStep(1);
      setSpecialty('');
      setProcedureSelection(null);
      setSymptomNotes('');
    }
  }, [open, user?.email]);

  const handleProcedureChange = (v: GiProcedureSelection | null) => {
    setProcedureSelection(v);
    if (v != null && isGastroProcedureComplete(v)) {
      onComplete({ cpt: v.cptCode, label: v.title, bundleId: v.bundleId });
    }
  };

  const allowChromePointer = (target: EventTarget | null) =>
    target instanceof Element && Boolean(target.closest('nav'));

  return (
    <DialogPrimitive.Root open={open} onOpenChange={() => {}} modal={false}>
      <DialogPrimitive.Portal>
        <div
          className={cn('pointer-events-auto fixed inset-x-0 bottom-0 z-50 bg-black/80', GATE_BACKDROP_TOP)}
          aria-hidden
        />
        <DialogPrimitive.Content
          className={cn(
            'fixed left-[50%] top-[50%] z-[51] flex max-h-[90vh] w-full max-w-lg translate-x-[-50%] translate-y-[-50%] flex-col gap-0 border bg-background p-0 shadow-lg duration-200',
            'data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0',
            'data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%]',
            'data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%] sm:max-w-2xl sm:rounded-lg',
          )}
          onPointerDownOutside={e => {
            if (allowChromePointer(e.target)) return;
            e.preventDefault();
          }}
          onInteractOutside={e => {
            if (allowChromePointer(e.target)) return;
            e.preventDefault();
          }}
          onEscapeKeyDown={e => e.preventDefault()}
        >
          <div className="px-6 pt-6 pb-4 border-b border-border shrink-0">
            <DialogHeader>
              <DialogTitle className="text-xl">
                {step === 1 ? 'Choose a specialty' : 'Your symptoms & procedure'}
              </DialogTitle>
              <DialogDescription>
                {step === 1
                  ? 'Select a specialty. Only Gastroenterology is available in this demo; more specialties are coming soon.'
                  : 'Tell us about your symptoms first. The assistant refines what you share until we pick the most likely procedure code for your estimate—not the other way around.'}
              </DialogDescription>
            </DialogHeader>
          </div>

          <div className="overflow-y-auto flex-1 px-6 py-4 min-h-0">
            {step === 1 && (
              <div className="space-y-4">
                <div>
                  <Label>Medical specialty</Label>
                  <Select value={specialty || undefined} onValueChange={setSpecialty}>
                    <SelectTrigger className="mt-1.5">
                      <SelectValue placeholder="Select a specialty" />
                    </SelectTrigger>
                    <SelectContent>
                      {SPECIALTY_SELECT_OPTIONS.map(opt => (
                        <SelectItem key={opt.id} value={opt.id} disabled={!opt.available}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <Button
                  type="button"
                  className="w-full bg-primary text-primary-foreground hover:bg-primary-hover"
                  disabled={specialty !== 'Gastroenterology'}
                  onClick={() => setStep(2)}
                >
                  Continue
                </Button>
              </div>
            )}

            {step === 2 && (
              <div className="space-y-4">
                <Button type="button" variant="ghost" size="sm" className="-mt-1 -ml-2" onClick={() => setStep(1)}>
                  ← Back to specialty
                </Button>
                <GiProcedureWizard
                  value={procedureSelection}
                  onChange={handleProcedureChange}
                  symptomNotes={symptomNotes}
                  onSymptomNotesChange={setSymptomNotes}
                />
              </div>
            )}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
};

export default ProcedureGateDialog;
