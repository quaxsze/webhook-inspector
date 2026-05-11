# Webhook Inspector — Design Document

**Date** : 2026-05-11
**Auteur** : Stanislas Plum
**Statut** : Validé — prêt pour planification implémentation

## Contexte & objectif

Side-project SaaS public et gratuit servant de **terrain d'apprentissage DevOps** progressif sur GCP.

Le produit : un **webhook inspector** style Webhook.site. L'utilisateur génère une URL unique, l'utilise comme cible de webhook (Stripe, GitHub, Slack…), et visualise les requêtes reçues en temps réel dans son navigateur.

L'objectif **n'est pas** de concurrencer Webhook.site, mais de fournir un produit suffisamment utile et fréquenté pour générer **du trafic réel, des incidents réels, des questions opérationnelles réelles**.

### Critères de réussite

1. La V1 est en ligne et utilisable en moins de 3 semaines (temps partiel, ~10h/semaine).
2. Au moins 1 incident production est vécu et postmortem dans les 3 premiers mois.
3. Chaque phase (V1 → V7) ajoute **un** apprentissage DevOps majeur, mesurable.
4. Le produit reste *utilisable* à toutes les phases (pas de régression UX).

### Choix structurants

| Décision | Choix | Motivation |
|----------|-------|------------|
| Cloud | GCP | Capitalise sur l'expertise Qantum, transfert immédiat. |
| Backend | Python 3.13 + FastAPI | Stack Qantum, focus 100% DevOps. |
| Frontend | Jinja2 + HTMX (servi par FastAPI) | Pas de toolchain Node. Une seule image à déployer. |
| Auth V1 | Anonyme (token = secret) | Friction zéro, MVP rapide. Auth ajoutée V5. |
| DB | Cloud SQL Postgres 16 | Postgres standard, LISTEN/NOTIFY pour le live V1. |
| Ambition | Side-project public gratuit | Vrais users, vraie surface d'attaque, pas de billing. |

## Scope V1 (MVP)

### Endpoints exposés

1. **`POST /api/endpoints`**
   Crée un endpoint anonyme.
   Génère un token `secrets.token_urlsafe(16)` (≈22 chars).
   Renvoie `{ "url": "https://hook.<domain>/h/<token>", "expires_at": "..." }`.

2. **`ANY /h/{token}`** (servi par le service `ingestor`)
   Accepte GET/POST/PUT/PATCH/DELETE/OPTIONS/HEAD.
   Capture : méthode, path complet (incluant suffixe après le token), query string, headers, body, IP source, timestamp.
   Renvoie `200 OK` avec body `{"ok":true}` (configurable en V2).

3. **`GET /api/endpoints/{token}/requests`**
   Liste paginée (cursor-based, 50/page) des requêtes reçues.

4. **`GET /{token}`**
   Page HTML Jinja2 affichant la liste des requêtes en live (SSE via HTMX).

5. **`GET /stream/{token}`**
   Endpoint Server-Sent Events. Pousse un fragment HTML pour chaque nouvelle requête. Abonné via Postgres LISTEN/NOTIFY côté serveur.

### Hors scope V1

- Auth utilisateur (V5)
- Custom response status/body (V2)
- Forward vers une URL cible (V3)
- Replay d'une requête (V2)
- Rate limiting applicatif (V4)
- API tokens / accès programmatique (V5)
- Statistiques / graphs (V6)
- Multi-région (V7)

### Rétention V1

- **Endpoints** : 7 jours après création (`expires_at = created_at + 7d`).
- **Requêtes** : supprimées avec l'endpoint (`ON DELETE CASCADE`).
- **Bodies > 8KB sur GCS** : lifecycle policy GCS = auto-delete 7 jours après upload.

### Limites bodies (deux seuils distincts)

