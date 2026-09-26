# SYMBIO

**Turning industrial by-products into industrial resources.**

SYMBIO is a mobile-first industrial symbiosis platform: organizations publish
resources they can provide and requirements they need, a common matching engine
discovers and explains feasible exchanges, and connected parties negotiate in a
private, match-scoped channel.

> Work in progress — full documentation lands with the later phases.

```
apps/backend   FastAPI + SQLAlchemy + PostgreSQL (modular monolith)
apps/mobile    React Native + Expo (Android first, iOS compatible)
apps/admin     Admin console
packages/      Shared types, validation schemas, config
docs/          Architecture, database, matching engine, API, deployment
```
