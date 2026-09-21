import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Quant OS — Autonomous Trading Command",
  description: "Autonomous quant research, risk, execution, and shadow trading command center."
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
