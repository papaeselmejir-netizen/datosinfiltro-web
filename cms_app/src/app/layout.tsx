import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DatoSinFiltro CMS",
  description: "Panel de revisión editorial de DatoSinFiltro",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="es"
      className="h-full antialiased"
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
