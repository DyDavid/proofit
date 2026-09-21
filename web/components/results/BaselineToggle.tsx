"use client";

import { useTranslations } from "@/lib/copy";

import { Button } from "@/components/ui/Button";

export interface BaselineToggleProps {
  shown: boolean;
  onToggle: () => void;
}

export function BaselineToggle({ shown, onToggle }: BaselineToggleProps) {
  const t = useTranslations("results");
  return (
    <Button
      type="button"
      variant={shown ? "secondary" : "ghost"}
      size="sm"
      onClick={onToggle}
      aria-pressed={shown}
    >
      {t("baseline.toggle")}
    </Button>
  );
}
