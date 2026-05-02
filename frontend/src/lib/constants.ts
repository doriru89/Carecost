import type { InsurerOptionApi } from '@/api/client';
import _payers from '../generated/payers.json';

export const FALLBACK_INSURERS: InsurerOptionApi[] = _payers;
