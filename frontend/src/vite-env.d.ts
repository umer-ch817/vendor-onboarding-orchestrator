/// <reference types="vite/client" />

// Without this reference, `import.meta.env` has no type and src/utils/api.ts
// fails to compile with "Property 'env' does not exist on type 'ImportMeta'".
// Vite's dev server does not typecheck, so the error only surfaces in
// `npm run build` (tsc && vite build).
