"""Site facts read from each site's own website (P10, contract X1).

Official name, phone, hours and which services a site offers, each claim backed by a URL and a
verbatim quote from the page as we cached it. Two independent extraction runs are merged; where
they disagree Austin decides. ``docs/etl/site_facts.md`` is the runbook.

    python -m app.site_facts discover   # data/sites/site_facts/pages.yaml (own pages per site)
    python -m app.site_facts fetch      # polite fetch -> gitignored cache + committed manifest
    python -m app.site_facts verify RUN # reject claims whose quote is not in the cached page
    python -m app.site_facts merge A B  # facts.yaml + review page
    python -m app.site_facts coverage   # own page found / 208, by kind; hours in text
"""
