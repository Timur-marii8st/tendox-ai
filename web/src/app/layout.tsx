import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Tendox — закупки и решения",
  description: "Внутренний пилот виртуального тендерного отдела",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
