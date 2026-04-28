import { useQuery } from '@tanstack/react-query';
import Navbar from '@/components/layout/Navbar';
import Footer from '@/components/layout/Footer';
import { fetchQualityStatus } from '@/api/client';

export default function Quality() {
  const qualityQuery = useQuery({
    queryKey: ['quality-status'],
    queryFn: fetchQualityStatus,
    staleTime: 30_000,
  });

  const status = qualityQuery.data;

  return (
    <div className="min-h-screen flex flex-col">
      <Navbar />
      <main className="flex-1 container mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-3xl font-bold mb-2">Quality Dashboard</h1>
        <p className="text-muted-foreground mb-6">
          Latest CI/test signal for backend and frontend quality gates.
        </p>

        {qualityQuery.isLoading && <p className="text-sm text-muted-foreground">Loading status...</p>}
        {qualityQuery.isError && (
          <p className="text-sm text-destructive">
            Could not load quality status. Run CI or generate local status output.
          </p>
        )}

        {status && (
          <div className="space-y-4">
            <div className="rounded-xl border border-border bg-card p-4">
              <p className="text-sm text-muted-foreground">Overall status</p>
              <p className="text-2xl font-semibold mt-1">{status.status}</p>
            </div>

            <div className="grid sm:grid-cols-2 gap-4">
              <div className="rounded-xl border border-border bg-card p-4">
                <p className="text-sm text-muted-foreground">Backend coverage</p>
                <p className="text-xl font-semibold mt-1">
                  {status.backendCoveragePct == null ? 'n/a' : `${status.backendCoveragePct}%`}
                </p>
              </div>
              <div className="rounded-xl border border-border bg-card p-4">
                <p className="text-sm text-muted-foreground">Frontend coverage</p>
                <p className="text-xl font-semibold mt-1">
                  {status.frontendCoveragePct == null ? 'n/a' : `${status.frontendCoveragePct}%`}
                </p>
              </div>
            </div>

            <div className="rounded-xl border border-border bg-card p-4">
              <p className="text-sm text-muted-foreground mb-2">Failing tests</p>
              {status.failingTests.length === 0 ? (
                <p className="text-sm">None reported.</p>
              ) : (
                <ul className="text-sm list-disc pl-5 space-y-1">
                  {status.failingTests.map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                </ul>
              )}
            </div>

            <div className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
              <p>Build SHA: {status.sha || 'unknown'}</p>
              <p>Generated at: {status.generatedAt || 'unknown'}</p>
              <p>Source: {status.source || 'quality-status.json'}</p>
            </div>
          </div>
        )}
      </main>
      <Footer />
    </div>
  );
}
