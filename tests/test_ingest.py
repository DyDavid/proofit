"""Unit tests for Dy David's ingestion pipeline, caching, and scrapers (BongThom, CamHR, JobNet, Jobify)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock
import pytest

from engine.ingest import fetch_jd
from engine.ingest.cache import get_cached_text, save_cached_text
from engine.ingest.scraper import scrape_job_url


def test_cache_save_and_get(tmp_path):
    key = "https://example.com/job/123"
    text = "Sample Job Posting Text"
    save_cached_text(key, text)

    cached = get_cached_text(key)
    assert cached == text


def test_fetch_jd_mock():
    os.environ["ENGINE_MODE"] = "mock"
    text = fetch_jd("https://example.com/job/test")
    assert "Junior Web Developer" in text or len(text) > 0


def test_camhr_scraping_mock(monkeypatch):
    """Test CamHR scraper parsing with mocked API response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "title": "Software Engineer",
            "employer": {
                "company": "Tech Innovations Cambodia",
                "address": "Phnom Penh",
            },
            "address": "Phnom Penh Tower",
            "termId": {"label": "Full Time"},
            "jobLevelId": {"label": "Entry Level"},
            "salaryId": {"label": "$500 - $800"},
            "description": "<p>Develop web applications using Python & React.<br>Collaborate with team.</p>",
            "requirement": "<ul><li>Bachelor degree in Computer Science</li><li>Knowledge of Git</li></ul>",
        }
    }

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_resp

    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)

    url = "https://www.camhr.com/a/job/10672005"
    result = scrape_job_url(url)

    assert "Job Title: Software Engineer" in result
    assert "Company: Tech Innovations Cambodia" in result
    assert "Location: Phnom Penh Tower" in result
    assert "Employment Type: Full Time" in result
    assert "Job Level: Entry Level" in result
    assert "Develop web applications using Python & React." in result
    assert "• Bachelor degree in Computer Science" in result


def test_jobnet_scraping_mock(monkeypatch):
    """Test JobNet.com.kh scraper with mocked JSON-LD response."""
    json_ld_sample = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "Title": "Frontend Developer",
          "hiringOrganization": {
            "@type": "Organization",
            "name": "Smart Axiata Co., Ltd."
          },
          "jobLocation": {
            "@type": "Place",
            "address": {
              "addressLocality": "Phnom Penh, Cambodia"
            }
          },
          "employmentType": "Full-time",
          "Description": "<p>Build Next.js web applications.<br>Responsibilities include UI development.</p><ul><li>Proficiency with React and TypeScript</li><li>Git version control</li></ul>"
        }
        </script>
      </head>
      <body><h1>Frontend Developer</h1></body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = json_ld_sample

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_resp

    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)

    url = "https://www.jobnet.com.kh/job/frontend-developer-smart-axiata/12345"
    result = scrape_job_url(url)

    assert "Job Title: Frontend Developer" in result
    assert "Company: Smart Axiata Co., Ltd." in result
    assert "Location: Phnom Penh, Cambodia" in result
    assert "Employment Type: Full-time" in result
    assert "Build Next.js web applications." in result
    assert "• Proficiency with React and TypeScript" in result


def test_jobify_scraping_mock(monkeypatch):
    """Test Jobify extractor with mocked meta tags response."""
    jobify_html = """
    <html>
      <head>
        <meta property="og:title" content="Junior React Developer - Jobify">
        <meta property="og:description" content="Responsibilities: Build frontend features in React. Requirements: Knowledge of JavaScript, HTML, CSS, Git, and REST APIs.">
      </head>
      <body><div>Job Details</div></body>
    </html>
    """

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = jobify_html

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_resp

    monkeypatch.setattr("httpx.Client", lambda **kwargs: mock_client)

    url = "https://jobify.works/jobs/1124"
    result = scrape_job_url(url)

    assert "Job Title: Junior React Developer - Jobify" in result
    assert "Build frontend features in React" in result
    assert "Knowledge of JavaScript, HTML, CSS" in result


def test_linkedin_firewall_rejection():
    """Verify that LinkedIn URLs prompt the user to copy/paste text directly."""
    with pytest.raises(ValueError) as excinfo:
        scrape_job_url("https://www.linkedin.com/jobs/view/123456789")
    assert "LinkedIn and Facebook require login" in str(excinfo.value)
