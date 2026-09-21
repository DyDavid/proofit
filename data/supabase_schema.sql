-- ============================================================================
-- PROOFIT DATABASE SCHEMA (Supabase PostgreSQL + pgvector)
-- ============================================================================
-- Run this script in the Supabase SQL Editor (Dashboard -> SQL Editor -> New Query).
-- ============================================================================

-- 1. Enable Required PostgreSQL Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- 2. Resumes Table
CREATE TABLE IF NOT EXISTS resumes (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/pdf',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    raw_text TEXT,
    normalized JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Jobs Table
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    content_hash TEXT UNIQUE NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('text', 'url')),
    raw TEXT NOT NULL,
    title TEXT,
    company TEXT,
    location TEXT,
    normalized JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Analyses Table
CREATE TABLE IF NOT EXISTS analyses (
    id TEXT PRIMARY KEY,
    resume_id TEXT REFERENCES resumes(id) ON DELETE SET NULL,
    job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    country TEXT NOT NULL DEFAULT 'KH',
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'done', 'failed')) DEFAULT 'queued',
    stage TEXT CHECK (stage IN ('reading_resume', 'reading_job', 'matching_requirements', 'checking_realism', 'generating_rewrites', NULL)),
    match JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5. JD Requirements (with 768-dimensional Gemini Embeddings)
CREATE TABLE IF NOT EXISTS jd_requirements (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    jd_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
    jd_hash TEXT NOT NULL,
    req_id TEXT NOT NULL,
    category TEXT NOT NULL,
    is_required BOOLEAN NOT NULL DEFAULT TRUE,
    description TEXT NOT NULL,
    canonical_skill TEXT,
    embedding vector(768),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. Resume Evidence (with 768-dimensional Gemini Embeddings)
CREATE TABLE IF NOT EXISTS resume_evidence (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    resume_id TEXT REFERENCES resumes(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    description TEXT NOT NULL,
    duration_months INTEGER DEFAULT 0,
    team_size INTEGER,
    outcome TEXT,
    embedding vector(768),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Indexes for Fast Lookup & Search
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_jobs_content_hash ON jobs(content_hash);
CREATE INDEX IF NOT EXISTS idx_analyses_resume_id ON analyses(resume_id);
CREATE INDEX IF NOT EXISTS idx_analyses_job_id ON analyses(job_id);
CREATE INDEX IF NOT EXISTS idx_analyses_created_at ON analyses(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jd_req_hash ON jd_requirements(jd_hash);
CREATE INDEX IF NOT EXISTS idx_resume_ev_resume_id ON resume_evidence(resume_id);

-- Optional HNSW Vector Indexes for Fast Approximate Nearest Neighbor (ANN) Search
CREATE INDEX IF NOT EXISTS idx_jd_req_embedding 
ON jd_requirements 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_resume_ev_embedding 
ON resume_evidence 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- ============================================================================
-- Row Level Security (RLS) & Server Access
-- ============================================================================
-- Enable RLS on all tables
ALTER TABLE resumes ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE jd_requirements ENABLE ROW LEVEL SECURITY;
ALTER TABLE resume_evidence ENABLE ROW LEVEL SECURITY;

-- Allow full access to service_role (used by Proofit FastAPI backend)
CREATE POLICY "Service Role full access on resumes" ON resumes FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service Role full access on jobs" ON jobs FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service Role full access on analyses" ON analyses FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service Role full access on jd_requirements" ON jd_requirements FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service Role full access on resume_evidence" ON resume_evidence FOR ALL TO service_role USING (true) WITH CHECK (true);

-- (Optional) Allow public read access on analyses for shareable results
CREATE POLICY "Allow anon read analyses" ON analyses FOR SELECT TO anon USING (true);