- **8 KB** : seuil au-delà duquel le body est offloadé vers GCS (au lieu d'être inline dans Postgres `body_preview`).
- **10 MB** : limite max acceptée par l'ingestor. Au-delà, `413 Payload Too Large` renvoyé avant lecture complète.

## Architecture

### Vue d'ensemble

```
                   ┌────────────────────────┐
                   │   Cloudflare (DNS)     │   TLS, DDoS basique
                   └────────────┬───────────┘
                                │
                  ┌─────────────┴─────────────┐
                  │                           │
        hook.<domain>                   app.<domain>
        (ingestion)                     (UI + API + SSE)
                  │                           │
                  ▼                           ▼
        ┌──────────────────┐        ┌──────────────────┐
        │   Cloud Run      │        │   Cloud Run      │
        │   "ingestor"     │        │   "app"          │
        │   FastAPI        │        │   FastAPI+Jinja2 │
        │   min=0, max=20  │        │   min=1, max=5   │
        └────────┬─────────┘        └────────┬─────────┘
                 │                            │
                 │   ┌────────────────────────┤
                 │   │                        │
                 ▼   ▼                        ▼
        ┌──────────────────┐        ┌──────────────────┐
        │   Cloud SQL      │        │   Cloud Storage  │
        │   Postgres 16    │        │   bodies > 8KB   │
        │   (db-f1-micro)  │        │   lifecycle 7d   │
        └──────────────────┘        └──────────────────┘
                 ▲
                 │
        ┌────────┴─────────┐
        │  Cloud Scheduler │
        │  + Cloud Run Job │   cleanup quotidien 3am UTC
        │   "cleaner"      │
        └──────────────────┘
```

### Pourquoi séparer `ingestor` et `app`

- L'ingestor reçoit du trafic adversarial public (n'importe qui peut spammer une URL). On veut le scaler agressivement, le rate-limiter spécifiquement, et **éviter qu'un burst d'ingestion ne fasse tomber l'UI**.
- Deux SLO distincts : ingestion 99.9%, UI 99%.
- Deux budgets de coût, deux pipelines de déploiement, deux jeux de métriques.
- Trade-off : 2 images Docker à maintenir. Acceptable, car même monorepo Python.

### Stack détaillé

- **Python 3.13** + **FastAPI 0.115+**
- **SQLModel** (ORM) + **Alembic** (migrations)
- **uvicorn + gunicorn workers** en prod
- **OpenTelemetry SDK** dès la V1 (auto-instrumentation FastAPI + SQLAlchemy) → Cloud Trace + Cloud Logging
- **Jinja2** + **HTMX** (CDN) + **Tailwind via CDN** pour la V1
- **Pas de Redis V1** — ajouté en V4 pour rate limiting distribué

### Modèle de données

```sql
CREATE TABLE endpoints (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token         TEXT UNIQUE NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at    TIMESTAMPTZ NOT NULL,
    request_count INT NOT NULL DEFAULT 0
);
CREATE INDEX idx_endpoints_expires ON endpoints(expires_at);

CREATE TABLE requests (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    endpoint_id   UUID NOT NULL REFERENCES endpoints(id) ON DELETE CASCADE,
    method        TEXT NOT NULL,
    path          TEXT NOT NULL,
    query_string  TEXT,
    headers       JSONB NOT NULL,
    body_preview  TEXT,
    body_size     INT NOT NULL,
    gcs_key       TEXT,
    source_ip     INET NOT NULL,
    received_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_requests_endpoint_time ON requests(endpoint_id, received_at DESC);
```

### Data flow d'une requête entrante

```
1. ANY /h/{token} arrive sur ingestor
2. ingestor lookup token en Postgres (index unique)
   ├─ inconnu → 404, pas de DB write (anti-abuse)
   └─ OK → continue
3. capture method, headers, query, body, IP
4. si body > 8KB : upload GCS (clé = {endpoint_id}/{request_id}), stocke gcs_key
5. INSERT requests + UPDATE endpoints.request_count (transaction atomique)
6. NOTIFY new_request '<endpoint_id>:<request_id>' (Postgres LISTEN/NOTIFY)
7. renvoie 200 {"ok":true} (< 100ms p95 cible)

En parallèle, côté app :
A. SSE stream actif pour {token} écoute Postgres NOTIFY
B. à chaque NOTIFY matchant son endpoint_id, SELECT requests WHERE id = ...
C. rend un fragment HTML Jinja2 et le pousse en SSE
D. HTMX insère le fragment en haut de la liste, sans reload
```

### Le service `cleaner`

- Cloud Run **Job** (pas Service), invoqué par Cloud Scheduler à 03:00 UTC.
- Logique : `DELETE FROM endpoints WHERE expires_at < NOW()`. Cascade vers requests. GCS gère sa propre lifecycle.
- **Idempotent** : peut tourner 2× sans casser.
- Alerte si 3 échecs consécutifs (V2+).

## Roadmap progressive

Chaque phase ajoute **un** apprentissage DevOps majeur, pas dix.

