#!/usr/bin/env node
/**
 * Copies the reviewed content the UI shows into small JSON files the bundle imports.
 *
 *   content/glossary/glossary.yaml   -> src/app/content/glossary.json  (hover text, D8)
 *   data/questions/questions.yaml    -> src/app/content/cards.json     (chat card_ids)
 *                                    -> src/app/content/questions.json (labels for "I understood: ...")
 *   zipcodes npm package (MA only)   -> src/app/content/ma_zips.json   (typed ZIP -> centroid, distance
 *                                                                      is computed in the browser, §4.3)
 *
 * The YAML files stay the source of truth. `npm run content:build` rewrites the JSON;
 * `src/app/content/content.test.ts` fails when the committed JSON is stale.
 *
 * Usage: node scripts/build-content.mjs [--check]
 */
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../..");
const out = resolve(here, "../src/app/content");

export function buildGlossary(yamlText) {
  const doc = parse(yamlText);
  const terms = {};
  for (const [key, t] of Object.entries(doc.terms)) {
    terms[key] = {
      plain_name: t.plain_name,
      technical_name: t.technical_name,
      short: String(t.short ?? "").trim(),
      link_out: (t.link_out ?? []).map((l) => ({ label: l.label, url: l.url })),
    };
  }
  return { version: doc.version, credit: doc.credit, review_status: doc.review?.status ?? null, terms };
}

export function buildCards(yamlText) {
  const doc = parse(yamlText);
  const cards = {};
  for (const c of doc.cards ?? []) {
    cards[c.id] = { kind: c.kind, title: c.title?.en ?? c.id, text: String(c.text ?? "").trim() };
  }
  return { version: doc.version, cards };
}

export function buildQuestions(yamlText) {
  const doc = parse(yamlText);
  const questions = {};
  for (const q of doc.questions ?? []) {
    questions[q.id] = {
      text: q.text?.en ?? q.id,
      answers: Object.fromEntries((q.answers ?? []).map((a) => [a.value, a.label?.en ?? a.value])),
    };
  }
  return { version: doc.version, questions };
}

export function buildZips() {
  const require = createRequire(import.meta.url);
  const { codes } = require("zipcodes/lib/codes.js");
  const zips = {};
  for (const [zip, z] of Object.entries(codes)) {
    if (z.state === "MA") zips[zip] = [Number(z.latitude.toFixed(4)), Number(z.longitude.toFixed(4))];
  }
  return { source: "zipcodes@8.0.0 (federalgovernmentzipcodes.us), MA only, [lat, lon]", zips };
}

export function buildAll() {
  return {
    "glossary.json": buildGlossary(readFileSync(resolve(repo, "content/glossary/glossary.yaml"), "utf8")),
    "cards.json": buildCards(readFileSync(resolve(repo, "data/questions/questions.yaml"), "utf8")),
    "questions.json": buildQuestions(readFileSync(resolve(repo, "data/questions/questions.yaml"), "utf8")),
    "ma_zips.json": buildZips(),
  };
}

const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const check = process.argv.includes("--check");
  let stale = 0;
  for (const [name, data] of Object.entries(buildAll())) {
    const path = resolve(out, name);
    const text = JSON.stringify(data, null, 1) + "\n";
    if (check) {
      let cur = "";
      try {
        cur = readFileSync(path, "utf8");
      } catch {
        /* missing */
      }
      if (cur !== text) {
        console.error(`stale: ${name}`);
        stale++;
      }
    } else {
      writeFileSync(path, text);
      console.log(`wrote ${name}`);
    }
  }
  process.exit(stale ? 1 : 0);
}
