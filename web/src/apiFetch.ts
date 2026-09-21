// The token is scoped to one workbench process and stays in page memory.
// A different website cannot read /api/session or send this header without
// passing the browser's same-origin checks. This is not an OS-user boundary.
let sessionPromise: Promise<string> | null = null

async function browserSession(): Promise<string> {
  if (!sessionPromise) {
    sessionPromise = fetch('/api/session', { cache: 'no-store', credentials: 'same-origin' })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Workbench session unavailable (${response.status})`)
        const payload = await response.json()
        if (payload?.status !== 'ok' || typeof payload.token !== 'string' || !payload.token) {
          throw new Error('Workbench session response is invalid')
        }
        return payload.token as string
      })
      .catch((error) => { sessionPromise = null; throw error })
  }
  return sessionPromise
}

export async function apiFetch(input: RequestInfo | URL, init: RequestInit): Promise<Response> {
  const headers = new Headers(init.headers)
  headers.set('X-ArchScope-Session', await browserSession())
  return fetch(input, { ...init, headers, credentials: 'same-origin' })
}
