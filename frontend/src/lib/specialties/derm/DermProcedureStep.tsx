import { useState, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import {
  DERM_PROCEDURE_ROOT_ID,
  DERM_PROCEDURE_NODES,
  type DermLeafNode,
  type DermQuestionNode,
  type DermProcedureSelection,
} from './dermDecisionTree';
import { Stethoscope } from 'lucide-react';
import type { ProcedureStepProps } from '@/lib/specialties/types';

function getDermNode(id: string) {
  return DERM_PROCEDURE_NODES[id] ?? null;
}

export function DermProcedureStep({
  procedureState,
  setProcedureState,
  symptomNotes,
  setSymptomNotes,
}: ProcedureStepProps) {
  const value = procedureState as DermProcedureSelection | null;
  const [nodeId, setNodeId] = useState(DERM_PROCEDURE_ROOT_ID);
  const [pathIds, setPathIds] = useState<string[]>([DERM_PROCEDURE_ROOT_ID]);

  const reset = useCallback(() => {
    setNodeId(DERM_PROCEDURE_ROOT_ID);
    setPathIds([DERM_PROCEDURE_ROOT_ID]);
    setProcedureState(null);
  }, [setProcedureState]);

  const goTo = useCallback(
    (nextId: string) => {
      const next = getDermNode(nextId);
      if (!next) return;
      setPathIds(prev => [...prev, nextId]);
      setNodeId(nextId);
      setProcedureState(null);
    },
    [setProcedureState],
  );

  const goBack = useCallback(() => {
    if (pathIds.length <= 1) {
      reset();
      return;
    }
    const nextPath = pathIds.slice(0, -1);
    setPathIds(nextPath);
    setNodeId(nextPath[nextPath.length - 1]);
    setProcedureState(null);
  }, [pathIds, setProcedureState, reset]);

  const node = getDermNode(nodeId);

  const confirmLeaf = useCallback(
    (leaf: DermLeafNode) => {
      setProcedureState({
        bundleId: leaf.bundleId,
        scenarioId: leaf.scenarioId,
        cptCode: leaf.cptCode,
        title: leaf.title,
        pathIds: [...pathIds],
      } satisfies DermProcedureSelection);
    },
    [setProcedureState, pathIds],
  );

  return (
    <div className="space-y-6">
      <div>
        <Label htmlFor="symptom-notes" className="text-base font-semibold">
          Symptoms or goals <span className="text-muted-foreground font-normal">(optional)</span>
        </Label>
        <Textarea
          id="symptom-notes"
          placeholder="e.g. suspicious mole, wart on hand, skin rash for 2 weeks…"
          value={symptomNotes}
          onChange={e => setSymptomNotes(e.target.value)}
          className="mt-2 min-h-[72px] resize-y"
        />
      </div>

      <div className="rounded-2xl border border-border bg-card/50 p-4 space-y-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Stethoscope className="w-4 h-4 text-primary" />
          Find your procedure (Dermatology)
        </div>
        <p className="text-xs text-muted-foreground">
          Answer a few questions. We map your answers to a CPT code used for hospital price data in this demo.
        </p>

        {node && node.kind === 'question' && (
          <div className="space-y-3 animate-fade-in">
            <p className="font-medium text-foreground leading-snug">{node.prompt}</p>
            {node.hint && <p className="text-xs text-muted-foreground">{node.hint}</p>}
            <div className="flex flex-col gap-2">
              {(node as DermQuestionNode).options.map(opt => (
                <Button
                  key={opt.nextId}
                  type="button"
                  variant="outline"
                  className="h-auto min-h-11 whitespace-normal text-left justify-start px-4 py-3 border-primary/20 hover:bg-primary/5 hover:border-primary/40"
                  onClick={() => goTo(opt.nextId)}
                >
                  {opt.label}
                </Button>
              ))}
            </div>
          </div>
        )}

        {node && node.kind === 'leaf' && (
          <div className="space-y-3 rounded-xl bg-primary/5 border border-primary/15 p-4 animate-fade-in">
            <p className="text-xs font-semibold uppercase tracking-wide text-primary">Selected procedure</p>
            <p className="font-semibold text-lg">{(node as DermLeafNode).title}</p>
            <p className="text-sm text-muted-foreground leading-relaxed">{(node as DermLeafNode).description}</p>
            <p className="text-xs text-muted-foreground">
              CPT <span className="font-mono font-medium text-foreground">{(node as DermLeafNode).cptCode}</span>
            </p>
            <div className="flex flex-wrap gap-2 pt-1">
              <Button
                type="button"
                size="sm"
                className="bg-primary text-primary-foreground hover:bg-primary-hover"
                onClick={() => confirmLeaf(node as DermLeafNode)}
              >
                {value?.bundleId === (node as DermLeafNode).bundleId ? 'Confirmed ✓' : 'Use this for estimates'}
              </Button>
              <Button type="button" size="sm" variant="outline" onClick={reset}>
                Choose a different path
              </Button>
            </div>
          </div>
        )}

        <div className="flex gap-2 pt-2">
          <Button type="button" variant="outline" size="sm" onClick={goBack} disabled={pathIds.length <= 1}>
            Back
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={reset}>
            Start over
          </Button>
        </div>
      </div>
    </div>
  );
}
