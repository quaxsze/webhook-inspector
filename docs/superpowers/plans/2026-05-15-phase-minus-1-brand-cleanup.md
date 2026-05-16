# Phase -1 — Brand & docs consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking. Plus ops-heavy que le plan Phase 0 — beaucoup de tâches sont à exécuter manuellement par le maintainer (achat domaine, création comptes), pas par un subagent.

**Goal:** Aligner toute la surface publique du repo (URLs, branding, langue, archi diagram) sur `hooktrace.io` et l'architecture Fly.io actuelle, **avant** de démarrer Phase 0 — sinon les interviewés en Phase 1 (customer discovery) tombent sur des incohérences (Cloud Run dans le README, `lang="fr"`, `odessa-inspect.org` partout).

**Architecture:**
- 8 tâches séquentielles, ~1 semaine total
- 4 tâches "ops" (manuelles, hors subagent) : achat domaine + comptes + Fly certs + DNS
- 4 tâches code/docs : pure search/replace + edits markdown, pas de TDD lourd
- **Pas de risque de migration DB ni de feature regression** (Phase -1 est strictement additive côté code, aucun changement applicatif)
- **Risque DNS/cert présent et borné en T7** : le cutover supprime les CNAMEs `odessa-inspect.org` et les certs Fly associés. Rollback = recréer les CNAMEs et `fly certs add` (les domain mappings Fly et la zone Cloudflare restent valides côté infra). Vu l'absence d'utilisateurs réels, le coût d'un cutover raté = redéploiement DNS de quelques minutes, pas une indisponibilité visible

**Tech Stack:** Markdown + Jinja2 templates + grep/sed pour les rewrites massifs.

**Sources :**
- `docs/launch/2026-05-15-launch-plan.md` — Phase -1 section + décisions 1, 2, 4 (branding)
- Règle de substitution app./hook./apex documentée dans le launch plan

---

## Pre-requisites

- [ ] Branche fraîche depuis main : `git checkout -b chore/phase-minus-1-rebrand`
- [ ] Lire `docs/launch/2026-05-15-launch-plan.md` sections "Décisions à prendre" + "Phase -1"

## Tâches dans l'ordre d'exécution

| # | Tâche | Type | Effort | Bloque |
|---|---|---|---|---|
| T1 | Achat domaine + réservation usernames | Ops | 30 min | T2-T8 |
| T2 | Création comptes Honeycomb + GitHub org | Ops | 30 min | Phase 0 PR1 |
| T3 | Décision repo GitHub (transfer/fork/stay) + exécution | Ops + git | 30 min | T6 (badges README) |
| T4 | Setup DNS + Fly certs sur hooktrace.io | Ops | 30 min | T7 cutover |
| T5 | Rebrand massif `odessa-inspect.org` dans code/docs | Code | 2-3 h | T7 |
| T6 | viewer.html `lang="fr"` → `lang="en"` + i18n strings | Code | 1 h | — |
| T7 | DNS cutover odessa → hooktrace + couper l'ancien | Ops | 1 h | T4 + **T5 ET T6** (sinon viewer FR exposé sur le nouveau domaine) |
| T8 | Verification grep + sanity tests | Code | 30 min | — |

**Total :** ~6-8 heures de travail concentré, étalable sur ~1 semaine en side-project.

---

## T1 — Achat domaine + réservation usernames (Ops)

Tâche manuelle hors subagent. ~30 min total.

