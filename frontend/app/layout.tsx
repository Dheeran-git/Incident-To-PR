import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Incident-to-PR | Incident Control Room",
  description: "Policy-governed, reviewable incident remediation for cloud-native services.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
