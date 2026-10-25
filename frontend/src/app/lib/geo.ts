/**
 * Distance is computed only in the browser (§4.3, D1): the quote request has no location field,
 * and nothing here sends one anywhere. A typed ZIP is looked up in a bundled MA centroid table.
 */
import zipTable from "../content/ma_zips.json";

export interface LatLon {
  lat: number;
  lon: number;
}

export interface UserLocation extends LatLon {
  /** what the person gave us, shown back to them */
  label: string;
  kind: "zip" | "device";
}

const ZIPS = (zipTable as unknown as { zips: Record<string, [number, number]> }).zips;

export function zipToLocation(zip: string): UserLocation | null {
  const z = zip.trim().slice(0, 5);
  if (!/^\d{5}$/.test(z)) return null;
  const hit = ZIPS[z];
  return hit ? { lat: hit[0], lon: hit[1], label: `ZIP ${z}`, kind: "zip" } : null;
}

/** Great-circle distance in miles (haversine). */
export function miles(a: LatLon, b: LatLon): number {
  const R = 3958.8;
  const rad = (d: number) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat);
  const dLon = rad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function milesText(m: number): string {
  return m < 10 ? `${m.toFixed(1)} mi` : `${Math.round(m)} mi`;
}
