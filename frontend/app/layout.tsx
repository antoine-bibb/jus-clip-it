import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Jus Clip It",
  description: "Automate clip creation with AI-assisted editing",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
