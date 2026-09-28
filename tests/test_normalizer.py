"""Unit tests for Dy David's normalizers and parsers."""

from __future__ import annotations

import os

import pytest

from engine.normalize import normalize_jd, normalize_resume
from engine.normalize.parser import parse_resume_bytes
from engine.normalize.schema import Job, Resume


def test_normalize_jd_basic():
    os.environ["ENGINE_MODE"] = "mock"
    sample_jd = (
        "Junior Web Developer needed at Angkor Digital.\n"
        "Requirements:\n"
        "- Bachelor's degree in Computer Science or IT.\n"
        "- Experience with HTML5, CSS3, and JavaScript.\n"
        "- English fluency."
    )
    job = normalize_jd(sample_jd)
    assert isinstance(job, Job)
    assert len(job.requirements) > 0
    assert job.content_hash is not None


def test_normalize_jd_empty():
    with pytest.raises(ValueError, match="empty"):
        normalize_jd("")


def test_normalize_resume_mock():
    os.environ["ENGINE_MODE"] = "mock"
    dummy_bytes = b"Dummy resume content with Python and Java projects."
    resume = normalize_resume(dummy_bytes, "resume.txt")
    assert isinstance(resume, Resume)
    assert len(resume.evidence) > 0


def test_parse_resume_bytes_invalid():
    with pytest.raises(ValueError):
        parse_resume_bytes(b"", "empty.pdf")


def test_normalizer_caching():
    from engine.normalize.normalizer import clear_normalizer_cache
    clear_normalizer_cache()

    sample_jd = "React frontend developer at TechCorp."
    job1 = normalize_jd(sample_jd)
    job2 = normalize_jd(sample_jd)
    assert job1 is job2

    dummy_bytes = b"Jane Doe - Software Engineer"
    res1 = normalize_resume(dummy_bytes, "jane.txt")
    res2 = normalize_resume(dummy_bytes, "jane.txt")
    assert res1 is res2

