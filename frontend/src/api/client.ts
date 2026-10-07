// Typed API client. Paths and bodies come from the generated OpenAPI types (npm run gen:api), so a contract
// change in the backend is a compile error here. Every call goes through /api, which Vite forwards to the API.
import createClient from 'openapi-fetch'

import type { components, paths } from './schema'

export type Schemas = components['schemas']
export const api = createClient<paths>({ baseUrl: '/api' })

/** The backend's single error shape (backend/app/errors.py). */
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

type Result<T> = { data?: T; error?: unknown; response: Response }

/** Return the data or throw an ApiError, so TanStack Query sees failures as errors. */
export function unwrap<T>({ data, error, response }: Result<T>): T {
  if (error !== undefined || data === undefined) {
    const info = (error as { error?: { code?: string; message?: string } } | undefined)?.error
    throw new ApiError(response.status, info?.code ?? 'unknown', info?.message ?? response.statusText)
  }
  return data
}
