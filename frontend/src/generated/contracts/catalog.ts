// GENERATED from contracts/catalog.schema.json by `python -m app.api_contracts`. Do not edit.
// A drift test (backend/tests/contracts) fails when this file is stale.

export interface Catalog {
  version: string;
  care_paths: CatalogPath[];
  services: CatalogService[];
}

export interface CatalogCode {
  code: string;
  role: "primary" | "alternative" | "add_on" | "drug" | "guidance";
  /**
   * Our own short words (no AMA descriptor text)
   */
  description: string;
}

export interface CatalogPath {
  id: string;
  title: string;
  /**
   * care_paths Scope.area, e.g. msk_shoulder
   */
  area: string;
  review_status: "pending_austin" | "changes_requested" | "approved";
}

export interface CatalogService {
  service_id: string;
  plain_name: string;
  technical_name: string;
  kind: "referral" | "visit" | "imaging" | "procedure" | "lab" | "anesthesia" | "therapy" | "medication" | "supply";
  areas: ("ortho" | "skin" | "gi" | "urgent_care")[];
  codes: CatalogCode[];
  /**
   * care path ids that include this service
   */
  care_paths: string[];
  glossary_keys: string[];
}
