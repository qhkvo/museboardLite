CREATE TABLE IF NOT EXISTS schema_migrations (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS boards (
  id uuid PRIMARY KEY,
  name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 100),
  description text NOT NULL DEFAULT '' CHECK (length(description) <= 1000),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS images (
  id uuid PRIMARY KEY,
  board_id uuid NOT NULL REFERENCES boards(id),
  original_path text UNIQUE NOT NULL,
  original_filename text NOT NULL,
  mime_type text NOT NULL CHECK (mime_type IN ('image/jpeg', 'image/png')),
  byte_size bigint NOT NULL CHECK (byte_size > 0),
  width integer NOT NULL CHECK (width > 0),
  height integer NOT NULL CHECK (height > 0),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS images_board_created_idx ON images(board_id, created_at DESC, id DESC);
INSERT INTO schema_migrations(version) VALUES (1) ON CONFLICT DO NOTHING;

-- Migration 2: run once, including jobs for images uploaded before workers existed.
DO $$
BEGIN
IF NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=2) THEN
  ALTER TABLE images ADD COLUMN thumbnail_path text;
  CREATE TABLE image_features (
    image_id uuid PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
    palette_json jsonb,
    embedding real[] CHECK (array_ndims(embedding)=1 AND array_length(embedding,1)=512),
    model_id text,
    CHECK ((embedding IS NULL) = (model_id IS NULL))
  );
  CREATE TABLE jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    image_id uuid NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    type text NOT NULL CHECK (type IN ('cpu_process','ai_embed')),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','running','succeeded','failed')),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    attempt_token uuid,
    lease_expires_at timestamptz,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(image_id,type),
    CHECK (status != 'running' OR (attempt_token IS NOT NULL AND lease_expires_at IS NOT NULL))
  );
  CREATE INDEX jobs_claim_idx ON jobs(type, status, created_at, id);
  INSERT INTO image_features(image_id) SELECT id FROM images;
  INSERT INTO jobs(image_id,type) SELECT id, 'cpu_process' FROM images
    UNION ALL SELECT id, 'ai_embed' FROM images;
  INSERT INTO schema_migrations(version) VALUES (2);
END IF;
END $$;

-- Migration 3: preserve existing embeddings while enabling exact vector search.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;
DO $$
BEGIN
IF NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=3) THEN
  ALTER TABLE image_features DROP CONSTRAINT image_features_embedding_check;
  ALTER TABLE image_features ALTER COLUMN embedding TYPE public.vector(512)
    USING embedding::public.vector(512);
  INSERT INTO schema_migrations(version) VALUES (3);
END IF;
END $$;

-- Migration 4: user-maintained subject labels, independent of processing jobs.
DO $$
BEGIN
IF NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version=4) THEN
  ALTER TABLE images ADD COLUMN subject_tags text[] NOT NULL DEFAULT '{}';
  CREATE INDEX images_subject_tags_idx ON images USING gin(subject_tags);
  INSERT INTO schema_migrations(version) VALUES (4);
END IF;
END $$;
