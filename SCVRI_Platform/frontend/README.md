# SCVRI Frontend (Next.js App Router)

Enterprise frontend architecture with feature modules:

- `src/app` - route composition and global providers
- `src/modules` - dashboard, supply-chain-map, suppliers, risk-intelligence, alerts, reports, integrations, admin
- `src/design-system` - reusable UI primitives and semantic badges
- `src/services` - typed service clients
- `src/store` - Zustand global UI/RBAC state

## Run

```bash
npm install
npm run dev
```

## Notes

- React Query is configured with retry and caching defaults.
- Charts are lazy-loaded using dynamic suspense wrappers.
- Sidebar visibility is role-based.
- Supply chain map requires `NEXT_PUBLIC_MAPBOX_TOKEN`.
