import "./globals.css";

export const metadata = {
  title: "AI-HAS Helpdesk",
  description: "AI-Powered Enterprise Helpdesk & Workflow Automation System",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}