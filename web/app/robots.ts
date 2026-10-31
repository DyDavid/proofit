import type { MetadataRoute } from "next";
import { getSiteUrl } from "@/lib/seo";

export default function robots(): MetadataRoute.Robots {
  const siteUrl = getSiteUrl();

  return {
    rules: {
      userAgent: "*",
      allow: ["/", "/pricing"],
      disallow: [
        "/dashboard",
        "/account",
        "/auth",
        "/api",
        "/billing",
        "/progress",
        "/results",
      ],
    },
    sitemap: `${siteUrl}/sitemap.xml`,
  };
}

