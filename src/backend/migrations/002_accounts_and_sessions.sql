-- PaperLens v0.2 account ownership and durable chat-session metadata.
-- Existing rows remain assigned to the local-development account. Before
-- enabling AUTH_ENABLED in production, explicitly reassign or remove them.

ALTER TABLE papers
  ADD COLUMN IF NOT EXISTS user_id VARCHAR(64) NOT NULL DEFAULT 'local-user';
CREATE INDEX IF NOT EXISTS ix_papers_user_id ON papers (user_id);

ALTER TABLE agent_conversations
  ADD COLUMN IF NOT EXISTS user_id VARCHAR(64) NOT NULL DEFAULT 'local-user';
ALTER TABLE agent_conversations
  ADD COLUMN IF NOT EXISTS title VARCHAR(512);
CREATE INDEX IF NOT EXISTS ix_agent_conversations_user_id
  ON agent_conversations (user_id);
