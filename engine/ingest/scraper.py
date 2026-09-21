"""Web scraper for job posting URLs with robots.txt compliance, JSON-LD parsing,
and dedicated extractors for Cambodian job boards (BongThom, CamHR, JobNet, Jobify).

OWNER: Person A (Dy David)
"""

from __future__ import annotations

import html as html_module
import json
import logging
import re
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)


def is_url_allowed_by_robots(url: str) -> bool:
    """Check if the URL path is allowed by the host's robots.txt."""
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rfp = RobotFileParser()
        rfp.set_url(robots_url)
        rfp.read()
        return rfp.can_fetch("*", url)
    except Exception as err:
        logger.debug("Could not fetch robots.txt for %s: %s (defaulting to allow)", url, err)
        return True


def _clean_html_text(text: str) -> str:
    """Helper to convert HTML markup into clean human-readable plain text."""
    if not text:
        return ""
    t = html_module.unescape(text)
    t = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", t, flags=re.IGNORECASE)
    t = re.sub(r"<li[^>]*>", "• ", t, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"^[ \t]*[\ufffd\x95\u2022\u25cf\-\*][ \t]*", "• ", t, flags=re.MULTILINE)
    t = re.sub(r"-->|<!--", "", t)
    t = re.sub(r"[\ufffd\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)
    clean_lines = [l.strip() for l in t.splitlines()]
    return "\n".join(l for l in clean_lines if l and l != "&nbsp;")


# ============================================================================
# 1. CamHR Extractor (Public REST API)
# ============================================================================

def scrape_camhr_job(url: str, timeout: float = 15.0) -> str:
    """Extract structured job description text from CamHR via their public REST API."""
    match = re.search(r"(?:/job/|/job-record/|[?&]id=|[?&]jobId=)(\d+)", url)
    if not match:
        match = re.search(r"/(\d{6,10})(?:[/?#]|$)", url)
    if not match:
        raise ValueError(f"Could not identify a valid CamHR job ID in URL: {url}")

    job_id = match.group(1)
    api_url = f"https://api.camhr.com/v1.0.0/jobs/{job_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9,km;q=0.8",
    }

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(api_url, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as err:
        logger.error("CamHR API request failed for job ID %s: %s", job_id, err)
        raise RuntimeError(f"Could not fetch CamHR job details ({err}). Please check the URL or paste the job description text directly.") from err

    job = payload.get("data")
    if not job or not isinstance(job, dict):
        raise RuntimeError(f"CamHR job #{job_id} not found or is no longer active.")

    title = (job.get("title") or "").strip()
    emp = job.get("employer", {})
    company = ""
    if isinstance(emp, dict):
        company = emp.get("company") or emp.get("name") or ""
    elif isinstance(emp, str):
        company = emp

    lines = []
    if title:
        lines.append(f"Job Title: {title}")
    if company:
        lines.append(f"Company: {company.strip()}")

    address = job.get("address") or ""
    if isinstance(emp, dict) and not address:
        address = emp.get("address") or ""
    if address:
        lines.append(f"Location: {address.strip()}")

    term_obj = job.get("termId")
    if isinstance(term_obj, dict) and term_obj.get("label"):
        lines.append(f"Employment Type: {term_obj.get('label').strip()}")

    level_obj = job.get("jobLevelId")
    if isinstance(level_obj, dict) and level_obj.get("label"):
        lines.append(f"Job Level: {level_obj.get('label').strip()}")

    salary_obj = job.get("salaryId")
    if isinstance(salary_obj, dict) and salary_obj.get("label"):
        lines.append(f"Salary: {salary_obj.get('label').strip()}")

    lines.append("")

    description = _clean_html_text(job.get("description", ""))
    if description:
        lines.append("Job Description & Responsibilities:")
        lines.append(description)
        lines.append("")

    requirement = _clean_html_text(job.get("requirement", ""))
    if requirement:
        lines.append("Requirements & Qualifications:")
        lines.append(requirement)
        lines.append("")

    others = _clean_html_text(job.get("othersQualification", ""))
    if others:
        lines.append("Other Information:")
        lines.append(others)
        lines.append("")

    clean_text = "\n".join(lines).strip()
    if not clean_text or len(clean_text) < 40:
        raise RuntimeError(f"Could not extract meaningful job text from CamHR job #{job_id}.")

    return clean_text


# ============================================================================
# 2. JobNet Cambodia Extractor (JSON-LD + Structured Markup)
# ============================================================================

def scrape_jobnet_job(url: str, timeout: float = 15.0) -> str:
    """Extract job description text from JobNet.com.kh via JSON-LD and structured markup."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,km;q=0.8",
    }

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url.strip(), headers=headers)
            resp.raise_for_status()
            html_text = resp.text
    except Exception as err:
        logger.error("JobNet request failed for URL %s: %s", url, err)
        raise RuntimeError(f"Could not load JobNet webpage ({err}). Please check the URL or paste the job description text directly.") from err

    # 1. Try to extract schema.org JSON-LD JobPosting
    json_ld_matches = re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html_text,
        re.DOTALL | re.IGNORECASE,
    )
    for match in json_ld_matches:
        try:
            data = json.loads(match.group(1), strict=False)
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    title = item.get("Title") or item.get("title") or ""
                    company = ""
                    hiring_org = item.get("hiringOrganization") or item.get("HiringOrganization") or {}
                    if isinstance(hiring_org, dict):
                        company = hiring_org.get("name") or hiring_org.get("Name") or ""
                    elif isinstance(hiring_org, str):
                        company = hiring_org

                    location = ""
                    job_loc = item.get("jobLocation") or item.get("JobLocation") or {}
                    if isinstance(job_loc, dict):
                        addr = job_loc.get("address") or {}
                        if isinstance(addr, dict):
                            location = addr.get("addressLocality") or addr.get("streetAddress") or "Phnom Penh, Cambodia"
                        elif isinstance(addr, str):
                            location = addr

                    emp_type = item.get("employmentType") or item.get("EmploymentType") or ""
                    raw_desc = item.get("Description") or item.get("description") or ""
                    clean_desc = _clean_html_text(raw_desc)

                    lines = []
                    if title:
                        lines.append(f"Job Title: {title}")
                    if company:
                        lines.append(f"Company: {company.strip()}")
                    if location:
                        lines.append(f"Location: {location.strip()}")
                    if emp_type:
                        lines.append(f"Employment Type: {emp_type.strip()}")
                    lines.append("")
                    if clean_desc:
                        lines.append(clean_desc)

                    out = "\n".join(lines).strip()
                    if len(out) > 60:
                        return out
        except Exception as json_err:
            logger.debug("Failed parsing JobNet JSON-LD: %s", json_err)

    # 2. Fallback to generic HTML cleanup
    return _extract_generic_html(html_text, url)


# ============================================================================
# 3. Jobify Cambodia Extractor (jobify.works / jobify.com)
# ============================================================================

def scrape_jobify_job(url: str, timeout: float = 15.0) -> str:
    """Extract job description text from Jobify Cambodia (jobify.works / jobify.com) supporting Nuxt SSR state."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,km;q=0.8",
    }

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(url.strip(), headers=headers)
            resp.raise_for_status()
            html_text = resp.text
    except Exception as err:
        logger.error("Jobify request failed for URL %s: %s", url, err)
        raise RuntimeError(
            f"Could not load Jobify webpage ({err}). "
            "Please copy and paste the job description text directly into the 'Paste text' tab."
        ) from err

    # 1. Parse window.__NUXT__ state (used by Jobify Nuxt SSR frontend)
    nuxt_match = re.search(r"window\.__NUXT__\s*=\s*(.*?);</script>", html_text, re.DOTALL)
    if nuxt_match:
        nuxt_code = nuxt_match.group(1)

        # Extract argument mappings from the Nuxt IIFE (function(a,b,...){...})(arg1, arg2, ...)
        args_match = re.search(r"\}\((.*?)\)\s*$", nuxt_code.strip(), re.DOTALL)
        arg_names_match = re.search(r"^\s*\(function\((.*?)\)", nuxt_code.strip())

        var_map: dict[str, str] = {}
        if arg_names_match and args_match:
            names = [n.strip() for n in arg_names_match.group(1).split(",")]
            raw_args_str = args_match.group(1)
            arg_tokens = re.findall(
                r'("(?:\\.|[^"\\])*"|\d+(?:\.\d+)?|true|false|null|undefined|void 0)',
                raw_args_str,
            )
            for i, name in enumerate(names):
                if i < len(arg_tokens):
                    val = arg_tokens[i].strip('"')
                    try:
                        var_map[name] = json.loads(f'"{val}"')
                    except Exception:
                        var_map[name] = val

        def resolve_val(raw_val: str) -> str:
            raw_val = raw_val.strip()
            if raw_val.startswith('"') and raw_val.endswith('"'):
                try:
                    return json.loads(raw_val)
                except Exception:
                    return raw_val[1:-1]
            if raw_val in var_map:
                return var_map[raw_val]
            return raw_val

        def get_field(field_name: str) -> str:
            m = re.search(rf'(?:{field_name})\s*=\s*("(?:\\.|[^"\\])*"|\d+|true|false|[a-zA-Z_]\w*)', nuxt_code)
            if m:
                return resolve_val(m.group(1))
            m2 = re.search(rf'"{field_name}"\s*:\s*("(?:\\.|[^"\\])*"|\d+|true|false|[a-zA-Z_]\w*)', nuxt_code)
            if m2:
                return resolve_val(m2.group(1))
            return ""

        title = get_field("job_title")
        if not title or title.startswith("data-v-") or len(title) > 100:
            h_match = re.search(
                r'<h[1-4][^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</h[1-4]>|<h[1-4][^>]*>(.*?)</h[1-4]>',
                html_text,
                re.IGNORECASE,
            )
            if h_match:
                title = _clean_html_text(h_match.group(1) or h_match.group(2))

        company = get_field("company_name")
        location_parts = [get_field("district"), get_field("city_province"), get_field("country")]
        location = ", ".join([p for p in location_parts if p and p != "null" and not p.isdigit()])

        job_type = get_field("job_type")
        job_level = get_field("job_level")
        exp_year = get_field("exp_year")
        qualification = get_field("qualification")
        min_sal = get_field("min_salary")
        max_sal = get_field("max_salary")

        salary = ""
        if min_sal and max_sal:
            salary = f"${min_sal} - ${max_sal}"
        elif min_sal:
            salary = f"${min_sal}"

        responsible_raw = get_field("responsible")
        requirement_raw = get_field("requirement")
        benefits_raw = get_field("employee_benefit")

        lines = []
        if title:
            lines.append(f"Job Title: {title}")
        if company:
            lines.append(f"Company: {company}")
        if location:
            lines.append(f"Location: {location}")
        if job_type:
            lines.append(f"Employment Type: {job_type}")
        if job_level:
            lines.append(f"Job Level: {job_level}")
        if exp_year:
            lines.append(f"Years of Experience: {exp_year}")
        if qualification:
            lines.append(f"Qualification: {qualification}")
        if salary:
            lines.append(f"Salary: {salary}")

        lines.append("")

        if responsible_raw:
            lines.append("Job Responsibilities:")
            lines.append(_clean_html_text(responsible_raw))
            lines.append("")

        if requirement_raw:
            lines.append("Job Requirements & Qualifications:")
            lines.append(_clean_html_text(requirement_raw))
            lines.append("")

        if benefits_raw and benefits_raw != "null":
            lines.append("Benefits:")
            lines.append(_clean_html_text(benefits_raw))
            lines.append("")

        out = "\n".join(lines).strip()
        if len(out) > 80:
            return out

    # 2. Check for OpenGraph meta tags
    og_title = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', html_text, re.IGNORECASE)
    og_desc = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']', html_text, re.IGNORECASE)

    if og_title and og_desc and len(og_desc.group(1).strip()) > 50:
        return f"Job Title: {og_title.group(1).strip()}\n\n{og_desc.group(1).strip()}"

    # 3. Generic extraction fallback
    try:
        extracted = _extract_generic_html(html_text, url)
        if len(extracted) > 100:
            return extracted
    except Exception:
        pass

    raise ValueError(
        "Could not extract job details from Jobify. "
        "Please copy and paste the job description text directly into the 'Paste text' tab."
    )



