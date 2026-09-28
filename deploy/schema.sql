-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Job Description Requirements Table
CREATE TABLE IF NOT EXISTS jd_requirements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    jd_hash TEXT NOT NULL,
    category TEXT CHECK (category IN ('hard_skill', 'soft_skill', 'education', 'certification', 'experience', 'language')),
    is_required BOOLEAN NOT NULL DEFAULT true,
    description TEXT NOT NULL,
    canonical_skill TEXT,
    embedding vector(768), -- Dimensions: 768 for text-embedding-004
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Resume Evidence Records Table
CREATE TABLE IF NOT EXISTS resume_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resume_id UUID NOT NULL,
    evidence_type TEXT CHECK (evidence_type IN ('employment', 'internship', 'part-time', 'coursework', 'project', 'volunteer', 'certification', 'competition')),
    description TEXT NOT NULL,
    duration_months INT DEFAULT 0,
    team_size INT,
    outcome TEXT,
    embedding vector(768), -- Dimensions: 768 for text-embedding-004
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Match Verdicts Table
CREATE TABLE IF NOT EXISTS match_verdicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requirement_id UUID REFERENCES jd_requirements(id),
    evidence_id UUID REFERENCES resume_evidence(id),
    verdict TEXT CHECK (verdict IN ('Proven', 'Partial', 'Missing')),
    reasoning TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Performance Indexing
CREATE INDEX IF NOT EXISTS idx_jd_hash ON jd_requirements(jd_hash);
CREATE INDEX IF NOT EXISTS idx_req_embedding ON jd_requirements USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_evidence_embedding ON resume_evidence USING ivfflat (embedding vector_cosine_ops);
