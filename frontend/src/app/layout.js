import "./globals.css";

export const metadata = {
  title: "AI-HAS Helpdesk",
  description: "AI-Powered Enterprise Helpdesk & Workflow Automation System",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: `
          try {
            if (localStorage.getItem("aihas_theme") === "light") {
              document.documentElement.dataset.theme = "light";
            }
          } catch {}
        ` }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