# ============================================================================
# 4. Generic Webpage & BongThom / Global Boards Extractor
# ============================================================================

def _extract_generic_html(html_text: str, url: str, fragment: str = "") -> str:
    """Clean and extract text from arbitrary HTML with fragment, JSON-LD, and English-section priority."""
    target_html = html_text
    start_pos = 0

    # If an anchor / fragment is provided (e.g. #position-32196 on BongThom), target that specific section
    if fragment:
        id_pattern = rf'(?:id|name)=["\']{re.escape(fragment)}["\']'
        match = re.search(id_pattern, html_text, re.IGNORECASE)
        if match:
            start_pos = match.start()
            # Stop before next job position or next toggle header
            next_pos_match = re.search(
                r'(?:id=["\']position-\d+["\']|<h3[^>]*onclick=["\']toggleDetails|class=["\'][^"\']*header-line[^"\']*["\'])',
                html_text[start_pos + 30:],
                re.IGNORECASE,
            )
            if next_pos_match:
                target_html = html_text[start_pos : start_pos + 30 + next_pos_match.start()]
            else:
                target_html = html_text[start_pos : start_pos + 20000]

    # Check for dedicated English position container (BongThom: class="pos-details-english")
    en_match = re.search(
        r'<div[^>]*class=["\'][^"\']*pos-details-english[^"\']*["\'][^>]*>(.*?)(?:<div[^>]*class=["\']blank-|<div[^>]*class=["\']pos-details-|<div[^>]*id=["\']position-|<h3|$)',
        target_html,
        re.DOTALL | re.IGNORECASE,
    )
    if not en_match and start_pos > 0:
        en_match = re.search(
            r'<div[^>]*class=["\'][^"\']*pos-details-english[^"\']*["\'][^>]*>(.*?)(?:<div[^>]*class=["\']blank-|<div[^>]*class=["\']pos-details-|<div[^>]*id=["\']position-|<h3|$)',
            html_text[start_pos : start_pos + 30000],
            re.DOTALL | re.IGNORECASE,
        )

    if en_match:
        target_html = en_match.group(1)

    # Extract JSON-LD if present and no specific fragment was targeted
    if not fragment:
        json_ld_matches = re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html_text,
            re.DOTALL | re.IGNORECASE,
        )
        for match in json_ld_matches:
            try:
                data = json.loads(match.group(1), strict=False)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        title = item.get("title") or item.get("Title") or ""
                        company = ""
                        h_org = item.get("hiringOrganization") or item.get("HiringOrganization") or {}
                        if isinstance(h_org, dict):
                            company = h_org.get("name") or h_org.get("Name") or ""
                        desc = item.get("description") or item.get("Description") or ""
                        clean_desc = _clean_html_text(desc)
                        if len(clean_desc) > 80:
                            header = f"Job Title: {title}\nCompany: {company}\n\n" if title else ""
                            return f"{header}{clean_desc}".strip()
            except Exception:
                pass

    # Strip HTML comments and noisy structural elements
    cleaned = re.sub(r"<!--.*?-->", " ", target_html, flags=re.DOTALL)
    cleaned = re.sub(
        r"<(script|style|nav|header|footer|svg|noscript|aside)[^>]*>.*?</\1>",
        " ",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )
    clean_text = _clean_html_text(cleaned)

    # Filter out empty lines, script fragments, and lines composed solely of Khmer script if English text is present
    lines = [l.strip() for l in clean_text.splitlines()]
    meaningful_lines = []
    has_english_content = any(re.search(r"[a-zA-Z]{3,}", l) for l in lines)

    for l in lines:
        if not l or l.startswith("id=") or l.startswith("style=") or l.startswith("<h3") or l.startswith("<ul"):
            continue
        # Filter pure Khmer script lines if English text is present
        if has_english_content and re.search(r"^[\u1780-\u17ff\s\d\.\-•:()]+$", l):
            continue
        meaningful_lines.append(l)

    result = "\n".join(meaningful_lines)

    # Extract Job Title and Company if not explicitly present at the top of result
    if not result.lower().startswith("job title:"):
        job_title = ""
        company = ""

        # 1. Look for fragment anchor link text (e.g. BongThom position title)
        if fragment:
            pos_link = re.search(
                rf'href=["\']#{re.escape(fragment)}["\'][^>]*>(.*?)</a>',
                html_text,
                re.DOTALL | re.IGNORECASE,
            )
            if pos_link:
                job_title = _clean_html_text(pos_link.group(1))

        # 2. Look for <h1> tags
        if not job_title:
            h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html_text, re.DOTALL | re.IGNORECASE)
            if h1_match:
                t_val = _clean_html_text(h1_match.group(1))
                if t_val and len(t_val) < 80:
                    job_title = t_val

        # 3. Look for <title> tag to extract title and company (e.g. "Sales Executive with H O S Trading Co.Ltd.")
        title_tag_match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.DOTALL | re.IGNORECASE)
        if title_tag_match:
            page_title = _clean_html_text(title_tag_match.group(1))
            with_match = re.search(r"(?:with|at|@)\s+([^|\-]+)", page_title, re.IGNORECASE)
            if with_match:
                company = with_match.group(1).strip()
            if not job_title:
                job_title = (
                    page_title.split(" with ")[0]
                    .split(" at ")[0]
                    .split(" - ")[0]
                    .split(" | ")[0]
                    .strip()
                )

        header_lines = []
        if job_title:
            header_lines.append(f"Job Title: {job_title}")
        if company:
            header_lines.append(f"Company: {company}")

        if header_lines:
            result = "\n".join(header_lines) + "\n\n" + result

    if not result or len(result) < 60:
        raise RuntimeError(
            f"Could not extract meaningful job text from URL: {url}. "
            "Please paste the job description text directly."
        )

    return result




