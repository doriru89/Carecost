# Errata — Shared Failure Patterns

Known failure patterns that both developers (and their AI agents) should check before writing code in a given area.

## How to Use

Before modifying code in an area, check if there's a pattern file for it:

```bash
ls .errata/patterns/
```

Each YAML file describes: what goes wrong, how to detect it, how to prevent it, and a real incident.

## Adding New Patterns

After discovering a bug caused by a repeated mistake:

1. Create `.errata/patterns/<descriptive-name>.yaml`
2. Fill in all 5 fields (see existing files for format)
3. Commit with the fix that inspired it

## Integration

- `AGENTS.md` directs AI to check `.errata/patterns/` before writing code
- CI does not enforce errata (it's guidance, not a gate)
- Patterns are additive — never delete one unless the underlying architecture changed
