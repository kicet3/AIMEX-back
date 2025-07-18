-- Add system_prompt column to AI_INFLUENCER table
-- This SQL script manually adds the system_prompt column to fix the database migration issue

USE AIMEX_MAIN;

-- Add the system_prompt column
ALTER TABLE AI_INFLUENCER 
ADD COLUMN system_prompt TEXT COMMENT 'AI 인플루언서 시스템 프롬프트';

-- Update the alembic_version table to mark this migration as complete
UPDATE alembic_version 
SET version_num = '136d6e9dd006' 
WHERE version_num = '8daeff3811d0';

-- Verify the column was added
DESCRIBE AI_INFLUENCER;