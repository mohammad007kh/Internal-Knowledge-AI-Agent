/**
 * Minimal write-once store so that api-client.ts can read the access token
 * without importing React context.
 * AuthProvider calls setToken() whenever the token changes.
 * apiClient calls getToken() in its request interceptor.
 */
let _token: string | null = null

export function setToken(t: string | null): void {
  _token = t
}

export function getToken(): string | null {
  return _token
}
