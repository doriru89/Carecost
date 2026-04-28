/**
 * Derm decision tree: symptom / visit-type questions → bundle (CPT) for estimates.
 * Keys must match backend specialty_config.py Dermatology bundle_cpt.
 */

export type DermQuestionNode = {
  kind: 'question';
  id: string;
  prompt: string;
  hint?: string;
  options: { label: string; nextId: string }[];
};

export type DermLeafNode = {
  kind: 'leaf';
  id: string;
  bundleId: string;
  scenarioId: string;
  cptCode: string;
  title: string;
  description: string;
};

export type DermTreeNode = DermQuestionNode | DermLeafNode;

export type DermProcedureSelection = {
  bundleId: string;
  scenarioId: string;
  cptCode: string;
  title: string;
  pathIds: string[];
};

export const DERM_PROCEDURE_ROOT_ID = 'derm_start';

export const DERM_PROCEDURE_NODES: Record<string, DermTreeNode> = {
  derm_start: {
    kind: 'question',
    id: 'derm_start',
    prompt: 'What best describes your dermatology visit?',
    hint: 'We use your answers to find the right procedure code for price comparison.',
    options: [
      { label: 'Skin check, rash, acne, or general concern', nextId: 'leaf_office_visit' },
      { label: 'Biopsy — doctor wants to sample a spot', nextId: 'biopsy_type' },
      { label: 'Mole or lesion removal', nextId: 'removal_type' },
      { label: 'Wart, skin tag, or lesion destruction', nextId: 'leaf_lesion_destruction' },
      { label: 'Mohs surgery (skin cancer)', nextId: 'mohs_location' },
    ],
  },

  biopsy_type: {
    kind: 'question',
    id: 'biopsy_type',
    prompt: 'What type of biopsy?',
    hint: 'If unsure, shave/tangential is most common for surface spots.',
    options: [
      { label: 'Shave / tangential biopsy (surface scrape)', nextId: 'leaf_biopsy_tangential' },
      { label: 'Punch biopsy (deeper circular sample)', nextId: 'leaf_biopsy_punch' },
      { label: 'Not sure yet', nextId: 'leaf_biopsy_tangential' },
    ],
  },

  removal_type: {
    kind: 'question',
    id: 'removal_type',
    prompt: 'Is the mole or lesion suspected to be cancerous?',
    options: [
      { label: 'No — benign / cosmetic removal', nextId: 'leaf_mole_benign' },
      { label: 'Yes — possibly cancerous or pre-cancerous', nextId: 'leaf_mole_malignant' },
      { label: 'Not sure — awaiting biopsy results', nextId: 'leaf_mole_benign' },
    ],
  },

  mohs_location: {
    kind: 'question',
    id: 'mohs_location',
    prompt: 'Where on the body is the Mohs surgery planned?',
    options: [
      { label: 'Head, neck, hands, feet, or genitalia', nextId: 'leaf_mohs_head_neck' },
      { label: 'Trunk, arms, or legs', nextId: 'leaf_mohs_trunk' },
    ],
  },

  // ── Leaf nodes ──

  leaf_office_visit: {
    kind: 'leaf',
    id: 'leaf_office_visit',
    bundleId: 'derm_office_visit_detailed',
    scenarioId: 'derm_office_visit_detailed',
    cptCode: '99214',
    title: 'Dermatology Office Visit',
    description: 'Established patient visit, detailed evaluation. Most common derm visit code.',
  },

  leaf_biopsy_tangential: {
    kind: 'leaf',
    id: 'leaf_biopsy_tangential',
    bundleId: 'skin_biopsy_tangential',
    scenarioId: 'skin_biopsy_tangential',
    cptCode: '11102',
    title: 'Skin Biopsy — Tangential / Shave',
    description: 'Surface biopsy of a single lesion. Pathology billed separately.',
  },

  leaf_biopsy_punch: {
    kind: 'leaf',
    id: 'leaf_biopsy_punch',
    bundleId: 'skin_biopsy_punch',
    scenarioId: 'skin_biopsy_punch',
    cptCode: '11104',
    title: 'Skin Biopsy — Punch',
    description: 'Deeper circular sample. Pathology billed separately.',
  },

  leaf_mole_benign: {
    kind: 'leaf',
    id: 'leaf_mole_benign',
    bundleId: 'mole_removal_benign_small',
    scenarioId: 'mole_removal_benign_small',
    cptCode: '11400',
    title: 'Mole Removal — Benign',
    description: 'Excision of benign lesion (≤0.5 cm, trunk/extremity). Pathology billed separately.',
  },

  leaf_mole_malignant: {
    kind: 'leaf',
    id: 'leaf_mole_malignant',
    bundleId: 'mole_removal_malignant_small',
    scenarioId: 'mole_removal_malignant_small',
    cptCode: '11600',
    title: 'Mole Removal — Malignant / Suspected',
    description: 'Excision of malignant lesion (≤0.5 cm, trunk/extremity). Pathology billed separately.',
  },

  leaf_lesion_destruction: {
    kind: 'leaf',
    id: 'leaf_lesion_destruction',
    bundleId: 'lesion_destruction_first',
    scenarioId: 'lesion_destruction_first',
    cptCode: '17000',
    title: 'Lesion Destruction (Wart, Skin Tag)',
    description: 'Destruction of first lesion by freezing, laser, or chemical. Additional lesions billed separately.',
  },

  leaf_mohs_head_neck: {
    kind: 'leaf',
    id: 'leaf_mohs_head_neck',
    bundleId: 'mohs_surgery_head_neck',
    scenarioId: 'mohs_surgery_head_neck',
    cptCode: '17311',
    title: 'Mohs Surgery — Head/Neck',
    description: 'Mohs micrographic surgery, first stage. Additional stages billed separately. Facility fee separate at hospital sites.',
  },

  leaf_mohs_trunk: {
    kind: 'leaf',
    id: 'leaf_mohs_trunk',
    bundleId: 'mohs_surgery_trunk',
    scenarioId: 'mohs_surgery_trunk',
    cptCode: '17313',
    title: 'Mohs Surgery — Trunk/Extremity',
    description: 'Mohs micrographic surgery, first stage (trunk/arms/legs). Additional stages billed separately.',
  },
};

/** All derm leaf procedures for the procedure filter dropdown. */
export const DERM_PROCEDURES: { cpt: string; label: string; bundleId: string }[] = Object.values(DERM_PROCEDURE_NODES)
  .filter((n): n is DermLeafNode => n.kind === 'leaf')
  .map(n => ({ cpt: n.cptCode, label: n.title, bundleId: n.bundleId }));
