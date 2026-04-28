import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import GiProcedureWizard from '@/components/GiProcedureWizard';
import type { GiProcedureSelection } from '@/lib/giDecisionTree';

interface AiGuidanceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onProcedureSelect: (cpt: string, label: string, bundleId: string) => void;
}

const AiGuidanceDialog = ({ open, onOpenChange, onProcedureSelect }: AiGuidanceDialogProps) => {
  const [procedureSelection, setProcedureSelection] = useState<GiProcedureSelection | null>(null);
  const [symptomNotes, setSymptomNotes] = useState('');

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl">AI Procedure Guidance</DialogTitle>
          <DialogDescription>
            Not sure which procedure to look for? Describe your symptoms and our AI will help narrow it down.
          </DialogDescription>
        </DialogHeader>
        <GiProcedureWizard
          value={procedureSelection}
          onChange={(sel) => {
            setProcedureSelection(sel);
            if (sel) {
              onProcedureSelect(sel.cptCode, sel.title, sel.bundleId);
              onOpenChange(false);
            }
          }}
          symptomNotes={symptomNotes}
          onSymptomNotesChange={setSymptomNotes}
        />
      </DialogContent>
    </Dialog>
  );
};

export default AiGuidanceDialog;
