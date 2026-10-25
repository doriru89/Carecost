import { useEffect, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
// maplibre-gl 6 builds its worker URL at runtime, which the bundler cannot see; bundle it here.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import type { UserLocation } from "../lib/geo";
import type { SiteView } from "../lib/sites";
import { stepOf, stepPin } from "../lib/steps";

/** OpenFreeMap: free vector tiles, no key (§4.3). */
export const MAP_STYLE = "https://tiles.openfreemap.org/styles/liberty";

maplibregl.setWorkerUrl(workerUrl);

/**
 * MapLibre map. Clicking a pin opens the same card's receipt. P3: a pin carries a price only for one
 * selected step (`step`, a StepSummary key): that step's own or estimated figure at that site. With no
 * step selected the map shows places only. With a step, a site that does not say it offers the step
 * (availability unknown or not offered) gets no pin (P6); lib/steps.ts stepPin.
 * The person's own location (if given) is drawn locally and never sent anywhere.
 */
export function SiteMap({
  views,
  selectedId,
  onOpen,
  location,
  step,
}: {
  views: SiteView[];
  selectedId: string | null;
  onOpen: (siteId: string) => void;
  location: UserLocation | null;
  /** P3: the one step whose price the pins show; null = places only */
  step: string | null;
}) {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);
  const onOpenRef = useRef(onOpen);
  onOpenRef.current = onOpen;

  useEffect(() => {
    if (!el.current) return;
    const m = new maplibregl.Map({
      container: el.current,
      style: MAP_STYLE,
      center: [-71.09, 42.36],
      zoom: 10.5,
      attributionControl: { compact: true },
    });
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.current = m;
    // the phone tabs keep this pane mounted but hidden; redraw at the right size when it shows again
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => m.resize()) : null;
    ro?.observe(el.current);
    return () => {
      ro?.disconnect();
      m.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const m = map.current;
    if (!m) return;
    markers.current.forEach((mk) => mk.remove());
    markers.current = [];
    const bounds = new maplibregl.LngLatBounds();
    for (const v of views) {
      const { site } = v.sq;
      const sp = step ? stepPin(stepOf(v.sq, step)) : null;
      if (step && !sp) continue; // P6: no pin where the site does not say it offers this step
      const pin = document.createElement("button");
      pin.type = "button";
      pin.dataset.testid = "map-pin";
      pin.dataset.priced = sp?.kind === "price" ? "true" : "false";
      pin.title = site.name;
      const on = site.site_id === selectedId ? "bg-ink text-white" : "bg-white text-ink";
      if (sp?.kind === "price") {
        pin.setAttribute("aria-label", `${site.name}: ${sp.text}${sp.estimated ? " (estimate)" : ""}`);
        pin.className =
          "rounded-full border-2 px-2 py-0.5 text-xs font-bold shadow-md tabular-nums " +
          (sp.estimated ? "border-dashed border-amber-500 " : "border-white ") +
          on;
        pin.textContent = `${sp.estimated ? "~" : ""}${sp.text}`;
      } else if (sp?.kind === "no_price") {
        // offered, but no dollar figure here: never a cheap-looking pin
        pin.setAttribute("aria-label", `${site.name}: ${sp.unusual ? "price looks unusual, being checked" : "no price"}`);
        pin.className = "rounded-full border-2 border-white px-2 py-0.5 text-xs font-bold shadow-md text-muted-foreground " + on;
        pin.textContent = sp.unusual ? "?" : "—";
      } else {
        // a place, not a price
        pin.setAttribute("aria-label", site.name);
        pin.className = "h-4 w-4 rounded-full border-2 border-ink shadow-md " + on;
      }
      pin.addEventListener("click", (e) => {
        e.stopPropagation();
        onOpenRef.current(site.site_id);
      });
      markers.current.push(new maplibregl.Marker({ element: pin }).setLngLat([site.coords.lon, site.coords.lat]).addTo(m));
      bounds.extend([site.coords.lon, site.coords.lat]);
    }
    if (location) {
      const me = document.createElement("div");
      me.className = "h-3.5 w-3.5 rounded-full border-2 border-white bg-sky-600 shadow";
      me.title = location.label;
      markers.current.push(new maplibregl.Marker({ element: me }).setLngLat([location.lon, location.lat]).addTo(m));
      bounds.extend([location.lon, location.lat]);
    }
    if (!bounds.isEmpty()) m.fitBounds(bounds, { padding: 60, maxZoom: 13, duration: 0 });
  }, [views, selectedId, location, step]);

  return <div ref={el} className="h-[420px] md:h-[calc(100vh-15rem)] min-h-[320px] w-full rounded-xl overflow-hidden border border-border" data-testid="site-map" />;
}
