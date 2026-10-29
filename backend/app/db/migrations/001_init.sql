-- Faultline schema (spec Section 6). Stage 1 uses a subset of the columns;
-- the rest exist so later stages never alter these tables.

CREATE TABLE sources (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name           text NOT NULL UNIQUE,
    es_url         text NOT NULL,
    index_pattern  text NOT NULL,
    service_field  text NOT NULL,
    watermark      timestamptz,
    enabled        boolean NOT NULL DEFAULT true
);

CREATE TABLE users (
    id            text PRIMARY KEY,
    email         text,
    display_name  text,
    role          text NOT NULL,
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE runs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    requested_by  text,
    started_at    timestamptz,
    finished_at   timestamptz,
    window_start  timestamptz,
    window_end    timestamptz,
    status        text NOT NULL,
    stats         jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX runs_status_idx ON runs (status);
CREATE INDEX runs_started_at_idx ON runs (started_at DESC);

CREATE TABLE fingerprints (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    service             text NOT NULL,
    level               text NOT NULL,
    drain_cluster_id    integer NOT NULL,
    template            text NOT NULL,
    category            text,
    severity            text,
    team_id             uuid,
    status              text NOT NULL DEFAULT 'new',
    merged_into_id      uuid REFERENCES fingerprints (id),
    first_seen          timestamptz NOT NULL,
    last_seen           timestamptz NOT NULL,
    total_count         bigint NOT NULL DEFAULT 0,
    deferred            boolean NOT NULL DEFAULT false,
    suppression         text NOT NULL DEFAULT 'none',
    snoozed_until       timestamptz,
    alert_on_spike      boolean NOT NULL DEFAULT false,
    suppression_reason  text,
    suppressed_by       text,
    suppressed_at       timestamptz,
    UNIQUE (service, drain_cluster_id)
);
CREATE INDEX fingerprints_status_severity_last_seen_idx ON fingerprints (status, severity, last_seen);
CREATE INDEX fingerprints_suppression_idx ON fingerprints (suppression, snoozed_until);

CREATE TABLE occurrences (
    fingerprint_id  uuid NOT NULL REFERENCES fingerprints (id),
    run_id          uuid NOT NULL REFERENCES runs (id),
    window_start    timestamptz NOT NULL,
    window_end      timestamptz NOT NULL,
    count           integer NOT NULL,
    PRIMARY KEY (fingerprint_id, run_id, window_start)
);
CREATE INDEX occurrences_fp_window_idx ON occurrences (fingerprint_id, window_start);

CREATE TABLE samples (
    id              bigserial PRIMARY KEY,
    fingerprint_id  uuid NOT NULL REFERENCES fingerprints (id),
    redacted_text   text NOT NULL,
    seen_at         timestamptz NOT NULL
);
CREATE INDEX samples_fp_seen_idx ON samples (fingerprint_id, seen_at DESC);

CREATE TABLE resolutions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fingerprint_id  uuid NOT NULL REFERENCES fingerprints (id),
    summary         text NOT NULL,
    probable_cause  text NOT NULL,
    steps           jsonb NOT NULL DEFAULT '[]'::jsonb,
    sources         jsonb NOT NULL DEFAULT '[]'::jsonb,
    confidence      text NOT NULL,
    origin          text NOT NULL,
    status          text NOT NULL,
    approved_by     text,
    approved_at     timestamptz,
    embedding       real[]
);
CREATE INDEX resolutions_fp_idx ON resolutions (fingerprint_id);

CREATE TABLE review_items (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          uuid NOT NULL REFERENCES runs (id),
    fingerprint_id  uuid NOT NULL REFERENCES fingerprints (id),
    proposed        jsonb NOT NULL,
    decision        text NOT NULL DEFAULT 'pending',
    edited          jsonb,
    reviewer        text,
    comment         text,
    decided_at      timestamptz,
    UNIQUE (run_id, fingerprint_id)
);
CREATE INDEX review_items_fp_idx ON review_items (fingerprint_id);

CREATE TABLE drain_state (
    service     text PRIMARY KEY,
    state       bytea NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
