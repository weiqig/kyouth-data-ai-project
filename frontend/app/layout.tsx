import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Audit-Ready Document Pipeline',
  description: 'PostgreSQL state-driven AI document processing prototype',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="topNav">
          <a className="brandLink" href="/">Audit Pipeline</a>
          <nav>
            <a href="/records">Database Records</a>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
