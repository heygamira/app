import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, gamira } from '@/api/gamiraClient';

// Matches the module's own private key (src/api/gamiraClient.js: `TOKEN_KEY`).
const TOKEN_KEY = 'gamira_access_token';

function fetchResponse({ ok = true, status = 200, body = {}, headers = {} } = {}) {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    headers: { get: (name) => headers[name] ?? null },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('gamira.request', () => {
  it('attaches the stored bearer token as an Authorization header', async () => {
    localStorage.setItem(TOKEN_KEY, 'token-abc');
    const fetchMock = vi.fn().mockResolvedValue(fetchResponse({ body: { ok: true } }));
    vi.stubGlobal('fetch', fetchMock);

    await gamira.request('/me');

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers.Authorization).toBe('Bearer token-abc');
  });

  it('omits the Authorization header when no token is stored', async () => {
    const fetchMock = vi.fn().mockResolvedValue(fetchResponse({ body: { ok: true } }));
    vi.stubGlobal('fetch', fetchMock);

    await gamira.request('/me');

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers.Authorization).toBeUndefined();
  });

  it('sets a JSON content type and a stringified body when a body is sent', async () => {
    const fetchMock = vi.fn().mockResolvedValue(fetchResponse({ body: {} }));
    vi.stubGlobal('fetch', fetchMock);

    await gamira.request('/families', { method: 'POST', body: { name: 'Sharma' } });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(init.body).toBe(JSON.stringify({ name: 'Sharma' }));
  });

  it('does not force a content type or a body on a bodyless request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(fetchResponse({ body: {} }));
    vi.stubGlobal('fetch', fetchMock);

    await gamira.request('/me');

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers['Content-Type']).toBeUndefined();
    expect(init.body).toBeUndefined();
  });

  it('returns null for a 204 response instead of parsing a body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(fetchResponse({ status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await gamira.request('/dose-events/1/taken', { method: 'POST' });

    expect(result).toBeNull();
  });

  it('turns a non-OK response into an ApiError built from the error envelope', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      fetchResponse({
        ok: false,
        status: 404,
        body: {
          error: {
            code: 'senior_not_found',
            message: 'No senior with that id.',
            details: { senior_id: 's1' },
            request_id: 'req-42',
          },
        },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const failure = await gamira.request('/seniors/s1').catch((err) => err);

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.status).toBe(404);
    expect(failure.code).toBe('senior_not_found');
    expect(failure.message).toBe('No senior with that id.');
    expect(failure.details).toEqual({ senior_id: 's1' });
    expect(failure.requestId).toBe('req-42');
  });

  it('falls back to a generic code/message when the error envelope omits them', async () => {
    const fetchMock = vi.fn().mockResolvedValue(fetchResponse({ ok: false, status: 500, body: {} }));
    vi.stubGlobal('fetch', fetchMock);

    const failure = await gamira.request('/anything').catch((err) => err);

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.code).toBe('request_failed');
    expect(failure.message).toBe('Request failed (500)');
  });

  it('falls back to the X-Request-Id response header when the envelope has no request id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      fetchResponse({
        ok: false,
        status: 400,
        body: { error: { code: 'bad_request', message: 'Nope' } },
        headers: { 'X-Request-Id': 'header-req-id' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const failure = await gamira.request('/anything').catch((err) => err);

    expect(failure.requestId).toBe('header-req-id');
  });

  it('turns a rejected fetch (network failure) into an ApiError instead of an unhandled rejection', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('offline'));
    vi.stubGlobal('fetch', fetchMock);

    const failure = await gamira.request('/me').catch((err) => err);

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.status).toBe(0);
    expect(failure.code).toBe('network_unavailable');
    expect(failure.details.cause).toContain('offline');
  });
});

describe('ApiError.isAuthError', () => {
  it('is true only for 401 and 403 responses', () => {
    expect(new ApiError({ status: 401, code: 'unauthorized', message: 'x' }).isAuthError).toBe(true);
    expect(new ApiError({ status: 403, code: 'forbidden', message: 'x' }).isAuthError).toBe(true);
  });

  it('is false for every other status', () => {
    expect(new ApiError({ status: 404, code: 'not_found', message: 'x' }).isAuthError).toBe(false);
    expect(new ApiError({ status: 500, code: 'server_error', message: 'x' }).isAuthError).toBe(false);
    expect(new ApiError({ status: 0, code: 'network_unavailable', message: 'x' }).isAuthError).toBe(false);
  });
});
