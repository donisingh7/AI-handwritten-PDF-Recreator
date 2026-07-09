ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS processing_mode VARCHAR(20) NOT NULL DEFAULT 'premium';

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS ai_provider TEXT;

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS ai_model TEXT;

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS model_option_id TEXT;

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS cleanup_preset TEXT;

UPDATE jobs
SET processing_mode = 'premium'
WHERE processing_mode IS NULL;
