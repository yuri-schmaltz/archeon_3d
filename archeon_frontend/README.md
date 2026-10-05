# Archeon 3D — Frontend

React 19, TypeScript 5.9, Vite 7 and Tailwind CSS 4 UI for the
[Archeon API](../ARCHEON_README.md). The gallery uses one authenticated SSE
connection per tab, reconnects after interruptions and polls while SSE is
unavailable. System metrics are refreshed separately.

## Setup

Requires Node.js 22.12+ and a running backend.

```bash
npm ci
cp .env.example .env
npm run dev
```

Open http://localhost:5173. The development API defaults to
http://localhost:8081. Set `VITE_API_URL` to the backend base URL, without `/v1`.
If unset in a production build, or explicitly empty, requests use the same
origin as the UI. The Docker nginx proxy provides `/v1`, `/health`, `/docs`,
`/openapi.json` and `/files`.

If `ARCHEON_API_KEY` is configured on the backend, enter the key in the
connection screen. It stays in memory for that page session and is passed in
`X-API-Key` headers for HTTP and SSE. Reloading requires entering it again.
There is no frontend environment variable for secrets.

## Scripts

| Command | Purpose |
| --- | --- |
| `npm run dev` | Development server with HMR |
| `npm run build` | TypeScript checks and production bundle in `dist/` |
| `npm run preview` | Local preview of the production build |
| `npm run lint` | ESLint |
| `npm run test` | Vitest request serialization tests |

## Organization

- `src/api/client.ts`: base URL, authenticated HTTP client and API error messages.
- `src/api/generation.ts`: validation and serialization of the selected generation mode.
- `src/api/useJobFeed.ts`: shared authenticated SSE, reconnection and fallback polling.
- `src/context/JobContext.tsx`: shared gallery state and recent status transitions.
- `src/components/jobs/`: creation form, gallery and model preview.
- `src/components/common/ApiAccessGate.tsx`: connection and runtime authentication.
- `src/design/`: tokens, focus styles and reusable primitives.

Form drafts are separate for each mode; only the selected mode is submitted.
Image uploads are limited to 10 MiB each and GLB uploads to 30 MiB. These UI
limits keep the current base64 requests below nginx's 64 MiB body limit.
Server-side payload limits and multipart uploads remain future work.

Use `apiClient` for HTTP actions and `useJobFeed` for streams. Label inputs,
keep keyboard navigation for mode tabs and distinguish job failures from
connection failures. The gallery's Refresh action forces a HTTP read even
while SSE is connected.
