import { ImageResponse } from "next/og";

export const alt =
  "Proofit — Prove your fit. AI resume-to-job-description matching for first-job seekers.";
export const size = {
  width: 1200,
  height: 630,
};
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          backgroundColor: "#f3f0e8",
          color: "#141412",
          padding: "64px 72px",
          fontFamily: "sans-serif",
          border: "12px solid #2b36e8",
        }}
      >
        {/* Top bar */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            width: "100%",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "14px",
            }}
          >
            <div
              style={{
                width: "18px",
                height: "18px",
                borderRadius: "9999px",
                backgroundColor: "#2b36e8",
              }}
            />
            <span
              style={{
                fontSize: "28px",
                fontWeight: 800,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "#141412",
              }}
            >
              Proofit
            </span>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              backgroundColor: "#e4e6fc",
              color: "#2b36e8",
              padding: "8px 20px",
              borderRadius: "9999px",
              fontSize: "18px",
              fontWeight: 700,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
          >
            Resume × Job Description
          </div>
        </div>

        {/* Center headline + value proposition */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "24px",
            maxWidth: "980px",
          }}
        >
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              fontSize: "82px",
              fontWeight: 900,
              lineHeight: 0.96,
              letterSpacing: "-0.03em",
              textTransform: "uppercase",
              color: "#141412",
            }}
          >
            <span>Your coursework &amp;</span>
            <span style={{ color: "#2b36e8" }}>projects are experience.</span>
          </div>

          <p
            style={{
              margin: 0,
              fontSize: "30px",
              lineHeight: 1.4,
              color: "#55524a",
              maxWidth: "900px",
            }}
          >
            Requirement-by-requirement resume matching that finds the proof in
            your classes, capstones, and part-time work.
          </p>
        </div>

        {/* Footer */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            width: "100%",
            borderTop: "2px solid #d9d4c8",
            paddingTop: "24px",
            fontSize: "20px",
            color: "#6d695f",
          }}
        >
          <span>Prove your fit · Built for first-job seekers</span>
          <span style={{ color: "#2b36e8", fontWeight: 700 }}>
            Proven · Partial · Missing
          </span>
        </div>
      </div>
    ),
    {
      ...size,
    },
  );
}

