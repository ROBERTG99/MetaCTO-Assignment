---
paths:
  - "frontend/**"
  - "web/**"
  - "**/*.tsx"
---
# Frontend rules

- TypeScript strict. API types are generated from the backend's OpenAPI schema, never written by hand.
- Data fetching lives in one API layer; components don't call `fetch` directly.
- Every AI-generated value shows that it came from AI, with its confidence and a short "why", so users always know what the model produced.
- Every page handles loading, empty and error states.
- Stable `data-testid` attributes on elements the end-to-end specs use.
- No new UI library without saying why.
