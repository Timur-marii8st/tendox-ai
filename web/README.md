# S3 internal pilot UI

Next.js App Router renders saved procurement cases and calls FastAPI only from
server modules. The bearer token must stay in `PROCUREMENT_API_TOKEN`; never
rename it to a `NEXT_PUBLIC_*` variable.

```powershell
$env:PROCUREMENT_API_URL = "http://127.0.0.1:8000"
$env:PROCUREMENT_API_TOKEN = "<local bearer secret>"
$env:PROCUREMENT_DEMO_MODE = "true"
npm install
npm run dev
```

Quality checks:

```powershell
npm run lint
npm run build
```

The pilot has one server-configured tenant and no user sessions. See
`../docs/18-first-screen.md` for the complete boundary.
