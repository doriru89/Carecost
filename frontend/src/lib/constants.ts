import type { InsurerOptionApi } from '@/api/client';

export const FALLBACK_INSURERS: InsurerOptionApi[] = [
  { key: 'bcbs', label: 'Blue Cross Blue Shield (BCBS)', payer_id: 'bcbs' },
  { key: 'aetna', label: 'Aetna', payer_id: 'aetna' },
  { key: 'harvard_pilgrim', label: 'Harvard Pilgrim', payer_id: 'harvard_pilgrim' },
  { key: 'uhc', label: 'UnitedHealthcare (UHC)', payer_id: 'uhc' },
];
