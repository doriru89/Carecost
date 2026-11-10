/**
 * The price items a person can pick for one quote (P3 / D-UI-3): one option's headline per site ("whole
 * visit", option A / B), or one step. The map pins and the list's step line show the chosen item. Owned by
 * CareApp so the chips can sit in the chat (next to the care path they belong to) or in the results pane.
 */
import type { QuoteResponse } from "@/generated/contracts/quote_api";
import { headlineMapChoices, type MapChoice } from "./headline";
import { mapStepKeys, stepLabels } from "./steps";

export function priceChoices(quote: QuoteResponse): MapChoice[] {
  const labels = stepLabels(quote);
  return [
    ...headlineMapChoices(quote),
    ...mapStepKeys(quote).map((k) => ({ id: k, label: labels[k] ?? k, item: { kind: "step" as const, key: k } })),
  ];
}

/** A manual pick of one service has one step: it is the chosen item without a click. */
export function onlyStepOf(quote: QuoteResponse): string | null {
  const keys = mapStepKeys(quote);
  return !quote.care_path && keys.length === 1 ? keys[0] : null;
}