| Phase | Feature produit | Apprentissage DevOps cible |
|-------|-----------------|----------------------------|
| **V1** | MVP (5 endpoints : 3 API + viewer HTML + SSE stream) | Cloud Run, Cloud SQL, Terraform basics, GitHub Actions, domaine + TLS, OTEL auto-instrumentation |
| **V2** | Custom response (status/body) + replay | Secrets Manager avancé, **métriques OTEL custom** + dashboards Cloud Monitoring + alerting policies |
| **V3** | Forward vers une URL cible | Pub/Sub, worker async, dead-letter queue, retry exponentiel, idempotency |
| **V4** | Rate limiting + abuse protection | Cloudflare WAF, IP reputation, Memorystore Redis (partagé entre instances ingestor), alerting Discord/PagerDuty |
| **V5** | Auth Google OAuth + URLs claimées + historique long | OAuth flow, IAM, multi-tenant data, RGPD retention |
| **V6** | SLO formels + error budgets + status page publique | Pratiques SRE, SLI definition, postmortems blameless |
| **V7+** | Multi-région, blue/green deploys, chaos engineering | Cloud Load Balancer, traffic splitting, fault injection |

## Infrastructure V1

### Ressources Terraform (un seul module au début)

- Cloud Run service `ingestor` (min=0, max=20, mémoire 512MB)
- Cloud Run service `app` (min=1, max=5, mémoire 512MB)
- Cloud Run Job `cleaner` (mémoire 256MB)
- Cloud SQL instance `db-f1-micro`, Postgres 16, single zone (pas de HA V1)
- Cloud Scheduler (cron `0 3 * * *`)
- GCS bucket avec lifecycle policy `Age > 7 days → DELETE`
- Secret Manager pour `DATABASE_URL`
- IAM bindings minimaux par service (principle of least privilege dès V1)

### CI/CD

GitHub Actions, **3 workflows** :

1. `lint-and-test.yml` sur PR : ruff + mypy + pytest unit + integration. Cible < 5 min.
2. `deploy-dev.yml` sur push `develop` : build image, push Artifact Registry, deploy Cloud Run dev.
3. `deploy-prod.yml` sur push `main` : idem mais env prod, avec approval manuel.

**Workload Identity Federation** (pas de clé de service JSON dans GitHub Secrets).

### Environnements

- `dev` : sandbox GCP perso, tout petit.
- `prod` : domaine public.
- **Pas de staging V1** — ajouté quand le besoin se manifestera.

### Observabilité minimale V1

- OpenTelemetry auto-instrumentation FastAPI + SQLAlchemy.
- Logs structurés JSON via `structlog`.
- Export vers Cloud Logging + Cloud Trace (natifs GCP).
- Pas de dashboards custom V1 — Cloud Run en fournit suffisamment par défaut.

### DNS / TLS

- Domaine perso (à acheter, ~10€/an).
- Cloudflare en proxy : TLS automatique, DDoS L3/L4 gratuit, cache statique. **Pas de règles WAF custom V1** (ajoutées en V4).
- Deux sous-domaines : `hook.<domain>` (ingestor), `app.<domain>` (UI).

## Error handling & dégradation

| Scénario | Comportement V1 | Apprentissage cible |
|----------|-----------------|---------------------|
| Postgres down | Ingestor → `503`. Pas de buffer. | Comprendre la perte → V3 ajoute Pub/Sub buffer. |
| Body > 10 MB | `413 Payload Too Large` avant lecture complète. | Cost control. |
| Token inexistant | `404`, pas de DB write. | Anti-abuse basique. |
| GCS upload fail | Best-effort : on stocke `body_preview` quand même, log l'erreur, renvoie 200. | Dégradation gracieuse. |
| SSE drop | HTMX reconnect auto. Fallback polling 5s après 3 échecs. | Limites des connexions longues. |
| Cleaner échoue | Retry par Scheduler le lendemain. Alerte si 3 échecs consécutifs. | Idempotency cron jobs. |

**Principe directeur V1** : favoriser la disponibilité de l'ingestion sur la cohérence parfaite. Mieux vaut un webhook capturé sans body que pas de webhook du tout.

## Stratégie de test

### Trois niveaux, pas plus

1. **Unit (pytest)** — logique domaine pure : token generation, header parsing, body size logic. Rapides, nombreux.
2. **Integration (pytest + testcontainers Postgres)** — repositories + schema. Pas de mock DB, vraie Postgres en container.
3. **E2E (1-2 max V1)** — script qui crée un endpoint, envoie 3 webhooks, vérifie via l'API. Run en CI après deploy `dev`.

