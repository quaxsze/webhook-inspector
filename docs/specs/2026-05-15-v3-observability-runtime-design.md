# V3 — Webhook observability runtime (design)

> Spec produit + technique pour V3, qui transforme webhook-inspector de "capture + view" en "**observability layer for webhooks**". Aligne sur le pivot stratégique défini dans `docs/launch/2026-05-15-launch-plan.md`.

## Sommaire

- [Objectifs](#objectifs)
- [Non-objectifs](#non-objectifs)
- [Features](#features)
  - [F1. HMAC signature validation built-in](#f1-hmac-signature-validation-built-in)
  - [F2. Replay](#f2-replay)
  - [F3. Per-integration view (grouping)](#f3-per-integration-view-grouping)
  - [F4. Schema inference + diff](#f4-schema-inference--diff)
  - [F5. Forward avec retry + DLQ](#f5-forward-avec-retry--dlq)
  - [F6. Transform (JSONata)](#f6-transform-jsonata)
  - [F7. OTEL timeline view](#f7-otel-timeline-view)
- [Modèle de données](#modèle-de-données)
- [Surface API](#surface-api)
- [Sécurité & secrets](#sécurité--secrets)
- [Ordre de livraison](#ordre-de-livraison)
- [Out of scope (V3.5 / V4)](#out-of-scope-v35--v4)

---

## Objectifs

V3 doit rendre crédible le pitch **"the free observability layer for webhooks"**. À la fin de V3 un dev doit pouvoir :

1. Capturer un webhook Stripe sur une URL du domaine principal et **voir immédiatement** si la signature HMAC est valide
2. **Re-fire** la même requête contre son `localhost:3000` pour débugger
3. Voir un dashboard par intégration (Stripe = 47 requests, p95=120ms, 2 erreurs signature)
4. Détecter qu'un nouveau champ `metadata.legacy_id` apparaît dans les payloads
5. Configurer un **forward** automatique vers son endpoint prod avec retry exponential
6. **Transformer** le payload (renommer un champ, filtrer un sous-objet) avant forward
7. Voir la **timeline OTEL** d'une requête : capture → HMAC check → DB write → R2 offload → forward → response

V3 prépare aussi le passage du free tier à un Pro tier monétisable : les features 5, 6, 7 sont premium, les features 1-4 restent gratuites pour le funnel viral.

## Non-objectifs

Pas dans V3 :

- **Auth / accounts** : V5 territory, voir launch plan. Tout reste anonymous-token-based pour V3.
- **Multi-target fan-out** : V3 forward = 1 URL cible max. Multi-targets en V4.
- **Webhook replay batch** (rejouer 100 requests d'un coup) : V3.5.
- **Custom integrations** au-delà des 9 services HMAC built-in : V3.5+.
- **Web UI rebuild complet** : on étend l'UI existant, pas un refactor majeur.
- **Self-hosted multi-tenant** : V3 reste single-tenant, tous les endpoints partagent l'instance.
- **Métriques custom OTEL utilisateur** : on expose les nôtres, pas une UI de query builder.

---

## Features

### F1. HMAC signature validation built-in

#### User story

> En tant que dev qui débug un webhook Stripe, je veux voir directement dans la viewer si la signature `Stripe-Signature` du header est valide pour mon secret, sans devoir écrire mon propre validateur.

#### Périmètre — 9 services HMAC au lancement V3 (+ PayPal en V3.5)

| Service | Header | Algo | Secret format | V3 |
|---|---|---|---|---|
| Stripe | `Stripe-Signature` | HMAC-SHA256 avec timestamp | `whsec_…` | ✅ |
| GitHub | `X-Hub-Signature-256` | HMAC-SHA256 | string libre | ✅ |
| Shopify | `X-Shopify-Hmac-Sha256` | HMAC-SHA256 base64 | string libre | ✅ |
| Twilio | `X-Twilio-Signature` | HMAC-SHA1 sur URL+params | auth token | ✅ |
| Mailgun | `signature` (form param) | HMAC-SHA256 sur timestamp+token | string libre | ✅ |
| Discord | `X-Signature-Ed25519` | Ed25519 | public key | ✅ |
| Slack | `X-Slack-Signature` | HMAC-SHA256 sur v0:timestamp:body | signing secret | ✅ |
| Zapier | `X-Hook-Signature` | HMAC-SHA256 | secret hook | ✅ |
| n8n | `n8n-signature` (custom) | HMAC-SHA256 | string libre | ✅ |
| **PayPal** | `Paypal-Transmission-Sig` | **RSA-SHA256 + cert chain** | cert URL + webhook ID | ⏭️ V3.5 |

> ⚠️ PayPal est **matériellement différent** des 9 autres : pas de HMAC symétrique, mais signature RSA + récupération + validation d'une chaîne de certificats Apple-like. Coût d'implémentation ~3× celui d'un HMAC simple (cache de certs, validation chain, gestion expiration). Repoussé en V3.5 — couvre 9 services HMAC d'abord, on ajoute PayPal une fois le pattern stable.

#### Comportement

- **Config par endpoint** : champ optionnel `signature_provider` (`stripe|github|...`) + `signature_secret` (chiffré côté serveur).
- **À la capture** : si l'endpoint a une config signature, on calcule + on stocke le résultat (`valid`, `invalid`, `missing_header`) dans la table `requests` (nouveau champ `signature_status`).
- **Pas de rejet sur signature invalide** — on capture quand même et on affiche le statut. C'est un outil d'observabilité, pas un firewall.

#### UI

- Petite pastille colorée à côté de chaque request : verte (`valid`), rouge (`invalid`), grise (`missing_header`).
- Détail au survol : "Signature HMAC-SHA256 ne correspond pas au secret. Body diff (timestamp dérive 12 min)" etc.

#### Free vs Pro

**Free.** C'est exactement la feature visuelle qui sell le pitch — la garder gratuite est obligatoire.

---

### F2. Replay

#### User story

> En tant que dev qui débug, je veux pouvoir cliquer sur une request capturée et la re-firer contre mon `localhost:3000` (ou n'importe quelle URL) pour reproduire un bug.

#### Comportement

- Sur le viewer, bouton **"Replay"** à droite de chaque request → ouvre un dialog
- Champs : URL cible (default = dernière utilisée), méthode (default = celle d'origine), checkboxes pour "include original headers" / "include body"
- Sur submit : POST `/api/requests/{id}/replay` → l'app fait le call HTTP + stocke le résultat
- Résultat stocké : `target_url`, `status_code`, `response_time_ms`, `response_body` (premiers 8 KB), `error` si network failure
- Replay illimité tant qu'il y a quota — chaque replay compte vers le rate limit `endpoint`

#### Storage

Nouvelle table `replays` :

```
id           uuid pk
request_id   uuid fk → requests.id
target_url   text
status_code  int
response_ms  int
response_body_preview  text  (max 8KB, blob_offloaded if larger via R2)
error_message  text  (null sauf network failure)
replayed_at  timestamptz
```

#### Free vs Pro

**Free 1 replay manuel par request**, **Pro replay illimité + bulk replay (re-fire les 50 dernières d'un endpoint)**.

#### Edge cases

- Target URL bloquée (DNS fail, refused, SSL fail) → store `error_message`, status 0
- Target URL = localhost / 127.0.0.1 / 10.x / 192.168.x → refuser côté serveur (SSRF protection)
- Target URL = même domaine que le service (e.g. `*.<our-domain>`) → refuser (anti-amplification SSRF self-pointing)
- Body > 1 MB → tronquer pour le replay (avec warning visible)

---

### F3. Per-integration view (grouping)

#### User story

> En tant que dev avec un endpoint qui reçoit du Stripe, GitHub et un webhook custom, je veux voir une vue séparée par source avec compteurs et p95 latency par intégration.

#### Détection d'intégration

Heuristique à la capture, stockée dans nouveau champ `requests.detected_integration`. **Priorité = ordre de cette liste** (le premier qui match gagne), avec les services les plus spécifiques en haut pour éviter qu'un proxy générique faussement positif (e.g. un middleware qui forward avec `X-GitHub-Event` ajouté) ne masque la vraie source :

```python
# Priority order: most specific signature first
DETECTORS = [
    ("stripe",  lambda h, ua, p: "stripe-signature" in h),
    ("github",  lambda h, ua, p: "x-github-event" in h and "x-github-delivery" in h),
    ("shopify", lambda h, ua, p: "x-shopify-topic" in h and "x-shopify-shop-domain" in h),
    ("twilio",  lambda h, ua, p: "x-twilio-signature" in h),
    ("mailgun", lambda h, ua, p: "x-mailgun-signature-v2" in h or ("signature" in p and "timestamp" in p)),
    ("discord", lambda h, ua, p: "x-signature-ed25519" in h and "x-signature-timestamp" in h),
    ("slack",   lambda h, ua, p: "x-slack-signature" in h and "x-slack-request-timestamp" in h),
    ("zapier",  lambda h, ua, p: "x-hook-signature" in h and "zapier" in ua.lower()),
    ("n8n",     lambda h, ua, p: "x-n8n-signature" in h),
    # PayPal in V3.5: Paypal-Transmission-Sig + cert chain
]

def detect_integration(headers: dict, user_agent: str, form_params: dict) -> str | None:
    for name, predicate in DETECTORS:
        if predicate(headers, user_agent, form_params):
            return name
    return None
```

**Tie-breaker rule** : si une request match plusieurs détecteurs (rare mais possible), c'est le premier dans `DETECTORS` qui gagne. Documenté.

**Override** : si la config endpoint a un `signature_provider` set, on suppose que l'utilisateur sait ce que c'est et on bypasse la détection auto (le `signature_provider` devient la valeur de `detected_integration`).

#### Sous-types par intégration

Pour les requests avec `detected_integration`, extraire un sous-type :
- Stripe : `event_type` de body JSON (e.g. `payment_intent.succeeded`)
- GitHub : header `X-GitHub-Event` (e.g. `pull_request`)
- Shopify : header `X-Shopify-Topic` (e.g. `orders/create`)
- Discord : `t` field du body (e.g. `MESSAGE_CREATE`)
- ...

Stocké dans `requests.detected_event_type` (text).

#### UI

Nouvelle tab `/endpoints/{token}/integrations` :
- Liste des intégrations détectées avec compteurs (`Stripe: 47 requests, 2 signature failures, p95 latency 120ms`)
- Drill-down : `/integrations/stripe` → liste filtrée par cette intégration, breakdown par `event_type`
- Sparkline 24h par intégration

#### Free vs Pro

**Free.** Drive viralité — un dev voit immédiatement "ah tiens Stripe envoie 47 events de plus depuis hier".

---

### F4. Schema inference + diff

#### User story

> En tant que dev qui consomme un webhook tiers, je veux savoir quand le schéma JSON du payload change (nouveau champ, type modifié) pour mettre à jour mon parser avant que ça casse.

#### Approche

- Bibliothèque : `genson` (Python, génère JSON Schema depuis exemples concrets) ou implémentation maison légère
- Génération du schéma : sur chaque request avec body JSON valide → schéma inféré
- Stockage : par endpoint + integration + event_type → un schéma cumulatif évolutif
- Diff : à la capture d'une request, comparer son schéma local au schéma cumulatif et noter les changements

#### Storage

Nouvelle table `inferred_schemas` :

```
id                  uuid pk
endpoint_id         uuid fk
integration         text  (e.g. "stripe")
event_type          text  (e.g. "payment_intent.succeeded", nullable)
schema_json         jsonb  (le JSON Schema cumulatif)
sample_count        int    (combien de payloads ont contribué)
last_updated_at     timestamptz
unique key (endpoint_id, integration, event_type)
```

Nouvelle colonne `requests.schema_drift` (jsonb null) : si le request introduit des changements, stocker la diff (nouveau champ, type changé). Vide sinon.

#### UI

- Page `/endpoints/{token}/schemas` : tableau des schémas inférés
- Sur chaque request : pastille "🟡 schema drift" si non vide, click → vue diff (champ ajouté en vert, type changé en jaune)
- Filtre dans la liste : "Show only requests with schema drift"

#### Free vs Pro

**Free**, mais avec limite : on garde max 10 schemas/endpoint actifs en free (Pro = illimité + alerts sur drift).

#### Implementation note

`genson` génère un schéma cumulatif efficacement en SQL via UPSERT JSONB. Pas besoin de stocker tous les payloads — juste le schéma running.

**Seuil de convergence** : freeze le schéma quand `sample_count >= 10 000`. Au-delà, le schéma a vu suffisamment d'exemples pour avoir convergé ; les itérations marginales coûtent du CPU pour zéro valeur. Si une drift réelle apparaît après freeze, l'admin peut reset le schéma manuellement.

---

### F5. Forward avec retry + DLQ

#### User story

> En tant que dev qui veut consommer ses webhooks Stripe en prod via mon API, je veux configurer le service comme proxy : capture → forward auto vers mon URL prod avec retry exponential. Si mon API est down, les events s'accumulent en DLQ et je peux les rejouer plus tard.

#### Comportement

- Config par endpoint : `forward_url`, `forward_headers` (override custom), `forward_secret` (pour signer le forward avec un HMAC nous-mêmes)
- Sur chaque capture : enqueue un forward job (Celery? Arq? Simple PG-based queue?)
- Tentatives : 1, puis backoff exponentiel 30s / 2min / 10min / 1h / 4h (5 tentatives total)
- DLQ : après 5 échecs → marquer comme `dlq_status='dead'`, visible dans une page dédiée

#### Storage

Nouvelle table `forwards` :

```
id              uuid pk
request_id      uuid fk → requests.id
endpoint_id     uuid fk → endpoints.id
target_url      text
status          enum (pending, in_flight, succeeded, failed, dead)
attempt_count   int
last_attempt_at timestamptz
next_attempt_at timestamptz
final_status_code int  (after final attempt)
final_error     text
forward_started_at timestamptz
forward_completed_at timestamptz
```

#### Worker

Job runner Arq (Redis-backed, async-native, Python-friendly) — déployer comme nouvelle Fly app `webhook-inspector-worker`.

**Redis hosting** : utiliser **Upstash Redis** via Fly (`fly redis create` provisionne une DB Upstash dans la même région). Free tier = 10 000 commands/jour, suffit pour ~1 000 forwards/jour. Au-delà, plan payant Upstash démarre à $0.20/100k commands. À 100k forwards/jour → ~$5-8/mo Redis.

Alternative auto-hébergée : Redis container sur une Fly Machine `shared-cpu-1x` 256MB ~$2/mo + volume 1GB ~$0.15. Plus cheap mais à gérer (snapshots, upgrades). À considérer une fois F5 stabilisé.

#### UI

- Page `/endpoints/{token}/forwards` : DLQ + retry status
- Bouton "Retry now" sur les `failed` items
- Bouton "Drop" pour purger DLQ items après investigation
- Compteur dashboard : "12 forwards dead, 3 in-flight, 1 247 succeeded today"

#### Free vs Pro

**Pro only.** Forward est le point de conversion principal — il transforme le service d'un debug tool en infra production.

#### Edge cases

- Target URL slow (>30s timeout) → marquer attempt failed, retry
- Target URL renvoie 4xx → ne PAS retry (mauvais payload, retry n'aidera pas). Sauf 408/429 où on retry.
- Target URL renvoie 5xx → retry
- DLQ size unbounded → cap à 1000 dead items/endpoint, oldest evicted

**Storage estimate DLQ** : à 100k forwards/jour × ~3% échec final → ~3k dead items/jour × ~5KB metadata (URL, headers, error, response preview tronqué) = ~15 MB/jour. Avec le cap 1000/endpoint et purge auto à 30j, plafond confortable < 1GB sur le volume PG.

---

### F6. Transform (JSONata)

#### User story

> En tant que dev qui veut forwarder un webhook Stripe vers un endpoint qui attend un payload différent (renommer `payment_intent.id` en `paymentId`, filtrer le champ `metadata`), je veux configurer une règle de transformation déclarative, pas un script.

#### Choix technique

**JSONata** ([jsonata.org](https://jsonata.org)). Pourquoi pas un sandbox JS/Python ?

- JSONata est **déclaratif**, déterministe, sans I/O, sans loop infinie → safe par construction
- Syntaxe familière à quiconque a fait du jq ou du XPath
- Pas de "code execution as a service" = pas de surface attaque massive

> ⚠️ **Choix de lib Python à investiguer avant de figer.** Les options pour exécuter JSONata depuis Python :
> 1. `jsonata-python` (PyPI) — maintenance intermittente, dernière release datant. À vérifier que les fonctions critiques marchent.
> 2. `pyjsonata` — alternative, moins connue.
> 3. Wrapper subprocess sur la lib JS officielle (Node) — fiable mais ajoute Node comme dépendance runtime.
> 4. Implémenter un **subset déclaratif maison** couvrant les 80% cas concrets (path access, rename, filter, basic arithmetic) — ~500 lignes Python, contrôle total, pas de dette tiers. Recommandé si le scope reste petit.
>
> Décision : tester (1) et (2) sur les use cases du spec en sprint 4 ouverture, si bloquant → fallback subset maison.

Exemple :
```
{
  "paymentId": payment_intent.id,
  "amount": payment_intent.amount / 100,
  "currency": payment_intent.currency
}
```

#### Config par endpoint

Nouveau champ `endpoints.transform_expression` (text, null). Si set, appliqué entre la capture et le forward.

#### UI

- Éditeur JSONata avec :
  - Payload d'exemple à gauche (dernière request capturée)
  - Expression au milieu
  - Résultat live preview à droite
- Test "Apply to last 10 requests" pour valider
- Versionning : garder l'historique des expressions (au cas où regression)

#### Free vs Pro

**Pro only.** Transform est une feature production essentielle.

#### Edge cases

- Expression invalide → ne pas bloquer le forward, log warning, forward le payload original
- Timeout JSONata > 1s → kill et fallback
- Output non-JSON-encodable → fallback

---

### F7. OTEL timeline view

#### User story

> En tant que dev qui regarde un request capturé, je veux voir la timeline complète : capture HTTP → HMAC check → DB write → R2 offload (si body > 8KB) → schema inference → forward → response, avec timing par span.

#### Approche

- Tous les spans OTEL sont déjà émis par notre stack (FastAPI, SQLAlchemy, psycopg, custom spans côté capture/forward)
- Au capture : extraire les spans associés au request via `trace_id` et stocker un résumé dans `requests.trace_summary` (jsonb)
- Le résumé contient les spans clés (operation_name, duration_ms, status) — pas les attributes complets (économise storage)

#### Storage

Nouvelle colonne `requests.trace_summary` (jsonb) — array d'objets `{name, duration_ms, status, attributes}` avec au max 20 spans/request.

#### UI

Sur la page detail request : nouvelle section "Timeline" avec diagramme horizontal des spans :
```
[capture HTTP    ] 12ms
  [validate HMAC ] 3ms  ✓
  [insert request] 8ms
    [offload R2  ] 38ms
  [detect integration] 2ms
  [infer schema  ] 5ms
[forward         ] 142ms
  [POST target   ] 138ms  → 200 OK
```

#### Free vs Pro

**Free** (basique : top-level spans). **Pro** : drill-down full attributes + filter spans.

---

## Modèle de données

Migrations Alembic à ajouter en V3 (nouvelle 0004).

**Prérequis à vérifier** avant d'écrire la migration : confirmer dans le schéma V2.5 actuel que (1) la colonne `requests.endpoint_id` existe et est NOT NULL, (2) la contrainte `endpoints.id` est bien `uuid PRIMARY KEY`. Si différence, ajuster les FK ci-dessous.

**Interaction avec V2.5 search vector** : la V2.5 a ajouté `requests.search_vector` comme **colonne `GENERATED ALWAYS AS (...) STORED`** (cf. migration `0003_5058fb3e1c3e_search_vector.py`). L'expression actuelle concatène `method || path || body_preview || headers::text`.

Pour étendre la recherche aux nouvelles colonnes (`signature_status`, `detected_integration`, `detected_event_type`) :

- **PostgreSQL ne permet pas d'ALTER l'expression d'une generated column** → opération en deux temps :
  ```sql
  ALTER TABLE requests DROP COLUMN search_vector;
  ALTER TABLE requests ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
    to_tsvector('simple',
      coalesce(method, '') || ' ' ||
      coalesce(path, '') || ' ' ||
      coalesce(body_preview, '') || ' ' ||
      coalesce(headers::text, '') || ' ' ||
      coalesce(signature_status, '') || ' ' ||
      coalesce(detected_integration, '') || ' ' ||
      coalesce(detected_event_type, '')
    )
  ) STORED;
  ```
- **Coût : full table rewrite** (Postgres recalcule la generated column pour chaque ligne existante). À 10k rows → ~quelques secondes. À 1M rows → ~minutes (lock ACCESS EXCLUSIVE pendant l'opération sauf si on utilise `pg_repack` / approche zero-downtime — overkill pour V3).
- L'index GIN doit aussi être recréé après le DROP/ADD (la nouvelle colonne ressort sans index) → `CREATE INDEX CONCURRENTLY IF NOT EXISTS requests_search_idx ON requests USING GIN (search_vector);`
- **Recommandation** : faire le DROP/ADD pendant une maintenance window courte (downtime ~30s à <1M rows). Pre-prod : tester sur un dump de la prod-like.

Migrations :

```sql
-- F1
ALTER TABLE endpoints ADD COLUMN signature_provider text;
ALTER TABLE endpoints ADD COLUMN signature_secret_encrypted bytea;  -- AES-GCM
ALTER TABLE requests ADD COLUMN signature_status text;  -- valid|invalid|missing|na

-- F2
CREATE TABLE replays (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    target_url text NOT NULL,
    status_code int,
    response_ms int,
    response_body_preview text,
    error_message text,
    replayed_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON replays(request_id, replayed_at DESC);

-- F3
ALTER TABLE requests ADD COLUMN detected_integration text;
ALTER TABLE requests ADD COLUMN detected_event_type text;
CREATE INDEX ON requests(endpoint_id, detected_integration) WHERE detected_integration IS NOT NULL;

-- F4
CREATE TABLE inferred_schemas (
    id uuid PRIMARY KEY,
    endpoint_id uuid NOT NULL REFERENCES endpoints(id) ON DELETE CASCADE,
    integration text NOT NULL,
    event_type text,
    schema_json jsonb NOT NULL,
    sample_count int NOT NULL DEFAULT 0,
    last_updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (endpoint_id, integration, event_type)
);
ALTER TABLE requests ADD COLUMN schema_drift jsonb;

-- F5
ALTER TABLE endpoints ADD COLUMN forward_url text;
ALTER TABLE endpoints ADD COLUMN forward_headers jsonb;
ALTER TABLE endpoints ADD COLUMN forward_secret_encrypted bytea;
CREATE TABLE forwards (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    endpoint_id uuid NOT NULL REFERENCES endpoints(id) ON DELETE CASCADE,
    target_url text NOT NULL,
    status text NOT NULL CHECK (status IN ('pending', 'in_flight', 'succeeded', 'failed', 'dead')),
    attempt_count int NOT NULL DEFAULT 0,
    last_attempt_at timestamptz,
    next_attempt_at timestamptz,
    final_status_code int,
    final_error text,
    forward_started_at timestamptz,
    forward_completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON forwards(status, next_attempt_at) WHERE status IN ('pending', 'failed');
CREATE INDEX ON forwards(endpoint_id, created_at DESC);

-- F6
ALTER TABLE endpoints ADD COLUMN transform_expression text;

-- F7
ALTER TABLE requests ADD COLUMN trace_summary jsonb;
```

Partitioning de `requests` par jour reste à ajouter en parallèle (lié au scaling de Phase 0 dans le launch plan).

---

## Surface API

### Endpoints REST nouveaux

```
PATCH  /api/endpoints/{token}/config
  body: {
    signature: {provider, secret} | null,
    forward: {url, headers, secret} | null,
    transform_expression: string | null
  }
  → 200, retourne la config courante (secrets masqués)

POST   /api/requests/{id}/replay
  body: {target_url, method?, include_headers?, include_body?}
  → 202, retourne le replay_id, statut async

GET    /api/requests/{id}/replays
  → liste des replays passés

GET    /api/endpoints/{token}/integrations
  → liste agrégée par detected_integration avec compteurs/p95

GET    /api/endpoints/{token}/integrations/{integration}
  → détail + breakdown par event_type

GET    /api/endpoints/{token}/schemas
  → liste des schemas inférés + last sample timestamps

GET    /api/endpoints/{token}/forwards
  → DLQ + retry status (filtrable par status)

POST   /api/forwards/{id}/retry
  → manual retry d'un forward dead

DELETE /api/forwards/{id}
  → drop manual d'un DLQ item
```

### Endpoint ingestion existant inchangé

`POST /h/{token}` reste identique — la magie observability est invisible côté sender, c'est l'intérêt.

---

## Sécurité & secrets

### Chiffrement des secrets

- Master key dans Fly secret `SECRETS_ENCRYPTION_KEY` (32 bytes random base64). À poser sur web + ingestor + worker apps **avant** la première migration V3 qui crée les colonnes `*_secret_encrypted`. À ajouter dans `config.py` comme `Settings.secrets_encryption_key: str` (sans default — fail-fast au boot si absent).
- AES-GCM avec nonce unique par secret → stocké en `bytea` (nonce + ciphertext + tag)
- Lib : `cryptography` (Python — pas transitive dep aujourd'hui, à ajouter via `uv add cryptography` lors du sprint F1)
- Rotation : prévoir un mécanisme `SECRETS_ENCRYPTION_KEY_PREVIOUS` pour migration (tente decrypt avec current key, fallback previous, re-encrypt avec current). Implémentable en V3.5, pas bloquant V3.

**Génération de la clé** :
```bash
openssl rand -base64 32  # → coller dans `fly secrets set SECRETS_ENCRYPTION_KEY=...`
```

### SSRF protection (replay + forward)

Refuser les `target_url` qui :
- Résolvent vers private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.0.0/16`, fc00::/7, fe80::/10, etc.)
- Domaine = même que le service (anti-amplification self-pointing)
- Protocole != `https://` ou `http://` (refuse `file://`, `ftp://`)

**DNS rebinding mitigation** : implémentation non-triviale avec `httpx` qui ne supporte pas l'override d'IP nativement. Approche concrète :

```python
# Resolve once, pass IP + Host header
import socket
ip = socket.gethostbyname(parsed.hostname)
assert_not_private_range(ip)
url_with_ip = parsed._replace(netloc=ip).geturl()
async with httpx.AsyncClient(verify=True) as client:
    await client.post(url_with_ip, headers={"Host": parsed.hostname, ...}, ...)
```

Coût : ~50 lignes utilitaire + tests dédiés (private ranges, IPv6, DNS rebinding canary). À budgéter une demi-journée par feature qui sort de l'app (F2 replay + F5 forward).

Lib alternative : `httpx-socks` ou `httpx-cache` n'aident pas. La meilleure ressource publique : [`requests-ip-rotator`](https://github.com/Ge0rg3/requests-IP-Rotator) pour le pattern, à adapter en async.

### Rate limiting

- Replay : 30 / heure / endpoint en free, 300 / heure en Pro
- Forward : pas de limite app-level (limite contrôlée par le target URL lui-même), mais cap absolu à 100 req/s/endpoint pour éviter qu'on devienne un DDoS amplifier

---

## Ordre de livraison

Priorisé par effort + impact pitch :

1. **F1 HMAC validation** (sprint 1, 1 semaine) — feature la plus visible et la plus simple, drive le pitch
2. **F3 Per-integration view** (sprint 1, 1 semaine) — UI réutilise F1, "ça fait riche" sur Show HN
3. **F2 Replay** (sprint 2, 1 semaine) — killer feature dev, code modéré
4. **F4 Schema inference + diff** (sprint 2, 1 semaine) — "wow" feature, bien pour le blog technique
5. **F7 OTEL timeline view** (sprint 3, ~3 jours) — UI-only, données déjà dispos
6. **F5 Forward + retry + DLQ** (sprint 3, 1.5 semaines) — feature paid tier la plus importante
7. **F6 Transform** (sprint 4, 1 semaine) — paid tier, complète F5

**Effort total (somme dev) : 7 semaines.** Avec buffer review/bug/intégration réaliste : **8-9 semaines solo full-time**, soit ~3-4 mois en side-project (10-15h/sem).

### Définition de "fait" par feature

(Les conventions repo standard — pre-commit / ruff / mypy / pytest — sont assumées et ne sont pas re-listées par feature.)

- Tests unitaires + integration (testcontainers Postgres)
- E2E test minimum : capture → trigger feature → verify result
- Documentation user (`docs/integrations/` pour F1, par feature pour F2-F7)
- Pas de breaking change sur l'API publique existante (V2.5 `/api/endpoints/{token}/requests` reste stable)

---

## Out of scope (V3.5 / V4)

- **Multi-target forward** : V3 = 1 URL cible. Multi-targets + fan-out = V4 (probablement avec Apache Kafka ou NATS si volume justifie)
- **PayPal HMAC RSA + cert chain** : reporté en V3.5 (cf. note dans F1)
- **Custom integrations** : ajouter Calendly, HubSpot, Salesforce, etc. → V3.5 si signal user (≥3 demandes par intégration)
- **Bulk replay** : "rejoue toutes les requests des 24 dernières heures" → V3.5
- **Schema validation strict** : passer du diff au "reject if drift" → V4 (territoire team tier)
- **Alerts via Slack/email** : V4 — nécessite un système de notification cross-cutting
- **API tokens / SDK** : V5 (avec auth)
- **Webhook origin verification** : valider que le webhook vient bien d'une IP Stripe etc. (registry des CIDR Stripe officiels) → V3.5 si plébiscité

---

## Risques techniques

| Risque | Mitigation |
|---|---|
| Forward worker DLQ explose si target prod a une panne longue | Cap absolu 1000 dead items/endpoint, alerte Honeycomb si dépasse 100, page UI claire pour purge en masse |
| JSONata library bug / DoS via expression maligne | Timeout 1s strict + cap expression length 10KB |
| HMAC secret leak côté logs structlog | Filter explicit `signature_secret*` dans la config structlog, redact dans serialization |
| SSRF découvert tardivement → exploit | Test suite dédiée SSRF (private ranges, DNS rebinding, redirect chasing) avant déploiement F2/F5 |
| Schema inference scale mal sur endpoints à 100k+ requests | Cap `sample_count` à 10 000, après ça on freeze le schéma (suffisamment converged) |
| OTEL spans manquants en prod (sampling 10%) | Pour F7, désactiver le sampling sur les spans liés à la capture — toujours 100% tracé sur ce chemin |

---

## Notes finales

- V3 verrouille le **moat observability**. Sans HMAC validation built-in et per-integration view, on est un n-ième clone webhook.site. Avec, on est positionné uniquement.
- F5 (forward) est le moment où l'archi doit gérer une async queue propre. C'est aussi le moment où la facture Fly va augmenter (3e app, Redis pour Arq, retention extended). Budgéter ~€30/mo Fly à partir de F5 vs ~€10/mo aujourd'hui.
- F6 (transform) peut être skip en V3 si le scope déborde — le Pro tier tient avec juste F5 + alerts (V4). Mais inclure F6 rend le Pro beaucoup plus défensable face à Hookdeck.
- F7 (timeline) est cheap (~3 jours) et c'est ce qui fait dire "oh putain" en démo. Ne pas le sacrifier.
