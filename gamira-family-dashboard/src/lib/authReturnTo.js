// Post-auth destination taken from the `returnTo` query param.
//
// Only same-origin *paths* are allowed: anything absolute, protocol-relative
// ("//evil.com"), or backslash-prefixed would let a crafted login link bounce a
// freshly authenticated user off-site, so those fall back to "/".
export function safeReturnTo(defaultPath = '/') {
  if (typeof window === 'undefined') return defaultPath;
  try {
    const raw = new URLSearchParams(window.location.search).get('returnTo');
    if (!raw) return defaultPath;
    const decoded = decodeURIComponent(raw);
    if (!decoded.startsWith('/')) return defaultPath;
    if (decoded.startsWith('//') || decoded.startsWith('/\\')) return defaultPath;
    // Reject anything that still parses as an absolute URL.
    if (/^[a-z][a-z0-9+.-]*:/i.test(decoded)) return defaultPath;
    return decoded;
  } catch {
    return defaultPath;
  }
}

export default safeReturnTo;
