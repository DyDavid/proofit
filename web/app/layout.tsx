import type { ReactNode } from "react";

type Props = {
  children: ReactNode;
};

/**
 * Pass-through root layout.
 *
 * Every Proofit route lives under `app/[locale]`, and that layout is the one
 * that renders `<html>` and `<body>` (it needs the resolved locale for
 * `lang={locale}`). Next.js still requires a file at `app/layout.tsx`, so this
 * one only forwards children — rendering `<html>` here as well would nest two
 * documents inside each other.
 *
 * @see https://next-intl.dev/docs/environments/error-files
 */
export default function RootLayout({ children }: Props) {
  return children;
}
