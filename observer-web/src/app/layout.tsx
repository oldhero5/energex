import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Energex Observer",
  description: "Energy derivatives data observer",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full flex flex-col bg-bg text-fg">{children}</body>
    </html>
  );
}
