"""Phase 5 SEO Basics verification tests."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = REPO_ROOT / "web" / "app"


def test_sitemap_exists_and_includes_public_routes_only() -> None:
    sitemap_path = WEB_APP / "sitemap.ts"
    assert sitemap_path.exists()
    content = sitemap_path.read_text(encoding="utf-8")
    assert "getSiteUrl" in content
    assert "${siteUrl}/" in content
    assert "${siteUrl}/pricing" in content
    for private_route in ("/dashboard", "/account", "/auth", "/billing"):
        assert private_route not in content


def test_robots_exists_and_disallows_private_routes() -> None:
    robots_path = WEB_APP / "robots.ts"
    assert robots_path.exists()
    content = robots_path.read_text(encoding="utf-8")
    assert 'allow: ["/", "/pricing"]' in content
    for disallowed in ("/dashboard", "/account", "/auth", "/api"):
        assert f'"{disallowed}"' in content
    assert "/sitemap.xml" in content


def test_opengraph_image_exists() -> None:
    og_path = WEB_APP / "opengraph-image.tsx"
    assert og_path.exists()
    content = og_path.read_text(encoding="utf-8")
    assert "ImageResponse" in content
    assert "width: 1200" in content
    assert "height: 630" in content
    assert "Proofit" in content


def test_root_layout_sets_metadata_base_and_social_defaults() -> None:
    layout_path = WEB_APP / "layout.tsx"
    content = layout_path.read_text(encoding="utf-8")
    assert "metadataBase" in content
    assert "openGraph" in content
    assert "twitter" in content
    assert 'lang="en"' in content


def test_landing_page_includes_json_ld_software_application_and_single_h1() -> None:
    landing_path = WEB_APP / "page.tsx"
    content = landing_path.read_text(encoding="utf-8")
    assert "application/ld+json" in content
    assert '"@type": "SoftwareApplication"' in content
    assert 'price: "0"' in content
    assert 'priceCurrency: "USD"' in content
    assert content.count("<h1") == 1


def test_private_pages_specify_noindex() -> None:
    private_files = [
        WEB_APP / "dashboard" / "page.tsx",
        WEB_APP / "account" / "page.tsx",
        WEB_APP / "results" / "page.tsx",
        WEB_APP / "progress" / "page.tsx",
        WEB_APP / "analyze" / "page.tsx",
        WEB_APP / "billing" / "layout.tsx",
        WEB_APP / "billing" / "cancel" / "page.tsx",
        WEB_APP / "(auth)" / "layout.tsx",
    ]
    for path in private_files:
        assert path.exists(), f"Missing file: {path}"
        content = path.read_text(encoding="utf-8")
        assert "index: false" in content, f"Missing noindex in {path}"
