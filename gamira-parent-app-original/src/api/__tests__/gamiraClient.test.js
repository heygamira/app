import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, auth, families } from '@/api/gamiraClient';

const TOKEN_KEY = 'gamira_access_token';

function jsonResponse(body, { ok = true, status = 200 } = {}) {
  return {
    ok,
    status,
    json: async () => body,
    headers: { get: () => null },
  };
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('gamiraClient request()', () => {
  it('attaches the stored bearer token as an Authorization header', async () => {
    localStorage.setItem(TOKEN_KEY, 'my-token');
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'u1' }));
    vi.stubGlobal('fetch', fetchMock);

    await auth.me();

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers.Authorization).toBe('Bearer my-token');
  });

  it('omits the Authorization header when no token is stored', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'u1' }));
    vi.stubGlobal('fetch', fetchMock);

    await auth.me();

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers.Authorization).toBeUndefined();
  });

  it('sets JSON content type when a request has a body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'f1' }));
    vi.stubGlobal('fetch', fetchMock);

    await families.create('The Smiths');

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/families');
    expect(options.headers['Content-Type']).toBe('application/json');
    expect(options.body).toBe(JSON.stringify({ name: 'The Smiths' }));
  });

  it('does not force a content type on a bodyless request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'f1' }));
    vi.stubGlobal('fetch', fetchMock);

    await families.get('f1');

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/families/f1');
    expect(options.headers['Content-Type']).toBeUndefined();
    expect(options.body).toBeUndefined();
  });

  it('returns null for a 204 response without reading a body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      json: vi.fn(),
      headers: { get: () => null },
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await families.get('f1');

    expect(result).toBeNull();
  });

  it('throws an ApiError built from the response payload on a non-OK response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'not_found',
            message: 'Family not found',
            details: { family_id: 'f1' },
            request_id: 'req-123',
          },
        },
        { ok: false, status: 404 }
      )
    );
    vi.stubGlobal('fetch', fetchMock);

    let caught;
    try {
      await families.get('f1');
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect(caught.status).toBe(404);
    expect(caught.code).toBe('not_found');
    expect(caught.message).toBe('Family not found');
    expect(caught.details).toEqual({ family_id: 'f1' });
    expect(caught.requestId).toBe('req-123');
  });

  it('falls back to a generic message and code when the error payload is missing', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(null, { ok: false, status: 500 }));
    vi.stubGlobal('fetch', fetchMock);

    let caught;
    try {
      await families.get('f1');
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect(caught.status).toBe(500);
    expect(caught.code).toBe('request_failed');
    expect(caught.message).toBe('Request failed (500)');
  });

  it('turns a rejected fetch into an ApiError instead of an unhandled rejection', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    vi.stubGlobal('fetch', fetchMock);

    await expect(families.get('f1')).rejects.toBeInstanceOf(ApiError);

    let caught;
    try {
      await families.get('f1');
    } catch (error) {
      caught = error;
    }
    expect(caught.status).toBe(0);
    expect(caught.code).toBe('network_unavailable');
  });
});

describe('ApiError#isAuthError', () => {
  it('is true for a 401 status', () => {
    const error = new ApiError({ status: 401, code: 'unauthorized', message: 'nope' });
    expect(error.isAuthError).toBe(true);
  });

  it('is true for a 403 status', () => {
    const error = new ApiError({ status: 403, code: 'forbidden', message: 'nope' });
    expect(error.isAuthError).toBe(true);
  });

  it('is false for other statuses, including a network failure', () => {
    expect(new ApiError({ status: 404, code: 'not_found', message: 'x' }).isAuthError).toBe(false);
    expect(new ApiError({ status: 500, code: 'server_error', message: 'x' }).isAuthError).toBe(false);
    expect(new ApiError({ status: 0, code: 'network_unavailable', message: 'x' }).isAuthError).toBe(
      false
    );
  });
});
