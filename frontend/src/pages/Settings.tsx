import { useEffect, useMemo, useState } from 'react';
import Navbar from '@/components/layout/Navbar';
import Footer from '@/components/layout/Footer';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useAuth } from '@/context/AuthContext';
import type { InsuranceProfile, UserProfile } from '@/types';
import { toast } from 'sonner';
import {
  fetchInsuranceOptions,
  insuranceProfileToApi,
  patchUserMe,
  userProfileToApi,
  type InsurerOptionApi,
} from '@/api/client';
import { maskUsDateDigits, parseUsDateToIso, isoToUsDisplay } from '@/lib/usDate';

const FALLBACK_INSURERS: InsurerOptionApi[] = [
  { key: 'bcbs', label: 'Blue Cross Blue Shield (BCBS)', price_column: 'bcbs_price' },
  { key: 'aetna', label: 'Aetna', price_column: 'aetna_price' },
  { key: 'harvard_pilgrim', label: 'Harvard Pilgrim', price_column: 'harvard_pilgrim_price' },
  { key: 'uhc', label: 'UnitedHealthcare (UHC)', price_column: 'uhc_price' },
];

const GENERIC_PLAN_FALLBACK = [
  'Commercial PPO',
  'Commercial HMO',
  'Medicare Advantage',
  'Other — see insurance card',
];

const BCBS_PLAN_FALLBACK = ['Plan name not listed in hospital data file'];

