/**
 * GI decision tree: symptom / visit-type questions → bundle (CPT) for estimates.
 * Keys must match backend `BUNDLE_CPT_AZ_MVP` / `SCENARIO_IDS`.
 */

export type GiQuestionNode = {
  kind: 'question';
  id: string;
  prompt: string;
  /** Subtext for clinicians — optional */
  hint?: string;
  options: { label: string; nextId: string }[];
};

export type GiLeafNode = {
  kind: 'leaf';
  id: string;
  /** Backend bundle + scenario id */
  bundleId: string;
  scenarioId: string;
  cptCode: string;
  title: string;
  description: string;
};

export type GiTreeNode = GiQuestionNode | GiLeafNode;

export const GI_PROCEDURE_ROOT_ID = 'gi_start';

export const GI_PROCEDURE_NODES: Record<string, GiTreeNode> = {
  gi_start: {
    kind: 'question',
    id: 'gi_start',
    prompt: 'What best describes why you need GI care?',
    hint: 'We use your answers to pick the most likely procedure code for price estimates.',
    options: [
      { label: 'Colon / rectum (colonoscopy, bleeding, screening)', nextId: 'colon_intro' },
      { label: 'Upper GI — esophagus or stomach (EGD / endoscopy)', nextId: 'upper_intro' },
      { label: 'Imaging or advanced testing', nextId: 'advanced_intro' },
    ],
  },

  colon_intro: {
    kind: 'question',
    id: 'colon_intro',
    prompt: 'Is this visit mainly for screening, or because you have symptoms / a follow-up issue?',
    options: [
      { label: 'Screening — no current symptoms (routine prevention)', nextId: 'leaf_colonoscopy_screening' },
      { label: 'Symptoms, abnormal test, or follow-up after prior findings', nextId: 'colon_symptom_detail' },
    ],
  },

  colon_symptom_detail: {
    kind: 'question',
    id: 'colon_symptom_detail',
    prompt: 'Which situation is closest?',
    options: [
      {
        label: 'Evaluation for bleeding, stool changes, pain, or unexplained symptoms',
        nextId: 'leaf_colonoscopy_diagnostic',
      },
      { label: 'Polyp removal or known / suspected polyps', nextId: 'leaf_colonoscopy_polyp' },
      { label: 'Biopsies are expected during the procedure', nextId: 'leaf_colonoscopy_with_biopsy' },
    ],
  },

  upper_intro: {
    kind: 'question',
    id: 'upper_intro',
    prompt: 'What is the main goal of the upper endoscopy (EGD)?',
    options: [
      {
        label: 'Biopsy or evaluation for reflux, dyspepsia, or similar (typical EGD)',
        nextId: 'leaf_egd_with_biopsy',
      },
      { label: 'Bleeding evaluation or bleeding control', nextId: 'leaf_egd_bleeding' },
      { label: 'Stricture or dilation', nextId: 'leaf_egd_dilation' },
    ],
  },

  advanced_intro: {
    kind: 'question',
    id: 'advanced_intro',
    prompt: 'Which type of test?',
    options: [
      { label: 'CT abdomen / pelvis', nextId: 'leaf_gi_imaging_ct' },
      { label: 'Capsule endoscopy', nextId: 'leaf_capsule_endoscopy' },
    ],
  },

  leaf_colonoscopy_screening: {
    kind: 'leaf',
    id: 'leaf_colonoscopy_screening',
    bundleId: 'colonoscopy_screening',
    scenarioId: 'colonoscopy_screening',
    cptCode: '45378',
    title: 'Screening colonoscopy',
    description: 'Average screening colonoscopy — preventive care when you have no active symptoms.',
  },
  leaf_colonoscopy_diagnostic: {
    kind: 'leaf',
    id: 'leaf_colonoscopy_diagnostic',
    bundleId: 'colonoscopy_diagnostic',
    scenarioId: 'colonoscopy_diagnostic',
    cptCode: '45378',
    title: 'Diagnostic colonoscopy',
    description: 'Colonoscopy to evaluate symptoms or abnormal findings.',
  },
  leaf_colonoscopy_polyp: {
    kind: 'leaf',
    id: 'leaf_colonoscopy_polyp',
    bundleId: 'colonoscopy_polyp',
    scenarioId: 'colonoscopy_polyp',
    cptCode: '45385',
    title: 'Colonoscopy with polypectomy',
    description: 'Procedure focused on polyp removal or similar interventions.',
  },
  leaf_colonoscopy_with_biopsy: {
    kind: 'leaf',
    id: 'leaf_colonoscopy_with_biopsy',
    bundleId: 'colonoscopy_with_biopsy',
    scenarioId: 'colonoscopy_with_biopsy',
    cptCode: '45380',
    title: 'Colonoscopy with biopsy',
    description: 'Colonoscopy including biopsies when indicated.',
  },
  leaf_egd_with_biopsy: {
    kind: 'leaf',
    id: 'leaf_egd_with_biopsy',
    bundleId: 'egd_with_biopsy',
    scenarioId: 'egd_with_biopsy',
    cptCode: '43235',
    title: 'EGD (upper endoscopy) with biopsy',
    description: 'Esophagogastroduodenoscopy with diagnostic biopsy when needed.',
  },
  leaf_egd_bleeding: {
    kind: 'leaf',
    id: 'leaf_egd_bleeding',
    bundleId: 'egd_bleeding',
    scenarioId: 'egd_bleeding',
    cptCode: '43255',
    title: 'EGD for bleeding',
    description: 'Upper endoscopy for bleeding evaluation or control.',
  },
  leaf_egd_dilation: {
    kind: 'leaf',
    id: 'leaf_egd_dilation',
    bundleId: 'egd_dilation',
    scenarioId: 'egd_dilation',
    cptCode: '43249',
    title: 'EGD with dilation',
    description: 'Endoscopy with dilation of stricture or similar.',
  },
  leaf_gi_imaging_ct: {
    kind: 'leaf',
    id: 'leaf_gi_imaging_ct',
    bundleId: 'gi_imaging_ct',
    scenarioId: 'gi_imaging_ct',
    cptCode: '74176',
    title: 'CT abdomen / pelvis without contrast',
    description: 'Cross-sectional imaging commonly used in GI workups (demo uses single CPT row).',
  },
  leaf_capsule_endoscopy: {
    kind: 'leaf',
    id: 'leaf_capsule_endoscopy',
    bundleId: 'capsule_endoscopy',
    scenarioId: 'capsule_endoscopy',
    cptCode: '91110',
    title: 'Capsule endoscopy',
    description: 'Wireless capsule study of the small bowel.',
  },
};

