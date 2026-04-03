export function apiBase(): string {
  const raw = import.meta.env.VITE_API_BASE_URL
  return (typeof raw === 'string' && raw.length > 0
    ? raw
    : 'http://127.0.0.1:8000'
  ).replace(/\/$/, '')
}
