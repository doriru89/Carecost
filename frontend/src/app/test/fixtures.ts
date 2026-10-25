import type { QuoteResponse } from "@/generated/contracts/quote_api";
import bcbs from "../../../../contracts/fixtures/quote_bcbs_hmo_shoulder.json";
import cash from "../../../../contracts/fixtures/quote_cash_shoulder.json";
import medicare from "../../../../contracts/fixtures/quote_medicare_shoulder.json";

export const BCBS = bcbs as unknown as QuoteResponse;
export const CASH = cash as unknown as QuoteResponse;
export const MEDICARE = medicare as unknown as QuoteResponse;
export const ALL_QUOTES = [BCBS, CASH, MEDICARE];
