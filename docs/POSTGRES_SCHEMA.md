# PostgreSQL schema (CareCost)

ORM definitions live in `backend/app/db/tables.py`. At runtime, `get_engine()` runs `Base.metadata.create_all` so missing tables are created (no Alembic).

| Table | Purpose |
|-------|---------|
| `providers` | NPI PK, lat/lng, `specialties` text[], `source`, `hospital` |
| `procedures` | `bundle_id` PK, `cpt_codes` text[] |
| `prices` | FK to `providers.npi`; unique (`provider_id`, `bundle_id`, `payer`, `source`, `effective_date`) |
| `insurers` | Plan rows for sample data |
| `hospital_rates` | Hospital × CPT columns (negotiated + de-identified rates) |
| `users` | UUID PK, unique `email`, `password_hash`, `user_profile` / `insurance_profile` JSONB |

Indexes: GIN on `providers.specialties`, btree on `providers.zip`, composite on prices and `hospital_rates (hospital_id, cpt)`.