### Hors scope V1

- Tests UI Playwright/Vitest browser — trop coûteux pour le ROI tant que l'UI fait 2 pages.
- Tests de charge — V4 quand on aura ajouté le rate limiting.

### Contraintes CI

CI complète en < 5 min, sinon évitement.

## Sécurité V1 — niveau honnête

**Ce qui est en place** :
- HTTPS partout (Cloudflare).
- Secrets dans Secret Manager, jamais en clair.
- IAM minimal par service (Workload Identity).
- Token endpoint = 16 bytes urlsafe = 128 bits d'entropie → non-devinable.
- Limite body 10 MB côté ingestor.

**Ce qui n'est PAS en place V1** (assumé) :
- Pas de rate limiting applicatif → tu vas te faire abuser → V4.
- Pas de scanning des bodies (malware, PII) → ajouté en V5 avec auth.
- Pas de WAF custom → V4.

**Principe** : la surface d'attaque exposée fait *partie* de l'apprentissage. On veut vivre l'incident, pas l'éviter prématurément.

## Décisions architecturales clés (ADR-light)

### ADR-001 : Deux services Cloud Run (ingestor + app) dès V1

**Décision** : séparer l'ingestion publique adversariale de l'UI/API utilisateur.
**Pourquoi** : SLO distincts, scaling indépendant, isolation des incidents.
**Alternative rejetée** : un seul service. Plus simple mais empêche l'apprentissage du scaling différencié.

### ADR-002 : Postgres LISTEN/NOTIFY plutôt que Pub/Sub V1

**Décision** : utiliser LISTEN/NOTIFY pour le live SSE en V1.
**Pourquoi** : zéro infra additionnelle, pattern qui scale jusqu'à plusieurs milliers de connexions.
**Alternative rejetée** : Pub/Sub dès V1. Pédagogiquement intéressant mais YAGNI — Pub/Sub arrive en V3 avec le forward async.

### ADR-003 : Jinja2 + HTMX plutôt que Next.js

**Décision** : pas de SPA, pas de Node, un seul service `app` qui sert HTML + API + SSE.
**Pourquoi** : focus 100% backend/infra, pas de toolchain frontend à entretenir.
**Alternative rejetée** : Next.js sur Cloudflare Pages. Plus moderne mais coût cognitif disproportionné pour la V1.

### ADR-004 : Pas de HA Postgres en V1

**Décision** : `db-f1-micro` single-zone.
**Pourquoi** : side-project, coût minimal, downtime acceptable.
**Alternative rejetée** : HA dès V1. Coût ×3, complexité inutile avant qu'on ait des users.

### ADR-005 : Anonyme en V1, auth en V5

**Décision** : pas d'auth utilisateur initiale, URL = secret.
**Pourquoi** : modèle qui marche (Webhook.site), MVP rapide, friction zéro.
**Alternative rejetée** : OAuth dès V1. Bonne pratique multi-tenant mais ralentit l'arrivée des premiers users.

## Risques identifiés & mitigation

| Risque | Probabilité | Impact | Mitigation V1 |
|--------|-------------|--------|---------------|
| Abuse/spam dès la mise en ligne | Haute | Coût Cloud Run | Body limit 10 MB, monitoring coûts GCP avec alerte budget. |
| Cold start ingestor > 2s | Haute | UX webhooks ratés | Accepté V1. Mesuré via OTEL. Min=1 si bloquant. |
| Postgres connection pool épuisé | Moyenne | 503 généralisés | Pgbouncer (V2) ou Cloud SQL Auth Proxy avec pooling. |
| Coût explose à cause d'un attaque | Moyenne | Carte bleue qui pleure | Budget alert GCP à 20€/mois. Hard cap à 50€. |
| Fuite token endpoint via logs | Moyenne | URL utilisable par un tiers | Token = path, pas de logging des paths complets en Cloud Logging par défaut. |

## Prochaines étapes

1. Acheter le domaine.
2. Setup compte GCP perso + facturation avec budget alert.
3. Repo GitHub initialisé.
4. Plan d'implémentation V1 détaillé (cf. invocation skill `writing-plans` post-validation de ce spec).

---

*Document validé via le workflow `superpowers:brainstorming` le 2026-05-11.*
