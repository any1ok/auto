import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AutoSend",
  description: "카카오톡 자동 발송 보조 앱 관리 웹"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}

