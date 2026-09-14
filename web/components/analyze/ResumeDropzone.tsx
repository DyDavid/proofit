"use client";

import { useTranslations } from "next-intl";
import * as React from "react";

import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

const ACCEPTED_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];
const MAX_BYTES = 5 * 1024 * 1024;

export interface ResumeDropzoneProps {
  file: File | null;
  onChange: (file: File | null) => void;
}

function formatSize(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Client-side-only validation (PERSON_B_PLAN_v2.md §5 Phase 1 task 5): type
 * and size are checked here before anything is sent anywhere, since there is
 * no upload endpoint yet in Phase 1 skeleton scope.
 */
export function ResumeDropzone({ file, onChange }: ResumeDropzoneProps) {
  const t = useTranslations("analyze.resume");
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [isDragOver, setIsDragOver] = React.useState(false);

  function validateAndSet(candidate: File | undefined | null) {
    if (!candidate) return;
    if (!ACCEPTED_TYPES.includes(candidate.type)) {
      setError(t("errorType"));
      return;
    }
    if (candidate.size > MAX_BYTES) {
      setError(t("errorSize"));
      return;
    }
    setError(null);
    onChange(candidate);
  }

  if (file) {
    return (
      <div className="flex items-center gap-3.5 border border-rule bg-paper p-3.5">
        <div className="relative flex h-12 w-10 shrink-0 items-center justify-center border border-ink bg-surface-raised">
          <span className="absolute bottom-1 left-0 right-0 text-center font-mono text-[9px] tracking-wide text-ink">
            {file.name.split(".").pop()?.toUpperCase()}
          </span>
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-ink">{file.name}</p>
          <p className="font-mono text-xs text-ink-3">{formatSize(file.size)}</p>
        </div>
        <Button variant="ghost" size="sm" type="button" onClick={() => onChange(null)}>
          {t("replace")}
        </Button>
      </div>
    );
  }

  return (
    <div className="grid gap-2">
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragOver(false);
          validateAndSet(e.dataTransfer.files[0]);
        }}
        aria-label={t("dropzone")}
        className={cn(
          "flex min-h-[220px] cursor-pointer flex-col items-center justify-center gap-2.5 border-[1.5px] border-dashed border-ink-3 bg-paper p-6 text-center transition-colors",
          isDragOver && "border-ink bg-paper-2",
        )}
      >
        <svg
          aria-hidden="true"
          width="30"
          height="30"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-ink-2"
        >
          <path d="M12 16V4m0 0-4 4m4-4 4 4" />
          <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
        </svg>
        <p className="font-medium text-ink">{t("dropzone")}</p>
        <p className="font-mono text-xs text-ink-3">{t("dropzoneHint")}</p>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_TYPES.join(",")}
          className="sr-only"
          onChange={(e) => validateAndSet(e.target.files?.[0])}
          aria-hidden="true"
          tabIndex={-1}
        />
      </div>
      {error ? (
        <p role="alert" className="text-sm text-missing">
          {error}
        </p>
      ) : null}
    </div>
  );
}
