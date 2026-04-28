/** True when the selected insurer slug is BCBS (BCBS plan dropdown applies). */
export function isBcbsInsurerKey(key: string): boolean {
  return key.toLowerCase() === 'bcbs';
}
