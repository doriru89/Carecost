import { useEffect, useMemo, useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import Stepper from '@/components/Stepper';
import { useAuth } from '@/context/AuthContext';
import type { InsuranceProfile, UserProfile } from '@/types';
import {
  fetchInsuranceOptions,
  insuranceProfileToApi,
  patchUserMe,
  userProfileToApi,
  type InsurerOptionApi,
} from '@/api/client';
import { isUserProfileComplete } from '@/lib/profileComplete';
import { maskUsDateDigits, parseUsDateToIso, isoToUsDisplay } from '@/lib/usDate';
import { PLAN_CONFIGS } from '@/lib/hospitalRatesCsv';
import { toast } from 'sonner';

import { FALLBACK_INSURERS } from '@/lib/constants';

const STEPS = ['About you', 'Coverage'];

const GENERIC_PLAN_FALLBACK = ['Commercial PPO', 'Commercial HMO', 'Medicare Advantage', 'Other — see insurance card'];
const BCBS_PLAN_FALLBACK = ['Plan name not listed in hospital data file'];

interface InsuranceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const InsuranceDialog = ({ open, onOpenChange }: InsuranceDialogProps) => {
  const { profile: authProfile, insurance: authInsurance, setProfile, setInsurance } = useAuth();

  const startStep = authProfile && isUserProfileComplete(authProfile) ? 1 : 0;
  const [step, setStep] = useState(startStep);

  const [name, setName] = useState(authProfile?.fullName || '');
  const [zip, setZip] = useState(authProfile?.zip || '');
  const [phone, setPhone] = useState(authProfile?.phone || '');
  const [dobDisplay, setDobDisplay] = useState(isoToUsDisplay(authProfile?.dob));
  const [dobError, setDobError] = useState<string | null>(null);

  const [carrier, setCarrier] = useState(authInsurance?.carrier || '');
  const [planName, setPlanName] = useState(authInsurance?.planName || '');
  const [memberId, setMemberId] = useState(authInsurance?.memberId || '');
  const [planType, setPlanType] = useState<InsuranceProfile['planType']>(authInsurance?.planType || 'PPO');
  const [deductible, setDeductible] = useState(authInsurance?.deductible ?? 0);
  const [oopMax, setOopMax] = useState(authInsurance?.oopMax ?? 0);
  const [copay, setCopay] = useState(authInsurance?.copay ?? 0);
  const [coinsurance, setCoinsurance] = useState(authInsurance?.coinsurance ?? 0);

  const [insurers, setInsurers] = useState<InsurerOptionApi[]>(FALLBACK_INSURERS);
  const [planOptionsByInsurer, setPlanOptionsByInsurer] = useState<Record<string, string[]>>({});
  const [coverageLoading, setCoverageLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
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
    return () => { cancelled = true; };
  }, [open]);

  useEffect(() => {
    if (!carrier) return;
    const key = insurers.find(i => i.label === carrier)?.key ?? '';
    if (!key || !planName) return;
    const match = PLAN_CONFIGS.find(p => p.carrierKey === key && p.planName === planName);
    if (match) {
      setDeductible(prev => prev || match.deductible);
      setOopMax(prev => prev || match.oopMax);
      setCoinsurance(prev => prev ?? match.coinsurancePct);
    }
  }, [planName, carrier, insurers]);

  const selectedInsurerKey = useMemo(
    () => insurers.find(i => i.label === carrier)?.key ?? '',
    [carrier, insurers],
  );

  const planChoices = useMemo(() => {
    if (!selectedInsurerKey) return [];
    const fromData = planOptionsByInsurer[selectedInsurerKey] ?? [];
    if (fromData.length > 0) return fromData;
    if (selectedInsurerKey === 'bcbs') return BCBS_PLAN_FALLBACK;
    return GENERIC_PLAN_FALLBACK;
  }, [selectedInsurerKey, planOptionsByInsurer]);

  const goNextFromAbout = () => {
    const iso = parseUsDateToIso(dobDisplay);
    if (!iso) {
      setDobError('Enter a valid date of birth as MM/DD/YYYY.');
      return;
    }
    setDobError(null);
    setStep(1);
  };

  const save = async () => {
    const iso = parseUsDateToIso(dobDisplay) || authProfile?.dob;
    const nextProfile: UserProfile = {
      fullName: name || authProfile?.fullName || '',
      dob: iso,
      zip: zip || authProfile?.zip || '',
      phone: phone || authProfile?.phone,
      onboardingCompleted: authProfile?.onboardingCompleted,
    };
    const nextInsurance: InsuranceProfile = {
      carrier, planName, memberId, planType,
      deductible, oopMax, copay, coinsurance,
    };
    setProfile(nextProfile);
    setInsurance(nextInsurance);
    setSaving(true);
    try {
      await patchUserMe({
        user_profile: userProfileToApi(nextProfile),
        insurance_profile: insuranceProfileToApi(nextInsurance),
      });
      toast.success('Insurance info saved');
      onOpenChange(false);
    } catch {
      toast.error('Could not save to server — your data is saved locally');
    } finally {
      setSaving(false);
    }
  };

  const canSaveCoverage =
    !!carrier && !!planName &&
    coinsurance != null && !Number.isNaN(Number(coinsurance)) &&
    coinsurance >= 0 && coinsurance <= 100;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-xl">
            {step === 0 ? 'About you' : 'Your coverage'}
          </DialogTitle>
          <DialogDescription>
            {step === 0
              ? 'Tell us a bit about yourself so we can personalize your estimates.'
              : 'Enter your insurance details to see your out-of-pocket costs.'}
          </DialogDescription>
        </DialogHeader>

        <Stepper steps={STEPS} currentStep={step} />

        {step === 0 && (
          <div className="space-y-4 mt-2">
            <div>
              <Label>Full name</Label>
              <Input value={name} onChange={e => setName(e.target.value)} className="mt-1" />
            </div>
            <div>
              <Label htmlFor="ins-dob">Date of birth</Label>
              <Input
                id="ins-dob"
                type="text"
                inputMode="numeric"
                placeholder="MM/DD/YYYY"
                value={dobDisplay}
                onChange={e => { setDobDisplay(maskUsDateDigits(e.target.value)); setDobError(null); }}
                className="mt-1"
                maxLength={10}
              />
              {dobError && <p className="text-xs text-destructive mt-1">{dobError}</p>}
            </div>
            <div>
              <Label>ZIP code</Label>
              <Input value={zip} onChange={e => setZip(e.target.value)} placeholder="02101" className="mt-1" />
            </div>
            <div>
              <Label>Phone <span className="text-muted-foreground font-normal">(optional)</span></Label>
              <Input value={phone} onChange={e => setPhone(e.target.value)} className="mt-1" />
            </div>
            <Button
              className="w-full bg-primary text-primary-foreground hover:bg-primary-hover h-11"
              onClick={goNextFromAbout}
              disabled={!name || !zip || !parseUsDateToIso(dobDisplay)}
            >
              Continue
            </Button>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4 mt-2">
            {coverageLoading && <p className="text-sm text-muted-foreground">Loading insurance options…</p>}
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
                <SelectTrigger className="mt-1"><SelectValue placeholder="Select your insurer" /></SelectTrigger>
                <SelectContent>
                  {insurers.map(opt => (
                    <SelectItem key={opt.key} value={opt.key}>{opt.label}</SelectItem>
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
                <SelectTrigger className="mt-1"><SelectValue placeholder="Select your plan" /></SelectTrigger>
                <SelectContent>
                  {planChoices.map(plan => (
                    <SelectItem key={plan} value={plan}>{plan}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Member ID <span className="text-muted-foreground font-normal">(optional)</span></Label>
              <Input value={memberId} onChange={e => setMemberId(e.target.value)} className="mt-1" />
            </div>
            <div>
              <Label>Plan type</Label>
              <Select value={planType} onValueChange={v => setPlanType(v as InsuranceProfile['planType'])}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {['PPO', 'HMO', 'EPO', 'Other'].map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Deductible ($)</Label>
                <Input type="number" value={deductible || ''} onChange={e => setDeductible(Number(e.target.value))} className="mt-1" />
              </div>
              <div>
                <Label>OOP max ($)</Label>
                <Input type="number" value={oopMax || ''} onChange={e => setOopMax(Number(e.target.value))} className="mt-1" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Copay ($) <span className="text-muted-foreground font-normal">opt.</span></Label>
                <Input type="number" value={copay || ''} onChange={e => setCopay(Number(e.target.value))} className="mt-1" />
              </div>
              <div>
                <Label>Coinsurance (%)</Label>
                <Input type="number" min={0} max={100} value={coinsurance ?? 0} onChange={e => setCoinsurance(Number(e.target.value))} className="mt-1" />
              </div>
            </div>
            <div className="flex gap-3 mt-2">
              {startStep === 0 && (
                <Button variant="outline" className="flex-1 h-11" onClick={() => setStep(0)}>Back</Button>
              )}
              <Button
                className="flex-1 bg-primary text-primary-foreground hover:bg-primary-hover h-11"
                onClick={save}
                disabled={!canSaveCoverage || saving}
              >
                {saving ? 'Saving…' : 'Save & see estimates'}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};

export default InsuranceDialog;
