"""Glossary: plain name first, own words, only public-domain sources paraphrased."""

from __future__ import annotations

from app.care_paths import validator

REQUIRED_TERMS = {
    "xray",
    "mri",
    "ultrasound",
    "mr_arthrogram",
    "steroid_injection",
    "pt_evaluation",
    "biopsy",
    "pathology",
    "colonoscopy",
    "anesthesia",
    "deductible",
    "copay",
    "coinsurance",
    "facility_fee",
    "in_network",
    "bundle_price",
    "referral",
    "hmo",
    "ppo",
}

LINK_ONLY_HOSTS = ("radiologyinfo.org", "orthoinfo.aaos.org", "orthoinfo.org", "aad.org")


def test_required_terms_present(bundle):
    missing = REQUIRED_TERMS - set(bundle.glossary.terms)
    assert not missing, missing


def test_plain_name_leads(bundle):
    for key, t in bundle.glossary.terms.items():
        assert t.plain_name and t.technical_name, key
        assert t.plain_name.lower() != t.technical_name.lower(), key
        for trig in t.triggers:
            assert trig.lower() not in t.plain_name.lower(), (
                f"{key}: plain name uses jargon {trig!r}"
            )


def test_paraphrased_only_from_public_domain(bundle):
    for key, t in bundle.glossary.terms.items():
        src = bundle.sources[t.based_on]
        assert src.license == "public_domain_us_gov", f"{key} paraphrases non-PD {t.based_on}"
        for link in t.link_out:
            assert link.url.startswith("https://"), key


def test_link_only_sources_never_paraphrased(bundle):
    for key, t in bundle.glossary.terms.items():
        src = bundle.sources[t.based_on]
        assert not any(h in src.url for h in LINK_ONLY_HOSTS), key


def test_glossary_text_is_not_a_copy(bundle):
    """Paraphrase, don't paste: no 8-word run shared with the stored source excerpts."""
    problems = validator.check_glossary_not_copied(bundle)
    assert not problems, "\n".join(problems)


def test_every_glossary_key_used_by_paths_exists(bundle):
    for path in bundle.paths.values():
        for key in path.glossary:
            assert key in bundle.glossary.terms, f"{path.id}: {key}"
        for step in path.steps:
            for key in step.glossary:
                assert key in bundle.glossary.terms, f"{path.id}.{step.id}: {key}"