export type GiProcedureSelection = {
  bundleId: string;
  scenarioId: string;
  cptCode: string;
  title: string;
  description: string;
  /** Question IDs visited for transparency */
  pathIds: string[];
};

export function getGiNode(id: string): GiTreeNode | undefined {
  return GI_PROCEDURE_NODES[id];
}

/** Find a leaf node by bundle id (e.g. restoring saved continuity). */
export function findLeafByBundleId(bundleId: string): GiLeafNode | undefined {
  for (const n of Object.values(GI_PROCEDURE_NODES)) {
    if (n.kind === 'leaf' && n.bundleId === bundleId) return n;
  }
  return undefined;
}

/** All leaf procedures for map filter / intake (bundleId is unique; CPT may repeat). */
export function getGiLeafSelectOptions(): { bundleId: string; cptCode: string; title: string }[] {
  return Object.values(GI_PROCEDURE_NODES)
    .filter((n): n is GiLeafNode => n.kind === 'leaf')
    .map(n => ({ bundleId: n.bundleId, cptCode: n.cptCode, title: n.title }));
}

/** BFS path from root to a leaf (for applying AI-proposed leaves while staying tree-valid). */
export function getPathIdsToLeaf(leafId: string): string[] | null {
  const target = GI_PROCEDURE_NODES[leafId];
  if (!target || target.kind !== 'leaf') return null;

  const queue: { id: string; path: string[] }[] = [{ id: GI_PROCEDURE_ROOT_ID, path: [GI_PROCEDURE_ROOT_ID] }];
  const seen = new Set<string>();

  while (queue.length > 0) {
    const { id, path } = queue.shift()!;
    if (seen.has(id)) continue;
    seen.add(id);

    const n = GI_PROCEDURE_NODES[id];
    if (!n) continue;

    if (n.kind === 'leaf') {
      if (n.id === leafId) return path;
      continue;
    }

    for (const opt of n.options) {
      queue.push({ id: opt.nextId, path: [...path, opt.nextId] });
    }
  }
  return null;
}