const Settings = () => {
  const { profile, insurance, setProfile, setInsurance } = useAuth();
  const [name, setName] = useState(profile?.fullName || '');
  const [zip, setZip] = useState(profile?.zip || '');
  const [phone, setPhone] = useState(profile?.phone || '');
  const [dobDisplay, setDobDisplay] = useState(isoToUsDisplay(profile?.dob));
  const [dobError, setDobError] = useState<string | null>(null);
  const [carrier, setCarrier] = useState(insurance?.carrier || '');
  const [planName, setPlanName] = useState(insurance?.planName || '');
  const [memberId, setMemberId] = useState(insurance?.memberId || '');
  const [planType, setPlanType] = useState<InsuranceProfile['planType']>(insurance?.planType || 'PPO');
  const [deductible, setDeductible] = useState(insurance?.deductible ?? 0);
  const [oopMax, setOopMax] = useState(insurance?.oopMax ?? 0);
  const [copay, setCopay] = useState(insurance?.copay ?? 0);
  const [coinsurance, setCoinsurance] = useState(insurance?.coinsurance ?? 0);

  const [insurers, setInsurers] = useState<InsurerOptionApi[]>(FALLBACK_INSURERS);
  const [planOptionsByInsurer, setPlanOptionsByInsurer] = useState<Record<string, string[]>>({});
  const [coverageLoading, setCoverageLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await fetchInsuranceOptions();
        if (cancelled) return;
        setInsurers(data.insurers.length > 0 ? data.insurers : FALLBACK_INSURERS);
        const byIns: Record<string, string[]> = { ...(data.plan_options_by_insurer ?? {}) };
        if ((byIns.bcbs?.length ?? 0) === 0 && data.bcbs_plan_options?.length) {
          byIns.bcbs = data.bcbs_plan_options;
        }
        setPlanOptionsByInsurer(byIns);
      } catch {
        if (!cancelled) {
          setInsurers(FALLBACK_INSURERS);
          setPlanOptionsByInsurer({});
        }
      } finally {
        if (!cancelled) setCoverageLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (coverageLoading) return;
    setName(profile?.fullName || '');
    setZip(profile?.zip || '');
    setPhone(profile?.phone || '');
    setDobDisplay(isoToUsDisplay(profile?.dob));
    setCarrier(insurance?.carrier || '');
    setPlanName(insurance?.planName || '');
    setMemberId(insurance?.memberId || '');
    setPlanType(insurance?.planType || 'PPO');
    setDeductible(insurance?.deductible ?? 0);
    setOopMax(insurance?.oopMax ?? 0);
    setCopay(insurance?.copay ?? 0);
    setCoinsurance(insurance?.coinsurance ?? 0);
  }, [profile, insurance, coverageLoading]);

  const selectedInsurerKey = useMemo(
    () => insurers.find(i => i.label === carrier)?.key ?? '',
    [carrier, insurers],
  );

  const planChoices = useMemo(() => {
    const key = selectedInsurerKey;
    if (!key) return [];
    const fromData = planOptionsByInsurer[key] ?? [];
    if (fromData.length > 0) return fromData;
    if (key === 'bcbs') return BCBS_PLAN_FALLBACK;
    return GENERIC_PLAN_FALLBACK;
  }, [selectedInsurerKey, planOptionsByInsurer]);

  const save = async () => {
    const iso = parseUsDateToIso(dobDisplay);
    if (!iso) {
      setDobError('Enter a valid date of birth as MM/DD/YYYY.');
      toast.error('Check date of birth');
      return;
    }
    setDobError(null);
    const nextProfile: UserProfile = {
      fullName: name,
      dob: iso,
      zip,
      phone,
      onboardingCompleted: profile?.onboardingCompleted,
    };
    const nextInsurance: InsuranceProfile = {
      carrier,
      planName,
      memberId,
      planType,
      deductible,
      oopMax,
      copay,
      coinsurance,
    };
    setProfile(nextProfile);
    setInsurance(nextInsurance);
    try {
      await patchUserMe({
        user_profile: userProfileToApi(nextProfile),
        insurance_profile: insuranceProfileToApi(nextInsurance),
      });
    } catch {
      toast.error('Could not sync profile to the server');
      return;
    }
    toast.success('Profile updated');
  };

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar />
      <div className="flex-1 container mx-auto px-4 py-10 max-w-lg animate-fade-in">
        <h1 className="text-2xl font-bold mb-8">Settings</h1>

        <section className="mb-8">
          <h2 className="text-lg font-semibold mb-4">Personal info</h2>
          <div className="space-y-3">
            <div>
              <Label>Full name</Label>
              <Input value={name} onChange={e => setName(e.target.value)} className="mt-1" />
            </div>
            <div>
              <Label htmlFor="settings-dob">Date of birth</Label>
              <Input
                id="settings-dob"
                type="text"
                inputMode="numeric"
                autoComplete="bday"
                placeholder="MM/DD/YYYY"
                value={dobDisplay}
                onChange={e => {
                  setDobDisplay(maskUsDateDigits(e.target.value));
                  setDobError(null);
                }}
                className="mt-1"
                maxLength={10}
              />
              {dobError && <p className="text-xs text-destructive mt-1">{dobError}</p>}
            </div>
            <div>
              <Label>ZIP code</Label>
              <Input value={zip} onChange={e => setZip(e.target.value)} className="mt-1" />
            </div>
            <div>
              <Label>Phone</Label>
              <Input value={phone} onChange={e => setPhone(e.target.value)} className="mt-1" />
            </div>
          </div>
        </section>

        <section className="mb-8">
          <h2 className="text-lg font-semibold mb-4">Insurance</h2>
          {coverageLoading && <p className="text-sm text-muted-foreground mb-2">Loading insurance options…</p>}
          <div className="space-y-3">
            <div>
              <Label>Insurance carrier</Label>
              <Select
                value={selectedInsurerKey || undefined}
                onValueChange={key => {
                  const opt = insurers.find(o => o.key === key);
                  if (!opt) return;
                  setCarrier(opt.label);
                  setPlanName('');
                }}
                disabled={coverageLoading}
              >
                <SelectTrigger className="mt-1">
                  <SelectValue placeholder="Select your insurer" />
                </SelectTrigger>
                <SelectContent>
                  {insurers.map(opt => (
                    <SelectItem key={opt.key} value={opt.key}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Plan name</Label>
              <Select
                value={planName || undefined}
                onValueChange={setPlanName}
                disabled={!carrier || planChoices.length === 0 || coverageLoading}
              >
                <SelectTrigger className="mt-1">
                  <SelectValue placeholder="Select your plan" />
                </SelectTrigger>
                <SelectContent>
                  {planChoices.map(plan => (
                    <SelectItem key={plan} value={plan}>
                      {plan}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Member ID</Label>
              <Input value={memberId} onChange={e => setMemberId(e.target.value)} className="mt-1" />
            </div>
            <div>
              <Label>Plan type</Label>
              <Select value={planType} onValueChange={v => setPlanType(v as InsuranceProfile['planType'])}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {['PPO', 'HMO', 'EPO', 'Other'].map(t => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Deductible ($)</Label>
                <Input type="number" value={deductible} onChange={e => setDeductible(Number(e.target.value))} className="mt-1" />
              </div>
              <div>
                <Label>OOP max ($)</Label>
                <Input type="number" value={oopMax} onChange={e => setOopMax(Number(e.target.value))} className="mt-1" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Copay ($)</Label>
                <Input type="number" value={copay || ''} onChange={e => setCopay(Number(e.target.value))} className="mt-1" />
              </div>
              <div>
                <Label>Coinsurance (%)</Label>
                <Input
                  type="number"
                  min={0}
                  max={100}
                  value={coinsurance}
                  onChange={e => setCoinsurance(Number(e.target.value))}
                  className="mt-1"
                />
              </div>
            </div>
          </div>
        </section>

        <Button className="w-full bg-primary text-primary-foreground hover:bg-primary-hover h-11" onClick={save}>
          Save changes
        </Button>
      </div>
      <Footer />
    </div>
  );
};

export default Settings;
