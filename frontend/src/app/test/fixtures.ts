import type { QuoteResponse, Receipt, SiteQuote } from "@/generated/contracts/quote_api";
import bcbs from "../../../../contracts/fixtures/quote_bcbs_hmo_shoulder.json";
import cash from "../../../../contracts/fixtures/quote_cash_shoulder.json";
import masshealth from "../../../../contracts/fixtures/quote_masshealth_manual.json";
import medicare from "../../../../contracts/fixtures/quote_medicare_shoulder.json";

/**
 * C3 made `SiteQuote.receipt` nullable (only the first `full_receipts` sites of a no-location list carry
 * one). Every committed quote fixture is a `near` request, so every site carries its receipt; this type
 * says so, and logic.test.ts checks it against the files.
 */
export type FixtureQuote = Omit<QuoteResponse, "sites"> & { sites: (SiteQuote & { receipt: Receipt })[] };

export const BCBS = bcbs as unknown as FixtureQuote;
export const CASH = cash as unknown as FixtureQuote;
export const MEDICARE = medicare as unknown as FixtureQuote;
export const MASSHEALTH = masshealth as unknown as FixtureQuote;
export const ALL_QUOTES = [BCBS, CASH, MEDICARE, MASSHEALTH];
