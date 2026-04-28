import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fetchProviders, fetchQualityStatus, setApiAccessTokenGetter } from './client';

describe('api client Authorization', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    setApiAccessTokenGetter(null);
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    setApiAccessTokenGetter(null);
  });

  it('does not set Authorization when no token getter', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    globalThis.fetch = fetchMock;
    await fetchProviders();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const h = init.headers as Record<string, string>;
    expect(h.Authorization ?? (h as unknown as Headers).get?.('Authorization')).toBeFalsy();
  });

  it('sets Authorization Bearer when token getter returns a token', async () => {
    setApiAccessTokenGetter(async () => 'test-access-token');
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );
    globalThis.fetch = fetchMock;
    await fetchProviders();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer test-access-token');
  });

  it('falls back to static quality JSON when /api/quality is unavailable', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response('not found', { status: 404 }))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            status: 'passed',
            backendCoveragePct: 80,
            frontendCoveragePct: 78,
            failingTests: [],
            sha: 'abc123',
            generatedAt: '2026-04-28T00:00:00Z',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      );

    globalThis.fetch = fetchMock;
    const data = await fetchQualityStatus();
    expect(data.status).toBe('passed');
    expect(fetchMock.mock.calls[0][0]).toContain('/api/quality');
    expect(fetchMock.mock.calls[1][0]).toContain('/quality-status.json');
  });
});
