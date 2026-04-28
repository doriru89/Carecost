export type FairHealthComponent = {
  label: string;
  amount: number;
};

export type FairHealthBreakdown = {
  total: number;
  components: FairHealthComponent[];
};

type FairHealthFields = {
  fh_physician_in_network?: number | null;
  fh_facility_hosp_in_network?: number | null;
  fh_anesthesia_in_network?: number | null;
  fh_pathology_in_network?: number | null;
};

const FH_FIELDS: { key: keyof FairHealthFields; label: string }[] = [
  { key: 'fh_physician_in_network', label: 'Physician' },
  { key: 'fh_facility_hosp_in_network', label: 'Facility' },
  { key: 'fh_anesthesia_in_network', label: 'Anesthesia' },
  { key: 'fh_pathology_in_network', label: 'Pathology' },
];

/** Sum FAIR Health 80th percentile components. Returns null if all fields are null/missing. */
export function computeFairHealthTotal(hospital: FairHealthFields): FairHealthBreakdown | null {
  const components: FairHealthComponent[] = [];
  let total = 0;

  for (const { key, label } of FH_FIELDS) {
    const val = hospital[key];
    if (val != null && val > 0) {
      components.push({ label, amount: val });
      total += val;
    }
  }

  return components.length > 0 ? { total, components } : null;
}
