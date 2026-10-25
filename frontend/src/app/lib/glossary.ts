import glossary from "../content/glossary.json";

export interface Term {
  plain_name: string;
  technical_name: string;
  short: string;
  link_out: { label: string; url: string }[];
}

/** Hover text, only from content/glossary/glossary.yaml (via npm run content:build). */
export const TERMS = (glossary as { terms: Record<string, Term> }).terms;
export const GLOSSARY_CREDIT = (glossary as { credit: string }).credit;
