/** API error type and user-facing messages (no auth dependencies, safe to import anywhere). */

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : 'Request failed');
    this.status = status;
    this.detail = detail;
  }
}

/** Human-friendly message for an error from this client. */
export function errorMessage(err) {
  if (!(err instanceof ApiError)) return err?.message || 'Something went wrong.';
  if (err.status === 401) return 'Your session expired. Please sign in again.';
  if (err.status === 403) return err.message || "You don't have permission to do that.";
  if (err.status === 404) return err.message || 'Not found.';
  if (Array.isArray(err.detail)) return err.detail.map(d => d.msg).join('; ');
  return err.message;
}
