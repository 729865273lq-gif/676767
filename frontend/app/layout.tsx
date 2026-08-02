import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Trade Axis | 外贸客户开发工作台",
  description: "AI 辅助客户搜索与人工审批外贸开发工作台。",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
