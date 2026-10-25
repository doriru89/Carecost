import type { Payment } from "@/generated/contracts/quote_api";

/**
 * How-are-you-paying options (plan §4.1, D4). Insurers = the payers A2 loads TiC files for
 * (data/etl/tic_networks.yaml); `payments.test.ts` fails when that registry gains or loses a
 * payer / product. INDEMNITY and unnamed products are not offered as a choice (nobody knows
 * their plan by those names); the engine still reads them for the other-payer range bar.
 */
export interface PayerOption {
  payer_id: string;
  label: string;
  products: string[];
  /** TiC files exist but A2 cannot read them yet (zip container): quotes will say not_loaded. */
  tic_pending?: true;
}

export const INSURERS: PayerOption[] = [
  { payer_id: "BCBS_MA", label: "Blue Cross Blue Shield of MA", products: ["HMO", "PPO"] },
  { payer_id: "HARVARD_PILGRIM", label: "Harvard Pilgrim", products: ["HMO", "POS", "PPO", "EPO"], tic_pending: true },
  { payer_id: "TUFTS_HP", label: "Tufts Health Plan", products: ["HMO"], tic_pending: true },
  { payer_id: "MGB_HP", label: "Mass General Brigham Health Plan", products: ["HMO", "PPO"] },
  { payer_id: "AETNA", label: "Aetna", products: ["PPO", "POS", "EPO"] },
  { payer_id: "UHC", label: "UnitedHealthcare", products: ["HMO", "POS", "PPO"] },
  { payer_id: "FALLON", label: "Fallon Health", products: ["HMO"] },
];

/** A flat option list for one <select>: every insurer × product, then the three non-insurance ways. */
export interface PaymentChoice {
  id: string;
  label: string;
  group: "insurance" | "other";
  payment: Payment;
  note?: string;
}

export const PAYMENT_CHOICES: PaymentChoice[] = [
  ...INSURERS.flatMap((p) =>
    p.products.map<PaymentChoice>((product) => ({
      id: `${p.payer_id}:${product}`,
      label: `${p.label} · ${product}`,
      group: "insurance",
      payment: { kind: "insurance", payer_id: p.payer_id, product, network: null },
      note: p.tic_pending ? "Insurer price files not loaded yet" : undefined,
    })),
  ),
  { id: "medicare", label: "Medicare (traditional)", group: "other", payment: { kind: "medicare" } },
  { id: "masshealth", label: "MassHealth (Medicaid)", group: "other", payment: { kind: "masshealth" } },
  { id: "cash", label: "Cash / no insurance", group: "other", payment: { kind: "cash" } },
];

export function paymentId(p: Payment): string {
  return p.kind === "insurance" ? `${p.payer_id}:${p.product}` : p.kind;
}

export function choiceFor(p: Payment): PaymentChoice | undefined {
  const id = paymentId(p);
  return PAYMENT_CHOICES.find((c) => c.id === id);
}

export function paymentLabel(p: Payment): string {
  return choiceFor(p)?.label ?? paymentId(p);
}
