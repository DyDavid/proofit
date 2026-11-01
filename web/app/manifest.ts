import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Proofit",
    short_name: "Proofit",
    description: "Requirement-by-requirement resume matching for first-job seekers",
    start_url: "/",
    display: "standalone",
    background_color: "#FBFBFA",
    theme_color: "#18181B",
    icons: [
      {
        src: "/favicon.ico",
        sizes: "any",
        type: "image/x-icon",
      },
    ],
  };
}