# ============================================================================
# Main Router Function
# ============================================================================

def scrape_job_url(url: str) -> str:
    """Scrape job description text from a web URL, routing to specialized extractors when available."""
    parsed = urlparse(url.strip())
    domain = parsed.netloc.lower()
    fragment = parsed.fragment.strip()
    fetch_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    if "linkedin.com" in domain or "facebook.com" in domain:
        raise ValueError(
            "LinkedIn and Facebook require login to view job postings due to anti-scraping protections. "
            "Please copy and paste the job description text directly into the 'Paste text' tab."
        )

    if "camhr.com" in domain:
        return scrape_camhr_job(url)

    if "jobnet.com.kh" in domain:
        return scrape_jobnet_job(url)

    if "jobify.works" in domain or "jobify.com" in domain or "jobify-cambodia" in domain:
        return scrape_jobify_job(url)

    # Generic webpage scraper (BongThom, ATS portals, greenhouse, lever, workday, etc.)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,km;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
    }

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(fetch_url, headers=headers)
            resp.raise_for_status()
            html_text = resp.text
    except Exception as err:
        logger.error("HTTP request failed for URL %s: %s", url, err)
        raise RuntimeError(
            f"Could not load webpage ({err}). "
            "Please check the URL or paste the job description text directly."
        ) from err

    return _extract_generic_html(html_text, url, fragment=fragment)
