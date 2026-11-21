-- Model trials (product owner 2026-11-21): the tables verigence.di.trials.model_trial reads and writes.
-- They are not part of the product: nothing a person sees reads them, and they can be dropped once a
-- trial has been decided on. Created by hand in the DEV database on 2026-11-21, kept here for the record.

CREATE SCHEMA IF NOT EXISTS di_trials;

-- Which documents a run reads, chosen beforehand.
CREATE TABLE IF NOT EXISTS di_trials.sample (
  run text NOT NULL,
  tenant_id text NOT NULL,
  document_id uuid NOT NULL,
  document_type_key text NOT NULL,
  stratum text NOT NULL,            -- why it is in the sample: CORRECTED (a person corrected a field) or RANDOM
  PRIMARY KEY (run, document_id)
);

-- What each model made of each document.
CREATE TABLE IF NOT EXISTS di_trials.result (
  run text NOT NULL,
  tenant_id text NOT NULL,
  document_id uuid NOT NULL,
  document_type_key text NOT NULL,
  model text NOT NULL,              -- the model called
  asked_model text NOT NULL,        -- the name the request asked for
  tier text NOT NULL,
  thinking text NOT NULL,           -- the thinking setting the read was made with ('' = the model's default)
  ok boolean NOT NULL,
  error_code text,
  error_detail text,               -- the provider's words for a refusal (about the request, not the page)
  http_status integer NOT NULL DEFAULT 0,
  duration_ms numeric NOT NULL DEFAULT 0,
  prompt_tokens integer NOT NULL DEFAULT 0,
  response_tokens integer NOT NULL DEFAULT 0,
  thoughts_tokens integer NOT NULL DEFAULT 0,
  cached_tokens integer NOT NULL DEFAULT 0,
  fields jsonb NOT NULL DEFAULT '{}'::jsonb,   -- field key -> {found, value, norm, confidence, page}
  checks jsonb NOT NULL DEFAULT '{}'::jsonb,   -- field key -> passed the check that needs no model
  created_at_utc timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run, document_id, model)
);

GRANT USAGE ON SCHEMA di_trials TO di_runtime;
GRANT SELECT ON di_trials.sample TO di_runtime;
GRANT SELECT, INSERT, UPDATE ON di_trials.result TO di_runtime;   -- UPDATE: a failed read may be made again
