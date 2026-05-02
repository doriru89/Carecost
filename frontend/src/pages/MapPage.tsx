import { useState, useMemo, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import Navbar from '@/components/layout/Navbar';
import Footer from '@/components/layout/Footer';
import ProviderCard from '@/components/providers/ProviderCard';
import CrtSelectionDialog, { EGD_PROCEDURES } from '@/components/CrtSelectionDialog';
import { DERM_PROCEDURES } from '@/lib/specialties/derm/dermDecisionTree';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip';
import { Search, List, MapPin, Building2, ChevronDown, ChevronRight, RefreshCw, Info, Sparkles, Stethoscope } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import InsuranceDialog from '@/components/InsuranceDialog';
import AiGuidanceDialog from '@/components/AiGuidanceDialog';
import type { Provider } from '@/types';
import { useAuth } from '@/context/AuthContext';
import { fetchProviders, fetchHospitals, postEstimate, type ProviderApi, type HospitalApi } from '@/api/client';
import { apiEstimateToCostEstimate } from '@/lib/mapEstimate';
import { getPayerPrice, computeYourPlanEstimate, carrierKeyFromLabel, getAllPriceSources } from '@/lib/payerPrice';
import { computeOop } from '@/lib/oopRules';
import { PLAN_CONFIGS, type PlanConfig } from '@/lib/hospitalRatesCsv';
import { buildEstimateFallback } from '@/lib/estimateFallback';
import { loadCrt, saveCrt, type SelectedCrt } from '@/lib/crtPersistence';
import { useLocation, useNavigate } from 'react-router-dom';

type MapRouteState = {
  openSymptoms?: boolean;
};

function toProvider(p: ProviderApi): Provider {
  return {
    id: p.id,
    name: p.name,
    specialty: p.specialties,
    address: `${p.address}, ${p.city}, MA ${p.zip}`,
    lat: p.lat,
    lng: p.lng,
    phone: p.phone,
    hospital: p.hospital,
  };
}

/** Airbnb-style: price pill + pin (CareCost pink). */
const createPricePinIcon = (priceLabel: string) => {
  const safe = priceLabel.replace(/[<>]/g, '');
  return L.divIcon({
    html: `<div style="display:flex;flex-direction:column;align-items:center;width:max-content;pointer-events:none;">
      <div style="background:#fff;border:1px solid hsl(345,40%,88%);border-radius:14px;padding:4px 10px;font-size:13px;font-weight:700;color:hsl(340,6%,17%);box-shadow:0 2px 10px rgba(0,0,0,0.1);white-space:nowrap;">${safe}</div>
      <div style="width:2px;height:5px;background:hsl(345,40%,85%);"></div>
      <div style="width:13px;height:13px;border-radius:50%;background:hsl(345,50%,77%);border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,0.18);"></div>
    </div>`,
    className: '',
    iconSize: [96, 56],
    iconAnchor: [48, 56],
  });
};

/** Payer key → human label for display. */
function payerDisplayLabel(carrier: string): string {
  const key = carrierKeyFromLabel(carrier);
  const labels: Record<string, string> = {
    bcbs: 'BCBS',
    aetna: 'Aetna',
    harvard_pilgrim: 'Harvard Pilgrim',
    uhc: 'UHC',
  };
  return labels[key] ?? 'BCBS';
}

const MapPage = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { intakePayload, insurance, user, profile } = useAuth();
  const insuranceCarrierLabel =
    (typeof intakePayload?.insurance_carrier === 'string' && intakePayload.insurance_carrier) ||
    insurance?.carrier ||
    'Your plan';

  // --- CRT selection state (persisted to sessionStorage, falls back to intakePayload for legacy flow) ---
  const [selectedCrt, setSelectedCrtRaw] = useState<SelectedCrt | null>(() => loadCrt(intakePayload));

  const setSelectedCrt = (val: SelectedCrt | null) => {
    setSelectedCrtRaw(val);
    saveCrt(val);
  };

  // --- Dialog + popover state ---
  const [insuranceDialogOpen, setInsuranceDialogOpen] = useState(false);
  const [aiDialogOpen, setAiDialogOpen] = useState(false);
  const [procPickerOpen, setProcPickerOpen] = useState(false);
  const [crtDialogOpen, setCrtDialogOpen] = useState(() => selectedCrt === null);

  // --- Filter / search state ---
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedProvider, setSelectedProvider] = useState<Provider | null>(null);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
  const [showList, setShowList] = useState(false);
  const [collapsedHospitals, setCollapsedHospitals] = useState<Set<string>>(new Set());
  const [expandedSources, setExpandedSources] = useState<Set<string>>(new Set());
  const [scrollToHospital, setScrollToHospital] = useState<string | null>(null);
  const hospitalRefsMap = useRef<Map<string, HTMLDivElement>>(new Map());

  const mapRef = useRef<L.Map | null>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const markersRef = useRef<L.LayerGroup | null>(null);

  const [selectedSpecialty, setSelectedSpecialty] = useState<string>(
    () => (intakePayload?.specialty as string) || (intakePayload?.care_focus as string) || 'Gastroenterology',
  );
  const [expandedSpecialty, setExpandedSpecialty] = useState<string | null>(
    () => (intakePayload?.specialty as string) || (intakePayload?.care_focus as string) || 'Gastroenterology',
  );

  // Derive plan config for rule-aware OOP calculation
  const activePlanConfig = useMemo<PlanConfig | undefined>(() => {
    const planName = insurance?.planName;
    if (planName) {
      const match = PLAN_CONFIGS.find(p => p.planName === planName);
      if (match) return match;
    }
    // Fallback: build from insurance profile
    if (insurance?.deductible != null && insurance?.coinsurance != null) {
      const carrierKey = carrierKeyFromLabel(insuranceCarrierLabel);
      return {
        id: 'user_custom',
        payer: insuranceCarrierLabel,
        carrierKey,
        planName: insurance.planName ?? 'Custom',
        planType: (insurance.planType as 'PPO' | 'HMO') ?? 'PPO',
        deductible: Number(insurance.deductible),
        oopMax: Number(insurance.oopMax ?? 0),
        coinsurancePct: Number(insurance.coinsurance),
        copaySpecialist: Number(insurance.copay ?? 50),
      };
    }
    return undefined;
  }, [insurance, insuranceCarrierLabel]);

  const providersQuery = useQuery({
    queryKey: ['providers', selectedSpecialty],
    queryFn: () => fetchProviders({ specialty: selectedSpecialty }),
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
  });

  const hospitalsQuery = useQuery({
    queryKey: ['hospitals', selectedCrt?.cpt, selectedSpecialty],
    queryFn: () => fetchHospitals(selectedCrt!.cpt, selectedSpecialty),
    enabled: selectedCrt !== null,
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always' as const,
  });

  const hospitals = useMemo(() => hospitalsQuery.data ?? [], [hospitalsQuery.data]);

  const providers = useMemo(
    () => (providersQuery.data ?? []).map(toProvider),
    [providersQuery.data],
  );

  const estimateQuery = useQuery({
    queryKey: ['estimate', intakePayload, insurance?.carrier, selectedCrt?.bundleId],
    queryFn: () => {
      const intake = buildEstimateFallback(profile, insurance, intakePayload, selectedSpecialty, selectedCrt);
      const bundle_id = selectedCrt?.bundleId ?? (typeof intake.bundle_id === 'string' && intake.bundle_id ? intake.bundle_id : '');
      const scenario_id = typeof intake.scenario_id === 'string' && intake.scenario_id ? intake.scenario_id : bundle_id;
      return postEstimate({ intake, bundle_id, scenario_id });
    },
    enabled: selectedCrt !== null && insurance != null,
  });

  const estimatesLackRates = useMemo(() => {
    if (hospitals.some(h => h.payer_rates.length > 0 || h.discounted_cash != null)) return false;
    const rows = estimateQuery.data?.estimates ?? [];
    if (rows.length === 0 || estimateQuery.isError) return false;
    return !rows.some(r => r.allowed_amount_range.max > 0 || r.oop_range.max > 0);
  }, [estimateQuery.data, estimateQuery.isError, hospitals]);

  const estimateById = useMemo(() => {
    const m = new Map<string, ReturnType<typeof apiEstimateToCostEstimate>>();
    for (const e of estimateQuery.data?.estimates ?? []) {
      const row = apiEstimateToCostEstimate(e);
      m.set(row.providerId, row);
    }
    return m;
  }, [estimateQuery.data]);

  const filtered = useMemo(() => {
    return providers.filter(p => {
      const matchSearch = !searchQuery || p.name.toLowerCase().includes(searchQuery.toLowerCase());
      return matchSearch;
    });
  }, [providers, searchQuery]);

  const groupedByHospital = useMemo(() => {
    const groups = new Map<string, Provider[]>();
    for (const p of filtered) {
      const key = p.hospital || 'Other';
      const list = groups.get(key) ?? [];
      list.push(p);
      groups.set(key, list);
    }
    const hospitalGroups: [string, Provider[]][] = [];
    const independentProviders: Provider[] = [];
    for (const [name, provs] of groups) {
      if (hospitals.some(h => h.name === name)) {
        hospitalGroups.push([name, provs]);
      } else {
        independentProviders.push(...provs);
      }
    }
    hospitalGroups.sort((a, b) => b[1].length - a[1].length);
    if (independentProviders.length > 0) {
      hospitalGroups.push(['Independent Providers', independentProviders]);
    }
    return hospitalGroups;
  }, [filtered, hospitals]);

  // Collapse all hospitals by default, then auto-expand the cheapest one
  useEffect(() => {
    if (hospitals.length === 0) return;
    const all = new Set(hospitals.map(h => h.name));
    all.add('Independent Providers');

    const priceFor = (h: HospitalApi) => getPayerPrice(h, insuranceCarrierLabel) ?? h.discounted_cash;
    const cheapest = [...hospitals]
      .filter(h => priceFor(h) != null)
      .sort((a, b) => (priceFor(a) ?? Infinity) - (priceFor(b) ?? Infinity))[0];

    if (cheapest) {
      all.delete(cheapest.name);
      setExpandedSources(new Set([cheapest.name]));
      setScrollToHospital(cheapest.name);
    }
    setCollapsedHospitals(all);
  }, [hospitals, insuranceCarrierLabel]);

  // Scroll to hospital after pin click — wait for expand animation, then scroll header to top
  useEffect(() => {
    if (!scrollToHospital) return;
    // Double rAF ensures DOM has settled after collapse state change
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const el = hospitalRefsMap.current.get(scrollToHospital);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
        setScrollToHospital(null);
      });
    });
  }, [scrollToHospital, collapsedHospitals]);

  const hasFullPlanData = insurance?.deductible != null && insurance?.coinsurance != null;

  const toggleHospital = (name: string) => {
    setCollapsedHospitals(s => {
      const next = new Set(s);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  };

  useEffect(() => {
    const routeState = (location.state ?? null) as MapRouteState | null;
    if (!routeState?.openSymptoms) return;
    setAiDialogOpen(true);
    navigate(`${location.pathname}${location.search}`, {
      replace: true,
      state: { ...routeState, openSymptoms: false },
    });
  }, [location.pathname, location.search, location.state, navigate]);

  useEffect(() => {
    if (!mapContainerRef.current) return;
    const container = mapContainerRef.current;

    const ro = new ResizeObserver(() => {
      if (mapRef.current || container.clientHeight < 100 || container.clientWidth < 100) return;
      const map = L.map(container, { zoomAnimation: false, fadeAnimation: false })
        .setView([39.8, -98.5], 4);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/">OSM</a>',
      }).addTo(map);
      markersRef.current = L.layerGroup().addTo(map);
      mapRef.current = map;
    });
    ro.observe(container);

    return () => {
      ro.disconnect();
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!mapRef.current || hospitals.length === 0) return;
    const valid = hospitals.filter(h => h.lat != null && h.lng != null && h.lat !== 0 && h.lng !== 0);
    if (valid.length === 0) { mapRef.current.setView([39.8, -98.5], 4); return; }
    const avgLat = valid.reduce((s, h) => s + h.lat, 0) / valid.length;
    const avgLng = valid.reduce((s, h) => s + h.lng, 0) / valid.length;
    mapRef.current.setView([avgLat, avgLng], 13);
  }, [hospitals]);

  // Payer-aware map markers
  useEffect(() => {
    if (!markersRef.current || !mapRef.current) return;
    markersRef.current.clearLayers();

    const payerLabel = payerDisplayLabel(insuranceCarrierLabel);

    hospitals.forEach(h => {
      const payerPrice = getPayerPrice(h, insuranceCarrierLabel);
      const priceLabel = payerPrice != null ? `$${Math.round(payerPrice).toLocaleString()}` : '—';
      const icon = createPricePinIcon(priceLabel);

      const rangeText = h.de_identified_min != null && h.de_identified_max != null
        ? `<br/><span style="font-size:11px;color:#666;">Range: $${Math.round(h.de_identified_min).toLocaleString()} – $${Math.round(h.de_identified_max).toLocaleString()}</span>`
        : '<br/><span style="font-size:11px;color:#999;font-style:italic;">Price range was not disclosed</span>';

      const marker = L.marker([h.lat, h.lng], { icon })
        .bindPopup(
          `<strong>${h.name}</strong><br/>` +
          `<span style="font-size:12px">${h.doctor_count} ${selectedSpecialty === 'Dermatology' ? 'dermatologists' : 'GI doctors'}</span>` +
          (payerPrice != null ? `<br/><span style="font-size:12px;font-weight:600;color:hsl(345,42%,45%);">${payerLabel}: ${priceLabel}</span>` : '') +
          rangeText,
        )
        .on('click', () => {
          // Collapse all (including Independent Providers), expand only this one, scroll to it
          setCollapsedHospitals(() => {
            const allCollapsed = new Set(hospitals.map(x => x.name));
            allCollapsed.add('Independent Providers');
            allCollapsed.delete(h.name);
            return allCollapsed;
          });
          setSelectedProvider(null);
          setScrollToHospital(h.name);
        });
      markersRef.current!.addLayer(marker);
    });
  }, [hospitals, insuranceCarrierLabel]);

  const toggleSave = (id: string) => {
    setSavedIds(s => {
      const next = new Set(s);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const loadError = providersQuery.isError || estimateQuery.isError || hospitalsQuery.isError;
  const payerLabel = payerDisplayLabel(insuranceCarrierLabel);

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar />

      {/* GI procedure dialog — can auto-open first time and be reopened from header */}
      {selectedSpecialty === 'Gastroenterology' && (
        <CrtSelectionDialog
          open={crtDialogOpen}
          onOpenChange={setCrtDialogOpen}
          onSelect={(cpt, label, bundleId) => {
            setSelectedCrt({ cpt, label, bundleId });
            setCrtDialogOpen(false);
          }}
        />
      )}

      <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-hidden">
        <div className="flex-1 relative min-h-[400px] lg:min-h-0">
          <div ref={mapContainerRef} className="absolute inset-0 z-0" />

          <div className="absolute top-3 right-3 z-[1000] lg:hidden">
            <Button size="sm" variant="outline" className="bg-card shadow-card" onClick={() => setShowList(!showList)}>
              {showList ? (
                <>
                  <MapPin className="w-4 h-4 mr-1" /> Map
                </>
              ) : (
                <>
                  <List className="w-4 h-4 mr-1" /> List
                </>
              )}
            </Button>
          </div>
        </div>

        <div
          className={`lg:w-[420px] lg:h-[calc(100vh-4rem)] bg-card border-l border-border overflow-y-auto ${showList ? 'block' : 'hidden lg:block'}`}
        >
          <div className="p-4 border-b border-border space-y-3 sticky top-0 bg-card z-10">
            {loadError && (
              <p className="text-sm text-destructive">
                Could not load map data. Run the API on port 8000 and seed the database
                (see the repo README). The Vite dev server proxies <code className="text-xs">/api</code> to{' '}
                <code className="text-xs">127.0.0.1:8000</code>.
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              {selectedSpecialty === 'Gastroenterology' && (
                <>
                  <Button type="button" variant="outline" size="sm" onClick={() => setCrtDialogOpen(true)}>
                    {selectedCrt ? 'Change procedure' : 'Choose procedure'}
                  </Button>
                  <Button type="button" variant="outline" size="sm" onClick={() => setAiDialogOpen(true)}>
                    Symptom guidance
                  </Button>
                </>
              )}
            </div>
            {/* Calculate OOP CTA — shown at top when no insurance */}
            {!hasFullPlanData && (
              <button
                type="button"
                onClick={() => setInsuranceDialogOpen(true)}
                className="w-full text-left rounded-xl border border-primary/20 bg-primary/5 px-3 py-2 text-sm hover:bg-primary/10 transition-colors"
              >
                <p className="text-xs font-semibold uppercase tracking-wide text-primary">Calculate your out-of-pocket</p>
                <p className="text-xs text-muted-foreground mt-0.5">Add your insurance info to see personalized estimates</p>
              </button>
            )}
            {selectedCrt && (
              <div className="rounded-xl border border-primary/20 bg-primary/5 px-3 py-2 text-sm flex items-start justify-between gap-2">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-wide text-primary">Estimates for</p>
                  <p className="font-medium text-foreground leading-snug">{selectedCrt.label}</p>
                  <p className="text-xs text-muted-foreground mt-0.5 font-mono">CPT {selectedCrt.cpt}</p>
                </div>
                {selectedSpecialty === 'Gastroenterology' && (
                  <button
                    type="button"
                    onClick={() => setAiDialogOpen(true)}
                    className="shrink-0 flex items-center gap-1.5 rounded-full bg-primary/10 hover:bg-primary/20 px-3 py-1.5 transition-colors mt-1"
                  >
                    <Sparkles className="w-3.5 h-3.5 text-primary" />
                    <span className="text-xs font-medium text-primary whitespace-nowrap">Update symptom guidance</span>
                  </button>
                )}
              </div>
            )}
            {estimatesLackRates && (
              <p className="text-xs text-amber-800 dark:text-amber-200 bg-amber-50 dark:bg-amber-950/40 border border-amber-200/80 rounded-lg px-3 py-2">
                No hospital rates found in the database for this CPT/bundle — pins cannot show dollars. From the repo
                root run{' '}
                <code className="text-[11px] bg-background/80 px-1 rounded">python scripts/import_csv_to_postgres.py --az-mvp</code>{' '}
                then refresh.
              </p>
            )}
            {/* Single dropdown — specialty → procedure nested selector */}
            <Popover open={procPickerOpen} onOpenChange={setProcPickerOpen}>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className="w-full flex items-center gap-2 h-11 px-3 rounded-md border border-primary/20 bg-card text-sm font-medium hover:bg-muted/50 transition-colors"
                >
                  <Stethoscope className="w-4 h-4 text-primary shrink-0" />
                  <span className="flex-1 text-left truncate">
                    {selectedCrt ? `${selectedCrt.label} (CPT ${selectedCrt.cpt})` : 'Select procedure'}
                  </span>
                  <ChevronDown className="w-4 h-4 text-muted-foreground shrink-0" />
                </button>
              </PopoverTrigger>
              <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0 max-h-[360px] overflow-y-auto" align="start">
                {[
                  { id: 'Gastroenterology', label: 'Gastroenterology', procs: EGD_PROCEDURES.filter((p, i, arr) => arr.findIndex(x => x.cpt === p.cpt && x.bundleId === p.bundleId) === i) },
                  { id: 'Dermatology', label: 'Dermatology', procs: DERM_PROCEDURES },
                ].map(spec => {
                  const isOpen = expandedSpecialty === spec.id;
                  return (
                    <div key={spec.id}>
                      <button
                        type="button"
                        onClick={() => setExpandedSpecialty(isOpen ? null : spec.id)}
                        className="w-full flex items-center gap-2 px-3 py-2.5 text-sm font-semibold text-muted-foreground hover:bg-muted/50 transition-colors border-b border-border"
                      >
                        {isOpen ? <ChevronDown className="w-3.5 h-3.5 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 shrink-0" />}
                        {spec.label}
                      </button>
                      {isOpen && spec.procs.map(p => {
                        const isSelected = selectedSpecialty === spec.id && selectedCrt?.bundleId === p.bundleId && selectedCrt?.cpt === p.cpt;
                        return (
                          <button
                            key={p.bundleId}
                            type="button"
                            onClick={() => {
                              if (spec.id !== selectedSpecialty) {
                                setSelectedSpecialty(spec.id);
                                setExpandedSources(new Set());
                              }
                              setSelectedCrt({ cpt: p.cpt, label: p.label, bundleId: p.bundleId });
                              setProcPickerOpen(false);
                            }}
                            className={`w-full text-left pl-9 pr-3 py-2 text-sm transition-colors ${
                              isSelected
                                ? 'bg-primary/10 text-primary font-medium'
                                : 'text-foreground hover:bg-muted/50'
                            }`}
                          >
                            {p.label}
                            <span className="text-xs text-muted-foreground ml-1.5 font-mono">CPT {p.cpt}</span>
                          </button>
                        );
                      })}
                    </div>
                  );
                })}
              </PopoverContent>
            </Popover>
            <div className="flex items-center gap-2">
              <div className="relative flex-1 min-w-0">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="Search providers…"
                  value={searchQuery}
                  onChange={e => setSearchQuery(e.target.value)}
                  className="pl-9"
                />
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="shrink-0"
                disabled={providersQuery.isFetching}
                onClick={() => {
                  void providersQuery.refetch();
                  void estimateQuery.refetch();
                  void hospitalsQuery.refetch();
                }}
                title="Reload data from API"
              >
                <RefreshCw className={`w-4 h-4 ${providersQuery.isFetching ? 'animate-spin' : ''}`} />
              </Button>
            </div>
          </div>

          <div className="p-4 space-y-3">
            {selectedProvider ? (
              <div>
                <button type="button" onClick={() => setSelectedProvider(null)} className="text-sm text-primary hover:underline mb-3">
                  ← Back to list
                </button>
                <ProviderCard
                  provider={selectedProvider}
                  estimate={estimateById.get(String(selectedProvider.id))}
                  insuranceLabel={insuranceCarrierLabel}
                  hospitalPayerPrice={(() => {
                    const h = hospitals.find(x => x.name === selectedProvider.hospital);
                    return h ? getPayerPrice(h, insuranceCarrierLabel) : null;
                  })()}
                  hospital={hospitals.find(x => x.name === selectedProvider.hospital)}
                  planConfig={activePlanConfig}
                  scenarioId={selectedCrt?.bundleId ?? null}
                  cptCode={selectedCrt?.cpt ?? null}
                  deductible={insurance?.deductible}
                  coinsurancePct={insurance?.coinsurance}
                  onSave={() => toggleSave(selectedProvider.id)}
                  saved={savedIds.has(selectedProvider.id)}
                  onRequestInsurance={() => setInsuranceDialogOpen(true)}
                />
              </div>
            ) : groupedByHospital.length > 0 ? (
              groupedByHospital.map(([hospitalName, hospitalProviders]) => {
                const isCollapsed = collapsedHospitals.has(hospitalName);
                const hData = hospitals.find(h => h.name === hospitalName);
                const hospitalPayerPrice = hData ? getPayerPrice(hData, insuranceCarrierLabel) : null;
                const yourPlanEst = hospitalPayerPrice != null && hasFullPlanData
                  ? computeYourPlanEstimate(hospitalPayerPrice, insurance!.deductible, insurance!.coinsurance!)
                  : null;
                const hospitalOop = hospitalPayerPrice != null && activePlanConfig && selectedCrt?.bundleId
                  ? computeOop(hospitalPayerPrice, activePlanConfig, selectedCrt.bundleId, selectedCrt?.cpt ?? null)
                  : null;
                return (
                  <div
                    key={hospitalName}
                    className="mb-2"
                    ref={el => { if (el) hospitalRefsMap.current.set(hospitalName, el); else hospitalRefsMap.current.delete(hospitalName); }}
                  >
                    <button
                      type="button"
                      onClick={() => toggleHospital(hospitalName)}
                      className="w-full flex items-center gap-2 px-3 py-2.5 rounded-xl bg-muted/50 hover:bg-muted transition-colors text-left"
                    >
                      {isCollapsed ? <ChevronRight className="w-4 h-4 shrink-0" /> : <ChevronDown className="w-4 h-4 shrink-0" />}
                      <Building2 className="w-4 h-4 shrink-0 text-primary" />
                      <div className="flex-1 min-w-0">
                        <span className="font-semibold text-sm truncate block">{hospitalName}</span>
                        {hospitalPayerPrice != null ? (
                          <span className="text-xs text-muted-foreground">{payerLabel} ${Math.round(hospitalPayerPrice).toLocaleString()}</span>
                        ) : (
                          <span className="text-xs text-muted-foreground italic">{payerLabel} price not disclosed</span>
                        )}
                        {hospitalOop ? (
                          <span className="text-xs text-primary ml-2 inline-flex items-center gap-0.5">
                            {hospitalOop.ruleType === 'preventive' ? (
                              <>
                                $0 <span className="bg-green-50 text-green-700 px-1 rounded text-[10px]">ACA preventive</span>
                                <Tooltip>
                                  <TooltipTrigger asChild><Info className="w-3 h-3 inline" /></TooltipTrigger>
                                  <TooltipContent side="top" className="max-w-xs text-xs">
                                    <p>Insurer pays ${hospitalPayerPrice != null ? Math.round(hospitalPayerPrice).toLocaleString() : '—'} · You pay $0. Preventive screening colonoscopy is covered at 100% under ACA with no cost-sharing. If a polyp is found, the plan may reclassify as diagnostic.</p>
                                  </TooltipContent>
                                </Tooltip>
                              </>
                            ) : hospitalOop.ruleType === 'copay_only' ? (
                              <>Copay ${hospitalOop.estimate}</>
                            ) : (
                              <>You pay ${hospitalOop.estimate.toLocaleString()}</>
                            )}
                          </span>
                        ) : yourPlanEst != null ? (
                          <span className="text-xs text-primary ml-2">
                            You pay ${yourPlanEst.toLocaleString()}
                          </span>
                        ) : (
                          <span
                            role="button"
                            tabIndex={0}
                            onClick={(e) => { e.stopPropagation(); setInsuranceDialogOpen(true); }}
                            onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); setInsuranceDialogOpen(true); } }}
                            className="text-xs text-primary/70 ml-2 hover:text-primary hover:underline cursor-pointer"
                          >
                            You pay —
                          </span>
                        )}
                      </div>
                      <span className="text-xs text-muted-foreground">{hospitalProviders.length}</span>
                    </button>
                    {!isCollapsed && (
                      <div className="mt-2 space-y-3 pl-2">
                        {/* Price range with info tooltip */}
                        {hData?.de_identified_min != null && hData?.de_identified_max != null ? (
                          <div className="bg-primary/5 border border-primary/15 rounded-lg px-3 py-2 text-xs flex items-center gap-1">
                            <span className="font-semibold">Price range:</span>{' '}
                            ${Math.round(hData.de_identified_min).toLocaleString()} – ${Math.round(hData.de_identified_max).toLocaleString()}
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Info className="w-3.5 h-3.5 text-muted-foreground shrink-0 cursor-help" />
                              </TooltipTrigger>
                              <TooltipContent side="top" className="max-w-xs text-xs">
                                <p>De-identified minimum and maximum negotiated rate across all payers at this hospital, as required by federal price transparency rules.</p>
                              </TooltipContent>
                            </Tooltip>
                          </div>
                        ) : (
                          <div className="bg-muted/30 border border-border rounded-lg px-3 py-2 text-xs text-muted-foreground italic">
                            Price range was not disclosed by this facility
                          </div>
                        )}
                        {/* Collapsible price sources at hospital level */}
                        {hData && (() => {
                          const sources = getAllPriceSources(hData, insuranceCarrierLabel);
                          if (sources.length === 0) return null;
                          const isSourcesOpen = expandedSources.has(hospitalName);

                          const kindDescriptions = {
                            negotiated: '(insurer-hospital contract rate)',
                            tic: '(insurer-reported, Transparency in Coverage)',
                            cash: '(self-pay / uninsured discount)',
                            de_identified: '(anonymized range across all payers)',
                            gross: '(hospital list price before discounts)',
                            benchmark: '(independent industry estimate)',
                          };

                          const sortedSources = [...sources].sort((a, b) => {
                            const aIsFairHealth = a.label.includes('FAIR Health');
                            const bIsFairHealth = b.label.includes('FAIR Health');
                            if (aIsFairHealth && !bIsFairHealth) return 1;
                            if (!aIsFairHealth && bIsFairHealth) return -1;
                            return a.price - b.price;
                          });

                          const userCarrierKey = carrierKeyFromLabel(insuranceCarrierLabel);
                          const carrierLabels: Record<string, string[]> = {
                            bcbs: ['bcbs', 'blue cross'],
                            aetna: ['aetna'],
                            harvard_pilgrim: ['harvard pilgrim', 'harvard'],
                            uhc: ['uhc', 'united'],
                          };
                          const matchTokens = carrierLabels[userCarrierKey] ?? [];

                          return (
                            <div className="bg-muted/30 rounded-lg px-3 py-2 text-xs">
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setExpandedSources(prev => {
                                    const next = new Set(prev);
                                    if (next.has(hospitalName)) next.delete(hospitalName);
                                    else next.add(hospitalName);
                                    return next;
                                  });
                                }}
                                className="flex items-center gap-1 font-semibold text-muted-foreground uppercase tracking-wider text-[10px] hover:text-foreground transition-colors w-full"
                              >
                                {isSourcesOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                                All {sources.length} data sources
                              </button>
                              {isSourcesOpen && (
                                <div className="mt-1 space-y-0.5 max-h-[200px] overflow-y-auto">
                                  {sortedSources.map((src, i) => {
                                    const srcLower = src.label.toLowerCase();
                                    const isUserInsurer = src.kind === 'negotiated' && matchTokens.some(t => srcLower.includes(t));
                                    const isCash = src.kind === 'cash';

                                    return (
                                      <div
                                        key={i}
                                        className={`flex flex-col gap-0.5 px-2 py-1.5 rounded ${
                                          isUserInsurer
                                            ? 'bg-primary/10 border-l-2 border-primary'
                                            : isCash
                                            ? 'bg-green-50 dark:bg-green-950/30'
                                            : ''
                                        }`}
                                      >
                                        <div className="flex justify-between items-baseline">
                                          <span className="text-muted-foreground">{src.label}</span>
                                          <span className="font-medium">${Math.round(src.price).toLocaleString()}</span>
                                        </div>
                                        <span className="text-[10px] text-muted-foreground/70">
                                          {kindDescriptions[src.kind]}
                                        </span>
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </div>
                          );
                        })()}
                        {hData && (
                          <div className="bg-muted/30 rounded-lg px-3 py-2 text-xs">
                            <p className="font-semibold text-muted-foreground uppercase tracking-wider text-[10px] mb-1.5">All insurers</p>
                            <div className="flex overflow-x-auto gap-1.5 text-center">
                              {(() => {
                                const PAYER_LABELS: Record<string, string> = {
                                  bcbs: 'BCBS', aetna: 'Aetna', harvard_pilgrim: 'Harvard Pilgrim', uhc: 'UHC',
                                };
                                const ratesByPayer = new Map<string, number | null>();
                                for (const r of hData.payer_rates) {
                                  if (!ratesByPayer.has(r.payer_id) || r.source_origin === 'mrf') {
                                    ratesByPayer.set(r.payer_id, r.negotiated_rate);
                                  }
                                }
                                const entries = [...ratesByPayer.entries()].map(([key, price]) => ({
                                  key, label: PAYER_LABELS[key] ?? key.toUpperCase(), price,
                                }));
                                const prices = entries.map(e => e.price).filter((p): p is number => p != null);
                                const lowest = prices.length > 0 ? Math.min(...prices) : null;
                                return entries.map(({ label, price, key }) => {
                                  const isActive = carrierKeyFromLabel(insuranceCarrierLabel) === key;
                                  const isCheapest = price != null && price === lowest;
                                  return (
                                    <div key={key} className={`rounded-md px-1 py-1.5 min-w-[4rem] ${isActive ? 'bg-primary/10 ring-1 ring-primary/30' : ''}`}>
                                      <p className="text-[10px] text-muted-foreground truncate">{label}</p>
                                      <p className={`font-semibold ${isCheapest ? 'text-green-700' : ''}`}>{price != null ? `$${Math.round(price).toLocaleString()}` : 'N/A'}</p>
                                    </div>
                                  );
                                });
                              })()}
                            </div>
                          </div>
                        )}
                        {hospitalProviders.map(p => (
                          <div key={p.id} onClick={() => setSelectedProvider(p)} className="cursor-pointer">
                            <ProviderCard
                              provider={p}
                              estimate={estimateById.get(String(p.id))}
                              insuranceLabel={insuranceCarrierLabel}
                              hospitalPayerPrice={hospitalPayerPrice}
                              deductible={insurance?.deductible}
                              coinsurancePct={insurance?.coinsurance}
                              onSave={() => toggleSave(p.id)}
                              saved={savedIds.has(p.id)}
                              onRequestInsurance={() => setInsuranceDialogOpen(true)}
                              compact
                            />
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })
            ) : (
              <div className="text-center py-12">
                <MapPin className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
                <p className="font-medium">No providers found</p>
                <p className="text-sm text-muted-foreground mt-1">Try another specialty or widen your search.</p>
              </div>
            )}
          </div>
        </div>
      </div>

      <Footer />

      <InsuranceDialog open={insuranceDialogOpen} onOpenChange={setInsuranceDialogOpen} />
      <AiGuidanceDialog
        open={aiDialogOpen}
        onOpenChange={setAiDialogOpen}
        onProcedureSelect={(cpt, label, bundleId) => setSelectedCrt({ cpt, label, bundleId })}
      />
    </div>
  );
};

export default MapPage;