- [ ] **Acheter `hooktrace.io`** chez Cloudflare Registrar (https://www.cloudflare.com/products/registrar/) — at-cost ~$45-50/an. Pourquoi Cloudflare : intégration native avec la zone DNS déjà chez eux, pas de markup, gestion WHOIS privacy auto.

- [ ] **Vérifier les usernames disponibles** (snapshot 2026-05-15, à re-confirmer à l'achat) :
  - Bluesky `hooktrace.bsky.social` : libre
  - npm `hooktrace` : libre
  - PyPI `hooktrace` : libre
  - GitHub `@hooktrace` : **squatté par compte dormant** (créé 2026-01-28, 0 repos). Workaround → org `hooktrace-io` (cf. T2).
  - X/Twitter `@hooktrace` : à vérifier manuellement (WebFetch bloqué par X)

- [ ] **Réserver les usernames libres** :
  - Bluesky : créer compte avec handle `hooktrace.bsky.social`
  - npm : `npm publish` d'un package placeholder (ou réserver via support si pas prêt à publier)
  - PyPI : créer un projet vide via le formulaire web

- [ ] **(Optionnel) Mastodon** : choisir une instance (`hachyderm.io`, `fosstodon.org` pour devs) et créer `@hooktrace@<instance>`.

- [ ] **Noter dans un password manager** : login Cloudflare Registrar, dates de renouvellement, contacts admin/billing du domaine.

**DoD T1 :** Domaine acheté, 3-4 usernames externe réservés, credentials dans un password manager.

---

## T2 — Création comptes externes (Ops)

Tâche manuelle. ~30 min.

- [ ] **Honeycomb** : créer compte free tier sur https://www.honeycomb.io. Créer un environnement `webhook-inspector-prod`. Copier la **Honeycomb API Key** (depuis Environment settings → API Keys). Noter dans password manager.

- [ ] **GitHub organization `hooktrace-io`** : https://github.com/organizations/plan (Free plan suffit). Cette org sera la cible si tu choisis l'option A de T3 (transfer).

- [ ] **Cloudflare R2** : déjà setup (bucket `wi-blobs-prod` créé en migration Fly). Vérifier qu'il existe encore avec `wrangler r2 bucket list` ou via le dashboard.

- [ ] **GitHub repo secret `FLY_API_TOKEN`** : déjà setup. Si transfert de repo en T3, à reposer dans le nouveau repo.

**DoD T2 :** Honeycomb API key en main, GitHub org `hooktrace-io` créée, R2 bucket vérifié.

---

## T3 — Décision repo GitHub + exécution (Ops + git)

Trois options listées dans le launch plan. **Choisir avant d'exécuter**.

### Option A — Transfer + rename

- [ ] **Transfer** : Settings → Transfer ownership → `hooktrace-io`. Ou CLI :
  ```bash
  gh api repos/quaxsze/webhook-inspector/transfer -f new_owner=hooktrace-io
  ```
- [ ] **Rename** dans la nouvelle org : `hooktrace-io/webhook-inspector` → `hooktrace-io/hooktrace` via Settings → Rename
- [ ] **Update local remote** :
  ```bash
  git remote set-url origin git@github.com:hooktrace-io/hooktrace.git
  git remote -v  # verify
  ```
- [ ] GitHub redirige automatiquement les anciennes URLs `git clone` mais **pas** les liens README/badges → tous à update en T5.

### Option B — Fork + archive

- [ ] Créer nouveau repo `hooktrace-io/hooktrace` (empty) via GitHub UI ou :
  ```bash
  gh repo create hooktrace-io/hooktrace --public --description "The free observability layer for webhooks"
  ```
- [ ] Ajouter le remote du nouveau repo en local :
  ```bash
  git remote add hooktrace-io git@github.com:hooktrace-io/hooktrace.git
  git remote -v  # verify
  ```
- [ ] Push une copie propre :
  ```bash
  git push hooktrace-io main && git push hooktrace-io --tags
  ```
- [ ] Repointer `origin` vers le nouveau repo pour les futurs pushes :
  ```bash
  git remote set-url origin git@github.com:hooktrace-io/hooktrace.git
  git remote remove hooktrace-io  # plus besoin, c'est devenu origin
  ```
- [ ] Sur `quaxsze/webhook-inspector` : Settings → Archive this repository → ajouter un README sticky "Moved to https://github.com/hooktrace-io/hooktrace"

### Option C — Stay on quaxsze/

- [ ] Pas d'action. Brand projet sur le domaine + org GitHub `hooktrace-io` pour les éventuels sub-projects (SDK Python, CLI, etc.). Repo reste sur le compte perso. Badges + landing pointent toujours sur `quaxsze/webhook-inspector`.

**DoD T3 :** Décision prise et exécutée. Remote local pointe vers la bonne URL. T5 + T6 connaissent l'URL canonical à utiliser dans les liens.

---

## T4 — DNS + Fly certs sur hooktrace.io (Ops)

À faire **après T1 (domaine acheté)**, **avant T7 (cutover)**.

- [ ] **Importer la zone `hooktrace.io` dans Cloudflare DNS** (auto si Cloudflare Registrar) — vérifier que les NS de Cloudflare sont bien actifs : `dig NS hooktrace.io +short`.

- [ ] **Configurer la Page Rule apex → app** :
  - Cloudflare → Rules → Page Rules → Create
  - URL pattern : `hooktrace.io/*`
  - Setting : **Forwarding URL** → 301 (Permanent Redirect) → `https://app.hooktrace.io/$1`
  - Save & deploy.

- [ ] **Demander les certs Fly pour les deux subdomains** :
  ```bash
  fly certs add app.hooktrace.io --app webhook-inspector-web
  fly certs add hook.hooktrace.io --app webhook-inspector-ingestor
  ```
  Output : Fly imprime soit "Recommended DNS setup: A/AAAA → <IPs>", soit propose un challenge ACME DNS-01.

- [ ] **Créer les 2 CNAMEs Cloudflare** (DNS-only, proxy OFF/gris) :
  - `app.hooktrace.io` CNAME → `webhook-inspector-web.fly.dev`
  - `hook.hooktrace.io` CNAME → `webhook-inspector-ingestor.fly.dev`

- [ ] **Si Fly demande un challenge DNS-01** (cf. flow d'init du domaine actuel `odessa-inspect.org`) : créer les 2 CNAMEs `_acme-challenge.app.hooktrace.io` et `_acme-challenge.hook.hooktrace.io` vers les targets `<hash>.flydns.net` indiqués par `fly certs setup app.hooktrace.io`.

- [ ] **Attendre validation Let's Encrypt** (~1-5 min) :
  ```bash
  fly certs check app.hooktrace.io --app webhook-inspector-web
  fly certs check hook.hooktrace.io --app webhook-inspector-ingestor
  ```
  Both must report `Status: Issued`.

- [ ] **Smoke test via `--resolve`** (DNS public peut encore servir l'ancien domaine, on force la résolution) :
  ```bash
  WEB_IP=66.241.124.237  # cf. fly ips list --app webhook-inspector-web
  ING_IP=66.241.124.115  # cf. fly ips list --app webhook-inspector-ingestor
  curl --resolve app.hooktrace.io:443:$WEB_IP -fsS https://app.hooktrace.io/health
  curl --resolve hook.hooktrace.io:443:$ING_IP -fsS https://hook.hooktrace.io/health
  ```
  Both must return `{"status":"healthy",...}`.

**DoD T4 :** Certs Issued, DNS public résout `app.` et `hook.` vers Fly, smoke test 200.

---

## T5 — Rebrand massif `odessa-inspect.org` (Code)

Suit la **règle de substitution app./hook./apex** documentée dans le launch plan. Chaque occurrence est annotée avec sa surface cible. **Aucune URL fonctionnelle ne doit utiliser l'apex `hooktrace.io`** — c'est uniquement pour la prose brand.

### Step 1: README.md (~8 occurrences)

Modifier `README.md` selon le mapping :
- L118 : `App: https://app.odessa-inspect.org` → `App: https://app.hooktrace.io`
- L119 : `Ingestor: https://hook.odessa-inspect.org` → `Ingestor: https://hook.hooktrace.io`
- L132 : `curl -X POST https://app.odessa-inspect.org/api/endpoints` → `app.hooktrace.io`
- L155 : idem L132
- L170 : `curl "https://app.odessa-inspect.org/api/endpoints/$TOKEN/requests?q=..."` → `app.hooktrace.io`
- L185 : `curl -OJ "https://app.odessa-inspect.org/api/endpoints/$TOKEN/export.json"` → `app.hooktrace.io`
- Redessiner le **diagramme d'architecture en haut du README** (lignes ~16-50 actuellement) pour refléter Fly + R2 + OTLP au lieu de Cloud Run + Cloud SQL + GCS. Le diagramme historique peut rester sous "Roadmap V2.6" — pas en tête de doc.
- L3-4 (badges CI/Deploy) : si T3 = transfer, les URLs des badges deviennent `hooktrace-io/hooktrace`. Si T3 = stay, inchangé.
- L236 : lien Security Advisories `github.com/quaxsze/webhook-inspector/security/advisories/new` → idem badges.

### Step 2: landing.html (~6 occurrences brand + URLs)

Modifier `src/webhook_inspector/web/app/templates/landing.html` :
- L6 : `<title>webhook-inspector — Generate a URL, inspect any webhook live</title>` → `<title>hooktrace — Webhook observability with capture, debug, replay</title>` (placeholder ; copy finale viendra en PR12 du plan Phase 0)
- L10 : `<meta property="og:title" content="webhook-inspector">` → `content="hooktrace"`
- L13 : `<meta property="og:url" content="https://app.odessa-inspect.org/">` → `https://app.hooktrace.io/` (URL canonical, pas l'apex qui 301-redirect)
- L23 : `<h1>webhook-inspector</h1>` → `<h1>hooktrace</h1>`
- L140 : exemple `https://hook.odessa-inspect.org/h/AbCdEf...` → `https://hook.hooktrace.io/h/AbCdEf...`
- L144 : idem L140
- L152 : `<a href="https://github.com/quaxsze/webhook-inspector">open source</a>` → nouveau repo URL selon T3

### Step 3: viewer.html (brand)

Modifier `src/webhook_inspector/web/app/templates/viewer.html` :
- L5 : `<title>Webhook Inspector — {{ token }}</title>` → `<title>hooktrace — {{ token }}</title>`
- L14 : `<h1 class="text-xl font-mono">webhook-inspector</h1>` → `<h1>hooktrace</h1>` (vérifier la ligne exacte via `grep -n webhook-inspector src/webhook_inspector/web/app/templates/viewer.html`)

(Le `lang="fr"` → `lang="en"` est traité en T6, séparément.)

### Step 4: Specs historiques — **mode rewrite** (décision actée ici)

> **Choix du mode** : on retient le **rewrite** des URLs dans les specs V2 et V2.5 (cohérent avec le grep de vérification T8 qui exclut ces fichiers de l'allowlist conditionnelle si rewrite). La spec V1 (`2026-05-11-webhook-inspector-design.md`) ne contient pas d'URL `odessa-inspect.org` à réécrire mais reçoit un banner historique qui désamorce les futures lectures.

- `docs/specs/2026-05-13-v2-custom-response-and-observability-design.md` (rewrite URLs) :
  - Ligne 6 : `https://app.odessa-inspect.org` → `https://app.hooktrace.io`
  - Ligne 139 : `"url": "https://hook.odessa-inspect.org/h/abc..."` → `https://hook.hooktrace.io/h/abc...`
  - Ligne 259 : `data-url — full ingestor URL (e.g. https://hook.odessa-inspect.org/h/abc...)` → `hook.hooktrace.io`
  - Ligne 618 : `Custom response works end-to-end on https://app.odessa-inspect.org` → `app.hooktrace.io`

- `docs/specs/2026-05-13-v2.5-ux-product-features-design.md` (rewrite URLs) :
  - Ligne 33 : `hook.odessa-inspect.org/h/stripe-test` → `hook.hooktrace.io/h/stripe-test` (et l'autre occurrence sur la même ligne)

- `docs/specs/2026-05-11-webhook-inspector-design.md` (banner uniquement — pas d'URL à réécrire) :
  Ajouter un banner en haut :
  ```markdown
  > **Historical note (2026-05-16)** : Ce document décrit le design originel V1.
  > Voir `docs/launch/2026-05-15-launch-plan.md` pour le pivot V3 observability.
  > Domaine actuel = `hooktrace.io` (subdomains `app.` + `hook.`), pas `odessa-inspect.org`.
  ```

**Conséquence pour T8** : le grep de vérification ne doit **pas** retourner ces deux specs V2/V2.5 (URLs rewrites). Si tu changes d'avis et préfères le mode "snapshot historique avec banner" pour les V2/V2.5, mets-le explicitement ici et adapte T8 en conséquence.

### Step 5: CONTRIBUTING.md (vérifier conventions)

Lire `CONTRIBUTING.md` et confirmer que les conventions matchent l'état réel (uv, Fly, pre-commit, etc.). Aucune URL `odessa-inspect.org` n'y devrait être, mais vérifier.

### Step 5b: CLAUDE.md (domain section)

Modifier `CLAUDE.md` :
- Ligne 48 : `Production domain: odessa-inspect.org` → `Production domain: hooktrace.io`
- Ligne 49 : remplacer `app.odessa-inspect.org` → `app.hooktrace.io` et `hook.odessa-inspect.org` → `hook.hooktrace.io` dans la description des deux CNAMEs

### Step 5c: SECURITY.md (3 corrections critiques)

Modifier `SECURITY.md` — c'est la page sécurité publique du repo, elle doit refléter l'état Phase 0 :
- Ligne ~25 (out-of-scope) : `app.odessa-inspect.org` → `app.hooktrace.io`
- Ligne ~26 : `Issues already documented in the roadmap as known gaps (rate limiting, WAF — planned for V4)` → réécrire en `Issues already addressed by the launch hardening (rate limiting + Cloudflare WAF in place since V3 public launch)` — le rate limit et WAF ne sont plus "planned for V4", ils sont prérequis Phase 0
- Lien GitHub Security Advisories : adapter selon décision T3 (transfer vers `hooktrace-io/hooktrace` ou rester sur `quaxsze/webhook-inspector`)

### Step 5d: .github files

- **`.github/workflows/deploy.yml`** : lignes 31-32 (smoke test URLs)
  - `APP_URL="https://app.odessa-inspect.org"` → `https://app.hooktrace.io`
  - `INGESTOR_URL="https://hook.odessa-inspect.org"` → `https://hook.hooktrace.io`
- **`.github/ISSUE_TEMPLATE/bug.yml`** : ligne ~51
  - `Live instance (app.odessa-inspect.org)` → `Live instance (app.hooktrace.io)`

### Step 5e: README.md roadmap (V3 + V4 rows)

Le launch plan a tranché : Forward Pro = 1 URL (multi-target = Team), et rate limit + WAF sont en Phase 0 prérequis (pas V4). Le README roadmap doit refléter ça sinon le messaging produit reste contradictoire :

Modifier `README.md` lignes 226-227 :
- **V3 row** :
  - Avant : `Forward webhook to target(s) — URL + worker + dead-letter queue + exponential retry + idempotency keys`
  - Après : `Observability pivot — HMAC validation (9 services) + per-integration view + schema drift + replay + OTEL timeline + forward to 1 target URL (Pro) with retry + DLQ`
- **V4 row** :
  - Avant : `Rate limiting + Cloudflare WAF custom rules + Memorystore Redis (distributed counters)`
  - Après : `Production hardening — multi-region read replicas + HA Postgres pair + formal SLOs + transform JSONata (Pro) + multi-target fan-out (Team)`

(Rate limit + WAF sont retirés de V4 car ils sont en Phase 0 — sinon le message au lecteur reste "ça arrive plus tard" alors qu'on les annonce comme acquis dans le pitch launch.)

### Step 6: Run lint + smoke test rendering

```bash
cd /Users/stan/Work/webhook-inspector
uv run pytest tests/integration/web -q  # render tests should still pass
```

### Step 7: Commit

Tous les fichiers touchés par les steps 1-5e doivent être stagés. La commande ci-dessous matche **exactement** la liste des fichiers modifiés. Vérifier avec `git status` que rien ne traîne avant le commit.

```bash
git add README.md \
        CLAUDE.md \
        SECURITY.md \
        CONTRIBUTING.md \
        src/webhook_inspector/web/app/templates/landing.html \
        src/webhook_inspector/web/app/templates/viewer.html \
        .github/workflows/deploy.yml \
        .github/ISSUE_TEMPLATE/bug.yml \
        docs/specs/2026-05-11-webhook-inspector-design.md \
        docs/specs/2026-05-13-v2-custom-response-and-observability-design.md \
        docs/specs/2026-05-13-v2.5-ux-product-features-design.md

git status  # sanity: nothing else untracked/modified

git commit -m "chore(brand): rebrand odessa-inspect.org → hooktrace.io with subdomain mapping"
```

Mapping complet des fichiers touchés (pour audit) :

| Step | Fichier | Type de changement |
|---|---|---|
| 1 | `README.md` | URLs + diagramme + roadmap V3/V4 + badges (selon T3) |
| 2 | `src/webhook_inspector/web/app/templates/landing.html` | brand + URLs |
| 3 | `src/webhook_inspector/web/app/templates/viewer.html` | brand (lang reste fr — traité en T6) |
| 4 | `docs/specs/2026-05-13-v2-custom-response-and-observability-design.md` | URLs (rewrite) |
| 4 | `docs/specs/2026-05-13-v2.5-ux-product-features-design.md` | URLs (rewrite) |
| 4 | `docs/specs/2026-05-11-webhook-inspector-design.md` | banner historique (pas d'URL) |
| 5 | `CONTRIBUTING.md` | vérif (souvent inchangé) |
| 5b | `CLAUDE.md` | domain section L48-49 |
| 5c | `SECURITY.md` | URLs + claim V4 rate limit/WAF + lien GH security |
| 5d | `.github/workflows/deploy.yml` | smoke URLs L31-32 |
| 5d | `.github/ISSUE_TEMPLATE/bug.yml` | live instance L51 |
| 5e | `README.md` | (déjà ci-dessus — roadmap V3/V4 rows) |

**DoD T5 :** Toutes les URLs `odessa-inspect.org` remplacées par le bon subdomain (`app.` ou `hook.`) selon la surface. Specs historiques annotées. Tests intégration web verts.

---

## T6 — viewer.html i18n (Code)

Tâche petite mais distincte de T5 pour clarté du diff. **T7 ne peut pas exposer le nouveau domaine tant que T6 n'est pas merged** — sinon le viewer reste partiellement en français sur `app.hooktrace.io`.

### État actuel (audité 2026-05-16)

Le seul fichier template avec du français : `src/webhook_inspector/web/app/templates/viewer.html`. **Une seule chaîne** à traduire (vérifié via grep diacritiques + apostrophes contractées) :

- L2 : `<html lang="fr">` → `<html lang="en">`
- L16 : `URL d'ingestion :` → `Ingestion URL:` (caractères français : apostrophe contractée `d'` — un grep "mots français courts" comme `\bde\b|\ble\b|\bla\b` **passe à côté** de cette chaîne, d'où le besoin d'une liste explicite)

Pas d'autre fichier touché. `request_fragment.html`, `landing.html`, et le reste sont déjà en anglais.

### Step 1: Apply changes (liste précise)

Modifier `src/webhook_inspector/web/app/templates/viewer.html` :
```diff
-<html lang="fr">
+<html lang="en">
```
```diff
-        URL d'ingestion :
+        Ingestion URL:
```

(Si une future modification de `viewer.html` introduit du français entre temps, refaire le step 2 de détection avant de commit.)

### Step 2: Verification — détection diacritiques + apostrophes contractées

```bash
cd /Users/stan/Work/webhook-inspector
grep -rnE "[àâéèêëïîôûùüç]|\b[dlnsmqct]'[a-zA-Zé]" src/webhook_inspector/web/app/templates/ || echo "(none — clean)"
```

Cette commande utilise deux signaux robustes :
- **Diacritiques** (`àâéèêëïîôûùüç`) — couvre toutes les voyelles accentuées + cédille
- **Apostrophes contractées** (`d'`, `l'`, `n'`, `s'`, `m'`, `qu'`, `c'`, `t'`) — c'est par là que `URL d'ingestion` passait au travers du grep précédent

Expected output : `(none — clean)`. Si un hit reste, c'est qu'une chaîne FR persiste.

### Step 3: Render check

```bash
cd /Users/stan/Work/webhook-inspector
uv run pytest tests/integration/web/test_viewer_render.py -v
```
Expected : test passe (le viewer rend toujours bien, juste avec `lang="en"` + label anglais).

### Step 4: Commit

```bash
git add src/webhook_inspector/web/app/templates/viewer.html
git commit -m "chore(viewer): lang=en + translate 'URL d'ingestion' → 'Ingestion URL'"
```

**DoD T6 :**
- `lang="en"` dans `viewer.html`
- `URL d'ingestion :` remplacé par `Ingestion URL:`
- `grep -rnE "[àâéèêëïîôûùüç]|\b[dlnsmqct]'[a-zA-Zé]" src/webhook_inspector/web/app/templates/` retourne vide
- Test render passe

---

## T7 — DNS cutover odessa → hooktrace (Ops)

À faire **après T4 (certs Fly en place pour hooktrace.io)** et **après T5 (rebrand) déployé** (sinon les visiteurs sur hooktrace.io voient l'ancien brand). Idéalement le même jour pour minimiser le delta.

### Step 1: Deploy le rebrand sur Fly

Une fois T5 mergé sur main, le workflow `deploy.yml` redéploie automatiquement. Vérifier que les apps Fly servent le nouveau brand :

```bash
# Force la résolution via les certs hooktrace.io pour anticipation
curl --resolve app.hooktrace.io:443:66.241.124.237 -fsS https://app.hooktrace.io/ | grep -o "<h1[^>]*>[^<]*</h1>"
# Expected: <h1>hooktrace</h1>
```

### Step 2: Capture le snapshot DNS avant flip

```bash
dig +short CNAME app.odessa-inspect.org
dig +short CNAME hook.odessa-inspect.org
# Expected: webhook-inspector-web.fly.dev. / webhook-inspector-ingestor.fly.dev.
```

### Step 3: Couper `odessa-inspect.org` net

Aucun utilisateur réel = pas de redirect 301 (cf. décision 2 du launch plan).

- [ ] Cloudflare DNS panel → supprimer les CNAMEs `app.odessa-inspect.org` et `hook.odessa-inspect.org`
- [ ] Cloudflare → supprimer les TXT `_acme-challenge.app.odessa-inspect.org` et `_acme-challenge.hook.odessa-inspect.org` s'il en reste
- [ ] Fly : `fly certs remove app.odessa-inspect.org --app webhook-inspector-web` et idem pour `hook.`
- [ ] Laisser `odessa-inspect.org` se renouveler ou expirer à son tour — décision selon coût annuel et risque squatting (un nom de domaine expiré peut être racheté par quiconque).

### Step 4: Sanity check post-cutover

```bash
# Old domain should not resolve
dig +short CNAME app.odessa-inspect.org
# Expected: empty

# New domain serves Fly
curl -fsS https://app.hooktrace.io/health
curl -fsS https://hook.hooktrace.io/health
# Expected: {"status":"healthy",...}

# Apex 301 works
curl -sI https://hooktrace.io/ | head -3
# Expected: HTTP/2 301 + location: https://app.hooktrace.io/
```

**DoD T7 :** DNS public sert hooktrace.io, ancien domaine ne résout plus, apex 301 vers app. (mDNS local peut être stale jusqu'à 5 min — c'est OK).

---

## T8 — Verification + sanity (Code)

### Step 1: Final grep — rien de stale (avec allowlist explicite)

```bash
cd /Users/stan/Work/webhook-inspector
grep -rln "odessa-inspect" . \
  --exclude-dir=.git \
  --exclude-dir=.venv \
  --exclude-dir=__pycache__ \
  --exclude-dir=terraform-legacy
```

> Note : `grep --exclude-dir` matche des **noms de dossiers (basenames)**, pas des chemins. `--exclude-dir=infra/terraform-legacy` est interprété comme un literal et ne filtre rien. On exclut donc `terraform-legacy` (basename — en pratique seul `infra/terraform-legacy/` chez nous porte ce nom).

**Allowlist permanente** (snapshots historiques + meta-documents qui décrivent le rebrand) — doivent toujours apparaître :

- `docs/launch/2026-05-15-launch-plan.md` — décrit l'état actuel `odessa-inspect.org` à migrer
- `docs/superpowers/plans/2026-05-15-migrate-to-fly-io.md` — plan archive de la migration GCP → Fly
- `docs/superpowers/plans/2026-05-15-phase-minus-1-brand-cleanup.md` — ce plan documente le rebrand
- `docs/plans/2026-05-13-v2-custom-response-and-observability.md` — plan V2 historique (figé)
- `docs/plans/2026-05-13-v2.5-ux-product-features.md` — plan V2.5 historique (figé)

**Allowlist conditionnelle** — selon le mode choisi en T5 pour les specs V2/V2.5 :

- Mode **"rewrite"** (URLs remplacées par hooktrace, L6/139/259/618 + L33 modifiées) → ces fichiers **ne doivent PAS** apparaître dans la sortie grep
- Mode **"snapshot historique"** (banner ajouté en haut + URLs laissées telles quelles) → ces fichiers **doivent** apparaître

Si tu vois `docs/specs/2026-05-13-v2-custom-response-and-observability-design.md` dans la sortie alors que tu as fait le rewrite (ou inversement) = state inconsistent, retourne à T5.

**Tout autre fichier dans la sortie** (README.md, SECURITY.md, CLAUDE.md, landing.html, viewer.html, deploy.yml, bug.yml, ou n'importe quel autre fichier de production) = oubli, retourne à T5/T5x pour fixer.

### Step 2: Final grep — rien en français résiduel

```bash
cd /Users/stan/Work/webhook-inspector
grep -rn 'lang="fr"' src/
```
Expected : aucun hit.

### Step 3: Render check global

```bash
cd /Users/stan/Work/webhook-inspector
uv run pytest tests/integration -q
```
Expected : tous verts.

### Step 4: Crawl sanity sur prod

```bash
# Verifier le contenu brand servi par les 2 apps en prod
curl -fsS https://app.hooktrace.io/ | grep -o 'hooktrace\|webhook-inspector\|odessa' | sort -u
# Expected: just "hooktrace"

curl -fsS https://hook.hooktrace.io/health | jq
# Expected JSON shape (cf. src/webhook_inspector/web/ingestor/routes.py:28):
# {
#   "status": "healthy",
#   "checks": {
#     "database": "ok",
#     "blob_storage": "ok"
#   }
# }
```

### Step 5: Update launch plan

Modifier `docs/launch/2026-05-15-launch-plan.md` pour marquer Phase -1 comme **✅ DONE** :
- Ajouter en haut de la section Phase -1 :
  ```markdown
  > ✅ **DONE** — exécutée 2026-MM-JJ. Cf. `docs/superpowers/plans/2026-05-15-phase-minus-1-brand-cleanup.md` pour le détail.
  ```
- Commit : `docs(launch): mark Phase -1 as done`

**DoD T8 :** Aucun grep résiduel suspect, tests verts, prod sert le bon brand sur les bons subdomains, launch plan mis à jour.

---

## Self-review checklist

### Coverage vs launch plan Phase -1

- ✅ Achat domaine + comptes (T1, T2)
- ✅ Décision GitHub repo (T3)
- ✅ DNS + Fly certs (T4, T7)
- ✅ Rebrand massif files (T5)
- ✅ viewer.html i18n (T6)
- ✅ Verification final (T8)

### Placeholder scan

- T3 a 3 options avec branches d'exécution distinctes — pas un placeholder, c'est une vraie décision à prendre une fois.
- T1 demande de vérifier la dispo X/Twitter `@hooktrace` manuellement — pas un placeholder, c'est une limitation tooling (WebFetch bloqué par X).

### Risques

| Risque | Mitigation |
|---|---|
| `hooktrace.io` racheté entre maintenant et T1 | Acheter dans les 24h après lecture du plan |
| Cert Let's Encrypt qui traîne (T4) | Vérifier `fly certs check` à 5 min puis à 15 min ; si toujours pending → re-créer les CNAMEs `_acme-challenge.*` |
| Tests integration web cassés par les nouveaux brand strings | T5 step 6 puis T8 step 3 attrappent ; si fail → grep `webhook-inspector` dans les tests + adapter snapshot |
| odessa-inspect.org expiré racheté par squatter post-coupure | Renouveler 1 an défensif avant de couper, ou accepter — pas de users à protéger |

---

## Notes finales

- **Ordre rigide** : T1 → T2 → T3 → T4 (en parallèle T5 + T6) → T7 → T8. T4 dépend de T1 (domaine). **T7 dépend de T4 ET T5 ET T6** — sans T5, branding stale sur le nouveau domaine ; sans T6, viewer FR exposé sur `app.hooktrace.io`. T5 et T6 peuvent être faits en parallèle mais les deux doivent être merged avant T7.
- **T1 + T2 sont les seules tâches "ouvrir un navigateur"** ; toutes les autres sont CLI/code.
- **Phase 0 PR1 ne démarre qu'après T8 done** — sinon `SECRETS_ENCRYPTION_KEY` (T2) manque, certs hooktrace pas en place, etc.
- **Side-project rythme** : 1 semaine si étalé sur soirées + un week-end. Full focus : 1-2 jours.
- **Pas de migration DB ni de feature regression** — Phase -1 est strictement additive côté code jusqu'à T7. **T7 reste un vrai cutover prod** (suppression CNAMEs `odessa-inspect.org` + révocation certs Fly), donc risque DNS/cert non nul mais borné et rollbackable : recréer les CNAMEs sur Cloudflare et `fly certs add app.odessa-inspect.org --app webhook-inspector-web` (+ idem hook.) ramène l'ancien domaine en service en ~quelques minutes. Vu l'absence d'utilisateurs réels, le coût d'un T7 raté = temps de redéploiement DNS, pas d'indisponibilité visible.
