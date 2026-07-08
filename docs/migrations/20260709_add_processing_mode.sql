ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS processing_mode VARCHAR(20) NOT NULL DEFAULT 'premium';

UPDATE jobs
SET processing_mode = 'premium'
WHERE processing_mode IS NULL;

DO $$
BEGIN
  ALTER TABLE jobs
  ADD CONSTRAINT jobs_processing_mode_check
  CHECK (processing_mode IN ('premium', 'cheap'));
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;
