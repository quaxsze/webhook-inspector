# Launch plan — webhook observability service

> Plan d'exécution pour transformer webhook-inspector en service public reconnu, avec voie de monétisation SaaS différée. Pivot stratégique : positionner le projet comme **la couche d'observabilité gratuite pour webhooks**, pas comme un n-ième clone de webhook.site.

## Sommaire

- [Positionnement](#positionnement)
- [État actuel — où on en est vraiment](#état-actuel--où-on-en-est-vraiment)
- [Décisions à prendre AVANT exécution](#décisions-à-prendre-avant-exécution)
- [Phase -1 — Brand & docs consistency (1 semaine)](#phase--1--brand--docs-consistency-1-semaine)
- [Phase 0 — Pivot produit (10-11 semaines)](#phase-0--pivot-produit-10-11-semaines)
- [Phase 1 — Customer discovery (1 semaine)](#phase-1--customer-discovery-1-semaine)
- [Phase 2 — Soft launch (2 semaines)](#phase-2--soft-launch-2-semaines)
- [Phase 3 — Show HN + launch officiel (1 jour + 1 semaine)](#phase-3--show-hn--launch-officiel-1-jour--1-semaine)
- [Phase 4 — Croissance SEO programmatique (mois 2-12)](#phase-4--croissance-seo-programmatique-mois-2-12)
- [Phase 5 — Monétisation (mois 9-18)](#phase-5--monétisation-mois-9-18)
- [Anti-abuse — prérequis non-négociables](#anti-abuse--prérequis-non-négociables)
- [KPIs](#kpis)
- [Free vs Paid tier](#free-vs-paid-tier)
- [Kill criteria](#kill-criteria)

---

## Positionnement

**Une phrase, à figer et à coller partout :**

> The free observability layer for webhooks — capture, debug, replay. From localhost to production.

### Pourquoi cet angle et pas un autre

| Concurrent | Ce qu'ils font | Ce qu'ils ne font pas |
|---|---|---|
| **webhook.site** | Capture + view dev/debug, gratuit illimité | Pas de replay, pas de forward, pas de métriques, pas de signature validation built-in, rétention 7j fixe |
| **Hookdeck** | Webhook infra production-grade, retry, DLQ, observability. Free tier 5k events/mo + $20/mo entry | Signup obligatoire, pas de URL anonyme zero-friction pour quick test, payant rapidement |
| **Svix** | Webhook sending/receiving infra. Free tier 50k msg/mo + $25/mo entry | Idem Hookdeck : signup-first, focus émetteur webhook plus que receveur observability |
| **smee.io / ngrok** | Tunnel localhost → URL publique | Pas de persistence, pas de replay, pas d'observabilité |
| **RequestBin** | Capture + view (mort/abandonné depuis 2020) | Idem webhook.site mais sans maintenance |

Le **trou de marché** : aucun outil ne combine **zero-friction (URL sans signup) + observabilité runtime (HMAC validation, schema inference, OTEL timeline) + replay/forward**. webhook.site couvre la première dimension, Hookdeck/Svix la seconde. On joue le **chevauchement des deux**.

### Avantage tactique : c'est visuel

Un screenshot d'une **timeline OTEL "Stripe webhook flow — DB write 12ms, R2 offload 38ms, response 8ms, signature ✓"** se vend en un coup d'œil. C'est imbattable côté "Show HN frontpage" face à du texte "open-source webhook tester".

---

## État actuel — où on en est vraiment

Avant de lister les "décisions à prendre", calage de l'état réel du repo au moment de l'écriture (vérifié contre le code, pas contre le souvenir).

### Déjà fait ✅ (ne pas re-décider)

#### Vérifiable depuis le repo (snapshot au commit `f48543c`)

- **Storage blob = Cloudflare R2** (`config.py` : `BLOB_STORAGE_BACKEND` accepte `s3`, adapter présent en `infrastructure/storage/s3_blob_storage.py`).
- **Observabilité OTLP** configurée côté code (`config.py:otlp_endpoint`, exporters branchés dans `observability/tracing.py` et `metrics.py`).
- **Repo public** sur GitHub (`quaxsze/webhook-inspector` — visible via badges README).
- **Licence MIT** (`LICENSE` à la racine).
- **CI/CD `flyctl deploy` sur push main** (`.github/workflows/deploy.yml`).
- **Features V1 + V2 + V2.5** : create endpoint, viewer live (SSE), search tsvector, export JSON, custom response (status/body/headers/delay), vanity slugs.
- **Stack Fly versionnée** : `infra/fly/{db,web,ingestor}.fly.toml` + `infra/fly/README.md`.

#### Vérifié manuellement le 2026-05-15 — à re-vérifier si stale

> Ces faits dépendent d'un état runtime / cloud externe et ne sont pas auto-vérifiables depuis un `git clone`. À traiter comme snapshot daté ; si tu reprends ce plan dans 3 mois, re-confirmer via `fly status` / `dig` / dashboard Honeycomb avant d'agir.

- Prod déployée sur Fly.io : `webhook-inspector-web` + `-ingestor` + `-db` en région `cdg` (vérifié via `fly status` post-cutover).
- Domaine `odessa-inspect.org` live : CNAMEs `app.` et `hook.` pointent sur Fly, certs Let's Encrypt issued.
- Honeycomb **non wired** en prod (env var `OTLP_ENDPOINT` pas posée sur les Fly apps) — runtime fallback console capture les spans dans `fly logs`.
- Migration GCP → Fly **terminée**, projet GCP `webhook-inspector-stan-dev` en `DELETE_REQUESTED` (soft-delete 30 jours).

### Pas encore fait, à acter en Phase 0 🟡

| Composant | État courant | Cible V3 |
|---|---|---|
| Rétention | `endpoint_ttl_days = 7` (`config.py`), cleaner purge à 7j | 30 jours pour free, 90j Pro, 1 an Team |
| Anti-abuse | Juste `max_body_bytes` côté ingestor — pas de rate limit, pas de WAF rules, pas de détection abuse | Cloudflare WAF + rate limit Redis (IP + endpoint) + flag pour review humain sur endpoints suspects (pas de freeze auto en V3, risque faux positifs) |
| Schéma DB | Tables `endpoints` + `requests` V2.5 uniquement | + `signature_status`, `detected_integration`, `detected_event_type`, `schema_drift`, `trace_summary`, + tables `replays`, `forwards`, `inferred_schemas` |
| HMAC built-in | Aucun | 9 services (cf. V3 spec) |
| Replay / Forward / Transform | Aucun | F2, F5, F6 du V3 spec |
| Per-integration view | Aucun | F3 du V3 spec |
| Schema inference | Aucun | F4 du V3 spec |
| OTEL timeline UI | Backend OK, pas de surface dans le viewer | F7 du V3 spec |
| Branding | `webhook-inspector` partout dans le code | Cible `hooktrace` (cf. décision domaine) |
| Langue UI | Landing en anglais, viewer `lang="fr"` | 100% anglais |
| README architecture | Diagramme top encore Cloud Run/Cloud SQL/Cloud Trace | Diagramme Fly + R2 + OTLP |

### Conséquences pour Phase 0

L'écart entre l'état actuel et le pitch V3 est **bien plus large que 60-80h**. Chiffrage détaillé en [section Phase 0](#phase-0--pivot-produit-10-11-semaines) — résumé : **~10-11 semaines solo full-time** (V3 features F1-F7 + extras Phase 0 anti-abuse/landing + buffer). C'est ce chiffrage qui prime, pas l'estimation initiale optimiste.

---

## Décisions à prendre AVANT exécution

À acter **dans la première semaine de Phase 0** :

### 1. Choix du domaine — ✅ DÉCIDÉ : `hooktrace.io`

Disponibilité vérifiée le 2026-05-15 :
- Domaine `.io` : libre (WHOIS "Domain not found")
- Bluesky `hooktrace.bsky.social` : libre
- npm `hooktrace`, PyPI `hooktrace` : libres
- GitHub @hooktrace : **squatté par un compte dormant** (créé 2026-01-28, 0 repos, 0 followers, no bio). Workaround → utiliser l'**org `hooktrace-io`**. Tenter un reclaim auprès de GitHub Support après janvier 2027 (policy d'inactivité ≥ 12 mois).
- X/Twitter @hooktrace : à vérifier manuellement (https://x.com/hooktrace)

**Coût estimé** : ~$45-50/an chez Cloudflare Registrar (at-cost wholesale `.io`). Pricing exact à valider sur https://www.cloudflare.com/products/registrar/.

**À acheter immédiatement avant qu'un squatter ne le prenne** :
- Domaine `hooktrace.io` chez Cloudflare Registrar (intégration native avec la zone DNS déjà chez Cloudflare)
- Créer GitHub org `hooktrace-io`
- Réserver Bluesky `hooktrace.bsky.social`
- Réserver npm `hooktrace`, PyPI `hooktrace`
- Réserver X/Twitter @hooktrace si dispo

### 2. Sortie du domaine actuel `odessa-inspect.org` + topologie subdomains

Domaine actuellement live + CNAMEs `app.` et `hook.` pointent sur Fly. **Aucun utilisateur réel** — donc pas de redirect 301 à mettre en place. Un 301 serait de toute façon mauvais sur l'ingestor (POST/PUT/PATCH webhooks) : beaucoup de providers ne suivent pas le redirect proprement, et un 301 peut réécrire la méthode HTTP côté client.

**Topologie `hooktrace.io`** : l'app web doit vivre sur `app.hooktrace.io` (pas sur l'apex) parce que `web/app/routes.py:71:hook_base_url()` réécrit `://app.` → `://hook.` pour générer les URLs de webhook retournées par l'API. Sans ce préfixe `app.`, les tokens créés via le viewer pointeraient sur le mauvais host.

L'apex `hooktrace.io` lui-même sert juste de **301 → `https://app.hooktrace.io/`** (via Cloudflare Page Rule, gratuit). Pas de landing distincte côté apex en V3 — éventuellement un site marketing statique séparé en V4+ si le pitch SEO le demande, mais YAGNI pour le launch.

Procédure complète :

1. Acheter `hooktrace.io` chez Cloudflare Registrar
2. Configurer Cloudflare Page Rule : `hooktrace.io/*` → 301 `https://app.hooktrace.io/$1`
3. Attacher Fly : `fly certs add app.hooktrace.io --app webhook-inspector-web` et `fly certs add hook.hooktrace.io --app webhook-inspector-ingestor`
4. Créer les CNAMEs Cloudflare `app.hooktrace.io` → `webhook-inspector-web.fly.dev` et `hook.hooktrace.io` → `webhook-inspector-ingestor.fly.dev` (proxy OFF, gris)
5. Smoke test via `curl --resolve` puis via DNS public
6. **Couper `odessa-inspect.org` net** : retirer les CNAMEs `app.odessa-inspect.org` et `hook.odessa-inspect.org` chez Cloudflare ; révoquer les certs Fly (`fly certs remove app.odessa-inspect.org` etc.). Laisser le domaine expirer à son renouvellement naturel.

> Note "Odessa" : potentiellement problématique géopolitiquement vu le contexte 2022+ (ville d'Ukraine). Argument supplémentaire pour la sortie.

### 3. Langue du repo + landing — décision quasi-acquise mais à finaliser

État actuel : repo, README, commits → **déjà en anglais**. Landing template → **en anglais**. **Mais viewer `lang="fr"`** (cf. `web/app/templates/viewer.html:2`). Inconsistance à corriger en Phase -1.

Décision à figer : **100% anglais** (cible international). Tickets GitHub idem, déjà la norme.

### 4. Stratégie OSS — **changement de licence à considérer séparément**

> ⚠️ Le repo est **déjà publié en MIT** (`LICENSE` à la racine). Ce n'est pas une décision neuve mais une **proposition de changement de licence**. Implications à arbitrer dans un doc dédié (`docs/launch/license-change.md` à créer si tu retiens l'option) :
> - Tout code mergé avant la bascule reste accessible sous MIT (le passé ne peut pas être révoqué).
> - Les contributeurs externes qui ont déjà push sous MIT doivent re-accepter sous AGPL → CLA rétroactif difficile.
> - L'option "MIT + commercial license sur features Pro" (modèle Posthog) reste valable et n'oblige pas à changer la licence du code historique.

Proposition à arbitrer (pas à exécuter sans réflexion séparée) :

- **Option A (status quo)** : rester en MIT. Risque de fork commercial mitigé par le fait que le service-as-a-service est petit, dépend du free tier + brand + DX. Pragma plausible pour un side-project qui devient public.
- **Option B (AGPL-3.0 going forward)** : nouvelles contributions sous AGPL via CLA. Code historique reste MIT — donc forkers ont toujours une base MIT à exploiter. Bénéfice marginal.
- **Option C (MIT + commercial features)** : code OSS reste MIT, certaines features (forward, transform, alerts) sous licence commerciale séparée (cf. Posthog). Demande effort juridique mais cohérent.

**Action** : ne PAS bouger la licence en Phase 0. Trancher séparément en mois 6+ quand un signal de PMF apparaît. Avant ça, la question est prématurée.

### 5. Co-founder marketing ou solo

Acter explicitement avant Phase 2. Sans co-founder distribution, viser un objectif plus modeste (€2-5k MRR plafond) et tagger ça dans le kill criteria.

---

## Phase -1 — Brand & docs consistency (1 semaine)

Prérequis **avant** de toucher au produit. La comm interne du repo est aujourd'hui incohérente — l'arch diagram du README parle encore de Cloud Run / Cloud Trace, la landing est en anglais mais le viewer en `lang="fr"`, le branding mélange `webhook-inspector` (code), `odessa-inspect` (URLs dans tout le repo), et `hooktrace` (cible). Avant tout marketing externe, on aligne.

### Checklist — remplacement systématique odessa-inspect.org → hooktrace.io

À faire **après l'achat du domaine** (décision 1) et **avant Phase 0**.

> **Règle de substitution** : le mapping n'est PAS uniforme. Trois cibles distinctes selon le contexte d'usage :
>
> - **`app.hooktrace.io`** — surface app : viewer HTML, routes API `/api/endpoints/*`, OG metadata, liens depuis README/docs vers l'app
> - **`hook.hooktrace.io`** — surface ingestor : URLs de webhook `/h/{token}` retournées aux utilisateurs, exemples curl qui simulent un sender
> - **`hooktrace.io`** (apex) — uniquement en prose marketing/brand ("hosted by hooktrace.io", "open-source at hooktrace.io"). Jamais dans une URL fonctionnelle, l'apex est un 301 vers `app.`
>
> Réécrire un curl webhook `https://app.odessa-inspect.org/h/...` (le `/h/` indique surface ingestor) doit donc devenir `https://hook.hooktrace.io/h/...`, **pas** `https://app.hooktrace.io/h/...`.

Mapping ligne par ligne :

- [ ] **README.md** :
  - Ligne 118 : `App: https://app.odessa-inspect.org` → `App: https://app.hooktrace.io` (surface app)
  - Ligne 119 : `Ingestor (webhook target): https://hook.odessa-inspect.org` → `Ingestor (webhook target): https://hook.hooktrace.io` (surface ingestor)
  - Ligne 132 : `curl -X POST https://app.odessa-inspect.org/api/endpoints` → `app.hooktrace.io` (API surface app)
  - Ligne 155 : `curl -X POST https://app.odessa-inspect.org/api/endpoints` → `app.hooktrace.io` (idem)
  - Ligne 170 : `curl "https://app.odessa-inspect.org/api/endpoints/$TOKEN/requests?q=..."` → `app.hooktrace.io` (API surface app)
  - Ligne 185 : `curl -OJ "https://app.odessa-inspect.org/api/endpoints/$TOKEN/export.json"` → `app.hooktrace.io` (API surface app)
  - Redessiner l'architecture diagram (haut du fichier) pour refléter Fly + R2 + OTLP. Garder la mention historique Cloud Run uniquement sous la roadmap V2.6.
  - Statut badges (lignes 3-4) : pointer vers le nouveau repo si transfert (cf. tâche GitHub ci-dessous)
  - Ligne 236 : lien GitHub Security Advisories → nouveau repo si transfert

- [ ] **src/webhook_inspector/web/app/templates/landing.html** :
  - Ligne 6 : `<title>webhook-inspector — ...</title>` → `<title>hooktrace — ...</title>` (brand, pas d'URL)
  - Ligne 10 : `og:title content="webhook-inspector"` → `hooktrace` (brand)
  - Ligne 13 : `og:url content="..."` → `https://app.hooktrace.io/` (URL canonical de l'app — l'apex 301-redirect vers cette URL)
  - Ligne 23 : `<h1>webhook-inspector</h1>` → `<h1>hooktrace</h1>` (brand)
  - Ligne 140 : exemple `https://hook.odessa-inspect.org/h/AbCdEf...` → `https://hook.hooktrace.io/h/AbCdEf...` (surface ingestor — c'est une URL de webhook)
  - Ligne 144 : idem ligne 140
  - Ligne 152 : lien `github.com/quaxsze/webhook-inspector` → nouveau repo si transfert

- [ ] **src/webhook_inspector/web/app/templates/viewer.html** : passer `lang="fr"` → `lang="en"`, traduire les 3-4 strings statiques restantes, harmoniser le H1 sur `hooktrace` (brand, pas d'URL)

- [ ] **docs/specs/2026-05-13-v2-custom-response-and-observability-design.md** :
  - Ligne 6 : `https://app.odessa-inspect.org` (prose de contexte) → `https://app.hooktrace.io` (surface app)
  - Ligne 139 : `"url": "https://hook.odessa-inspect.org/h/abc..."` (exemple payload API) → `https://hook.hooktrace.io/h/abc...` (surface ingestor — c'est une URL de webhook retournée à l'utilisateur)
  - Ligne 259 : `data-url — full ingestor URL (e.g. https://hook.odessa-inspect.org/h/abc...)` → `hook.hooktrace.io` (surface ingestor)
  - Ligne 618 : `Custom response works end-to-end on https://app.odessa-inspect.org` → `app.hooktrace.io` (surface app)
  - Si tu juges cette doc historique (V2 design figé), tu peux à la place ajouter en haut un banner "snapshot V2 — domaine actuel = hooktrace.io (app./hook. subdomains)" et laisser les URLs telles quelles. Décision à toi.

- [ ] **docs/specs/2026-05-13-v2.5-ux-product-features-design.md** :
  - Ligne 33 : `hook.odessa-inspect.org/h/stripe-test` et `hook.odessa-inspect.org/h/k7Hq3...` → `hook.hooktrace.io` (surface ingestor — user story d'URL webhook)

- [ ] **docs/specs/2026-05-11-webhook-inspector-design.md** : banner historique "design originel — voir docs/launch/ pour le pivot V3"

- [ ] **CONTRIBUTING.md** : vérifier que les conventions matchent l'état réel (uv, Fly, etc.)

> **Vérification post-rebrand** : lancer `grep -rn "odessa-inspect" .` à la fin doit retourner uniquement les fichiers archivés dans `infra/terraform-legacy/` et les commits historiques git log. Tout autre hit = ligne oubliée.

### Checklist — migration identité GitHub

État actuel : repo `github.com/quaxsze/webhook-inspector`, org perso, badges + liens README + landing y pointent. Le plan a déjà acté la création de l'org `hooktrace-io`. Reste à décider du sort du repo lui-même :

- [ ] **Décision** : trois options, choisir UNE
  - **Option A — Transfer repo** : `gh repo transfer quaxsze/webhook-inspector hooktrace-io/webhook-inspector` puis rename → `hooktrace-io/hooktrace`. GitHub maintient automatiquement les redirects (URLs `quaxsze/webhook-inspector` → `hooktrace-io/hooktrace`) pour les `git clone`/`gh` mais **PAS** pour les liens README/badges qui restent broken jusqu'à update. Risque : tu perds le link entre le compte perso et le projet (stars portées au compte transféré).
  - **Option B — Fork + archive** : créer `hooktrace-io/hooktrace` comme fork repropre, archive `quaxsze/webhook-inspector` en read-only avec un lien sticky vers le nouveau repo. Perd l'historique de stars mais clean break.
  - **Option C — Rester sur `quaxsze`** : repo perso, brand projet sur le domaine + org GitHub `hooktrace-io` pour les éventuels sub-projects (SDK, CLI...). Pragma pour solo dev, mais incohérence brand visible.
- [ ] Une fois la décision prise, **update tous les badges + liens** vers la nouvelle URL canonical du repo (cf. checklist README + landing ci-dessus)

### Effort

**~1 semaine** solo, ou en parallèle de Phase 0 si tu peux multitasker — mais commencé **AVANT Phase 1** (customer discovery), sinon les interviewés tombent sur des incohérences. La migration GitHub elle-même est rapide (~30 min) mais demande de réfléchir à l'option A/B/C en amont.

---

## Phase 0 — Pivot produit (10-11 semaines)

Objectif : avoir un produit qui **mérite** le pitch "observability layer" avant tout marketing. Décomposition détaillée en table plus bas — résumé :

| Composante | Source | Durée |
|---|---|---|
| F1-F7 features (dev pur) | V3 spec | 7 sem |
| Phase 0 extras (anti-abuse + landing) | propre launch | 2 sem |
| Buffer review/bugs/intégration | réaliste solo | 1-2 sem |
| **Total Phase 0** | | **10-11 sem solo full-time** |

En side-project 15h/sem ≈ **4-5 mois calendrier**.

### Features à livrer (cf. `docs/specs/2026-05-15-v3-observability-runtime-design.md`)

- [ ] **Replay** : bouton sur chaque request pour re-fire vers une URL cible
- [ ] **Forward** : config par endpoint pour relayer toutes les requests vers **1 URL** downstream avec retry exponential + DLQ. Multi-targets + fan-out repoussés au tier Team (cf. section [Free vs Paid tier](#free-vs-paid-tier)).
- [ ] **Transform** : règle JSONata par endpoint pour modifier le payload avant forward
- [ ] **Per-integration view** : grouping auto des requests par source détectée (Stripe, GitHub, Shopify, Twilio, Mailgun, Discord, Slack, PayPal, Zapier, n8n) avec compteurs + p95 latency
- [ ] **HMAC signature validation built-in** pour les 9 intégrations HMAC (PayPal en V3.5) ci-dessus (config secret par endpoint)
- [ ] **Schema inference + diff** : extract JSON schema des requests, surligne les changements
- [ ] **Timeline view** : OTEL spans visibles dans le viewer (DB write / R2 offload / HMAC check / forward / etc.)
- [ ] **Rétention 30 jours** (vs 7 actuellement)

### Anti-abuse + scaling minimum

> État actuel : l'ingestor (`web/ingestor/routes.py`) ne fait qu'un check `max_body_bytes` (413 si payload trop gros). Aucun rate limit, aucune détection abuse, aucune WAF rule. **Tout ce qui suit est à construire**, ne pas le présenter comme acquis.

- [ ] **Cloudflare WAF** activé sur le domaine. Le plan gratuit limite à 5 custom rules — suffisant pour démarrer (bot blocking + rate limit IP de base). Plan Pro ($20/mo) débloque les rules avancées (managed rulesets OWASP) — à budgéter dès qu'on dépasse 10k MAU.
- [ ] **Rate limit par IP** : 100 req/min/IP via middleware FastAPI + Redis backend. Soft block (429 avec retry-after), pas de ban permanent.
- [ ] **Rate limit par endpoint** : 1 000 req/heure pour les endpoints non-authentifiés free tier. Soft block.
- [ ] **Détection heuristique "phishing landing"** : si un endpoint reçoit > 50 requests `GET /` (humans qui cliquent) plutôt que `POST/PUT/PATCH/DELETE` (webhooks) sur une fenêtre 1h, flag pour review humain (pas de freeze auto au début — risque de faux positifs sur des webhooks GET légitimes).
- [ ] **XSS mitigation viewer** : déjà partiellement en place (`request_fragment.html` sérialise via `|tojson` en attributs `data-*`, pas d'injection inline). Audit explicite à faire pour confirmer aucune route ne render un payload directement. PAS de blocage par Content-Type — ça contredirait la promesse "inspect any webhook".
- [ ] **Slug denylist** : refuser les vanity slugs qui matchent des marques (`stripe`, `paypal`, `apple`, …) ou des mots offensants. Liste publique + appel à PR pour ajouts.
- [ ] **Process abuse@** : email forwarding + template auto-réponse + workflow Linear/GitHub Issues pour triage 24h SLA.
- [ ] **Page `/legal/abuse-report`** : formulaire qui pré-remplit un email à `abuse@`.

### Refonte communication

> Prérequis : Phase -1 (brand cleanup) traitée. Sinon le travail ci-dessous repose sur une base incohérente.

- [ ] README riche : screenshot timeline + GIF replay + quick start Docker en 3 commandes. Diagramme archi à jour (Fly + R2 + OTLP, pas Cloud Run).
- [ ] Landing page :
  - Démo live sans signup (`POST /api/endpoints` → URL utilisable immédiatement) — DÉJÀ EN PLACE, à étendre avec screenshot timeline + value proposition observability
  - Capture vidéo 30s : "Stripe webhook → timeline → replay → forward" (à enregistrer après F1+F2+F7)
  - CTA "Try a webhook now" → génère un endpoint éphémère cliquable
  - Lien GitHub avec compteur de stars visible
  - Mise à jour copie "URLs expire after 7 days" → "URLs expire after 30 days" (cohérence avec la rétention free tier acquise post F1-F7)
- [ ] Page `/docs` : Markdown statique (Astro recommandé pour SSG fast + bon SEO)
- [ ] Page `/integrations/{stripe,github,shopify,…}` : 9 pages templatisées avec exemple HMAC + payload de référence + lien doc officielle
- [ ] Légal : ToS + Privacy Policy minimaux mais réels (GDPR-compliant car Cloudflare R2 + Fly cdg) — revue rapide avocat dev-friendly ~500€ one-shot
- [ ] **Rétention 30 jours** : changement de `endpoint_ttl_days` de 7 → 30 dans `config.py`, mise à jour du cleaner, communication explicite dans landing + ToS. **C'est une feature à livrer, pas un fait acquis** — aujourd'hui `endpoint_ttl_days = 7`.

### Architecture scaling minimum

- [ ] Partitionner la table `requests` par jour (`requests_2026_05_15`, ...) pour purge sans lock
- [ ] Index sur `(endpoint_id, received_at DESC)` validé EXPLAIN ANALYZE
- [ ] Upgrade PG de `shared-cpu-1x` 1GB → `shared-cpu-2x` 4GB. Coût Fly à valider sur pricing page actuelle (estimation ~$25-35/mo, encaisse confortablement 100k req/jour)
- [ ] Volume 10GB → 50GB
- [ ] Alerts Honeycomb sur p95 latency + error rate

> Estimation cost total à 100k req/jour : ~$50-70/mo (PG + volume + 3 apps + R2 toujours $0 grâce au free tier + Honeycomb free tier 20M events). **À valider concrètement avec la pricing page Fly à jour avant de figer dans le pitch publique.**

**Investissement temps réaliste, table de chiffrage détaillée** :

| Bloc | Durée dev pur | Notes |
|---|---|---|
| F1 HMAC + F3 per-integration view + F4 schema inference | 4 sem | (1+1+2 sem, F4 schema inference inclut tooling drift) |
| F2 replay + F7 OTEL timeline | 1.5 sem | (1 + 0.5) |
| F5 forward + DLQ + worker app + Redis Upstash | 1.5 sem | nouvelle app Fly, Upstash setup |
| F6 transform JSONata | 1 sem | si garde (cf. note compression ci-dessous) |
| Anti-abuse + rate limits + WAF rules + denylist | 1 sem | spécifique launch public, pas dans V3 spec |
| Refonte landing + docs/integrations × 9 services | 1 sem | spécifique launch public |
| **Sous-total dev pur** | **10 sem** | (8 sem F1-F7 + 2 sem extras Phase 0) |
| Buffer review/bug/intégration | +1 sem | hypothèse solo full-time réaliste |
| **Total Phase 0 réaliste** | **~11 sem** | upper bound : 12 sem si imprévus |

Side-project 15h/sem ≈ **4-5 mois calendrier**.

Si compressé à <9 semaines, soit certaines features tombent (F6 transform peut glisser en V3.5, libère 1 sem), soit la qualité tests/docs souffre.

---

## Phase 1 — Customer discovery (1 semaine)

Avant de marketer, **valider que le pitch parle aux vrais users**.

### Méthode

- [ ] Trouver 15-20 devs via :
  - DM Twitter/Bluesky à des devs qui parlent souvent de Stripe/webhooks
  - r/stripe, r/webdev, r/sysadmin
  - Discord serveurs Stripe, Shopify dev
  - Anciens collègues
- [ ] Script d'interview 30 min standardisé :
  1. *"Comment debug-tu un webhook Stripe en dev aujourd'hui ?"*
  2. *"Comment monitor-tu tes endpoints webhook en prod ?"*
  3. *"Quelle est la chose la plus chiante avec les webhooks ?"*
  4. *"As-tu déjà utilisé webhook.site, Hookdeck, ngrok ? Qu'est-ce qui manque ?"*
  5. *"Si tu avais une magic feature pour les webhooks demain, ce serait quoi ?"*
  6. Montrer la landing de hooktrace.io en fin : *"À quoi ça ressemble ? Tu paierais pour le payant ?"*
- [ ] Pas de slides, pas de demo guidée. Écouter, prendre notes, surtout sur les frustrations réelles vs idées de features.

### Livrables

- [ ] Notes brutes des 15-20 entretiens (Notion/Obsidian)
- [ ] Top 5 pain points cités spontanément
- [ ] 3-5 quotes verbatim pour la landing
- [ ] Décision : si moins de 60% des interviewés s'allument sur le replay+forward → repivoter le pitch avant Phase 2

---

## Phase 2 — Soft launch (2 semaines)

Tester sur audiences niche pour ramasser bugs + feedback avant Show HN.

### Canaux

- [ ] **r/selfhosted** : angle "open-source webhook observability you can self-host"
- [ ] **Lobste.rs** : audience pointue, feedback technique sérieux (utiliser le tag `devops` ou `web`)
- [ ] **Indie Hackers** : story "building in public, here's my first launch"
- [ ] **Discord Stripe Dev + Shopify Partners** : partager comme open-source utile (pas de pub directe — règle communautaire)
- [ ] **r/devops, r/SREs** : angle "we use OTLP traces internally, here's the trace UI for our webhooks"

### Objectifs

- 100-300 premiers users actifs
- Identifier 5-10 bugs critiques
- Affiner les frictions UX (heatmaps via Plausible / Umami)
- 3-5 quotes utilisateurs supplémentaires

---

## Phase 3 — Show HN + launch officiel (1 jour + 1 semaine)

### Show HN

- **Quand** : mardi/mercredi/jeudi, 14h-16h UTC (matin Europe, début après-midi US-East)
- **Titre** : à figer au moment du launch en fonction du scope effectivement livré. Template : `Show HN: <Name> – observability for webhooks (<features>, open source)`. Substituer `<features>` par les 2-3 features réellement shippées qui sont visuellement les plus fortes — typiquement `replay, HMAC validation` si scope minimal, ou `replay, transform, forward` si F5+F6 livrés. Ne jamais inclure une feature qui a glissé en V3.5.
- **Body** : 3 paragraphes max. Problème → solution → invitation. **Aucun emoji, aucun hype**.
- **Préparer** : screenshots dans le body (Imgur), GIF démo, lien GitHub, lien doc
- **Répondre dans les 6 premières heures** à TOUS les commentaires, même les critiques (surtout les critiques)
- **Tag** : pas de "Ask HN" mention dans le titre

### Product Hunt

- Same week, 1-2 jours après Show HN si HN a marché
- **Hunters préparés** à l'avance : 5-10 personnes prévenues 48h avant
- Première image : timeline screenshot
- Description : pitch en 1 phrase + 3 bullet points

### Article blog technique

- Titre : `Building hooktrace.io: webhook observability with OpenTelemetry`
- Stack tour : FastAPI + OTEL + Honeycomb + Fly + R2
- Choix d'archi commentés honnêtement (pourquoi Fly pas Cloud Run, pourquoi self-managed PG, etc.)
- Post-mortem migration GCP → Fly (lien vers le plan public dans le repo)
- Cross-post : dev.to, Hashnode, Medium

### KPIs réalistes (PAS optimistes)

| Métrique | Floor | Target | Stretch |
|---|---|---|---|
| Show HN rank | 50e | 30e | top 10 |
| Visites jour J | 1 000 | 3 000 | 10 000 |
| GitHub stars semaine | 100 | 400 | 1 200 |
| Endpoints créés semaine | 200 | 800 | 3 000 |
| Mentions externes | 1-2 | 5 | 15 |

---

## Phase 4 — Croissance SEO programmatique (mois 2-12)

C'est ici que se joue la pérennité **du free tier**.

### Pages programmatiques (objectif 50 pages d'ici mois 6)

Templates générés depuis un YAML de config — **pas du copier-coller manuel**.

Slugs prioritaires :
- `/observe-stripe-webhooks` / `/test-stripe-webhooks`
- `/observe-github-webhooks` / `/debug-github-pull-request-webhooks`
- `/observe-shopify-webhooks` / `/test-shopify-order-webhooks`
- `/observe-twilio-webhooks` / `/test-twilio-sms-webhooks`
- `/observe-mailgun-webhooks` / `/debug-mailgun-bounce-webhooks`
- `/observe-discord-webhooks` / `/test-discord-bot-webhooks`
- `/observe-slack-webhooks` / `/test-slack-events-api`
- `/observe-paypal-webhooks` / `/debug-paypal-ipn-webhooks`
- `/observe-zapier-webhooks` / `/test-zapier-trigger-webhooks`
- `/observe-n8n-webhooks` / `/test-n8n-workflow-webhooks`
- + variantes "how to" : `/how-to-test-stripe-webhooks-locally`, `/how-to-replay-failed-github-webhooks`, `/how-to-validate-shopify-hmac`

Contenu type par page :
1. Explication du webhook du service (volume estimé, payload type, headers)
2. Payload réel JSON pretty-printé
3. URL pré-générée copy-pasteable
4. Snippets code Python/Node/Go pour tester localement
5. Walkthrough HMAC signature validation (le killer feature observability)
6. Lien vers la doc officielle (lien sortant qui rassure Google sur la légitimité)

### Pages comparatives (mois 2-3)

- `/vs/webhook-site` : honnête, mettre en avant ce que webhook.site fait mieux (notoriété, ancienneté)
- `/vs/ngrok` : positionnement différent (tunnel vs observabilité)
- `/vs/requestbin` : RIP, abandonné
- `/vs/hookdeck` : "Hookdeck is paid infra; hooktrace is the free observability layer"
- `/vs/svix` : idem
- `/alternatives` : page qui liste tous les concurrents avec recommandation contextuelle

### Blog technique

Rythme cible : **2 articles/mois**. Tous orientés "webhook observability + concrete code".

- "How HMAC validation prevents replay attacks"
- "Webhook retries: idempotency keys explained"
- "Stripe webhook event types: full reference"
- "Debugging webhook race conditions with OTEL traces"
- "Why your webhook handler times out (and how to fix it)"
- "GitHub webhook payload size limits"
- "Building a webhook DLQ in 50 lines"
- "OpenTelemetry semantic conventions for webhooks"

### Contenu communautaire

- [ ] Stack Overflow : répondre aux 50 questions top sur "webhook testing", "ngrok alternative", "stripe webhook debugging" — mentionner hooktrace seulement quand c'est la meilleure réponse
- [ ] `awesome-selfhosted` : PR pour ajout
- [ ] `awesome-devtools` : idem
- [ ] `awesome-opentelemetry` : positionner comme exemple "real-world OTEL integration"
- [ ] Sponsoring open-source projects : afficher "thanks to hooktrace" en footer de quelques projets pertinents

---

## Phase 5 — Monétisation (mois 9-18)

**Ne pas démarrer avant 10k MAU** ou 5k stars GitHub. Sinon c'est de la friction inutile sur un funnel pas encore prouvé.

### Tiers (voir [Free vs Paid tier](#free-vs-paid-tier))

### Stratégie conversion

- Lifecycle email léger : signup → onboarding J1, J7, J30 (Buttondown ou Loops)
- In-app prompts contextuels : "tu utilises 80% de ta rétention 30 jours, passe en Pro 90 jours"
- Pas de paywall agressif. **Friction = mort virale.**

### Infrastructure monétisation

- Stripe Billing (pas Paddle — MoR pas critique à ce volume)
- Page `/pricing` claire avec calculateur usage
- Self-serve uniquement au début. Sales motion = jamais avant 10 customers entrants spontanés.

---

## Anti-abuse — prérequis non-négociables

URLs publiques + zéro auth = paradis pour les abuseurs. **Sans ce bloc, ne pas lancer en Phase 2.**

### Cloudflare WAF (gratuit)

- [ ] Rules : block les bots agressifs, scrapers connus, IPs sur listes de réputation
- [ ] Rate limit : 100 req/min/IP toutes routes confondues
- [ ] Challenge JavaScript pour les `GET /` (humans) sur endpoints suspects

### Application-level

- [ ] Rate limit par token : 1 000 req/heure max sur un endpoint non-authentifié (libérable en Pro)
- [ ] Detection "endpoint comme landing phishing" : ratio GET / (POST+PUT+PATCH) anormal sur 1h → flag pour review humain (pas de freeze auto initial — risque faux positifs sur webhooks GET légitimes)
- [ ] **Audit XSS du viewer** : confirmer que `request_fragment.html` et les templates Jinja sérialisent tous les body/header user-controlled via `|tojson` (data attributes) plutôt qu'en interpolation inline. Pas de Content-Type blocking : la promesse publique reste "inspect any webhook", restreindre les content-types contredit le produit.
- [ ] Slugs vanity : denylist marques (`stripe`, `apple`, `paypal`, etc.) et mots offensants français/anglais. Liste publique versionnée + PR welcome.

### Process abuse

- [ ] Email `abuse@hooktrace.io` → ticket Linear/Notion auto-créé
- [ ] Réponse SLA 24h ouvrées (documenté publiquement)
- [ ] Page `/legal/abuse-report` template formulaire
- [ ] Log de toutes les actions admin (freeze, ban, takedown) pour audit
- [ ] DMCA agent désigné si .com US plus tard, sinon procédure EU equivalent

### Légal minimum

- [ ] Terms of Service rédigés (template GenericTOS + adapté), revue rapide par avocat dev-friendly (~500€ one-shot)
- [ ] Privacy Policy : transparence sur ce qui est capturé, où c'est stocké (Fly cdg + R2 EU), combien de temps, comment supprimer
- [ ] Cookie banner minimal si Plausible (Plausible n'a pas besoin de cookies — un avantage)

---

## KPIs

| Phase | Métrique | Plancher | Cible | Stretch |
|---|---|---|---|---|
| **0** | Features V3 livrées | 6/7 | 7/7 | 7/7 + 2 bonus |
| **0** | Anti-abuse en place | "GO" criteria | idem | idem |
| **1** | Entretiens user complétés | 12 | 18 | 25 |
| **1** | Pain points convergents | 3 | 5 | 5+ |
| **2** | MAU mois 1 | 100 | 400 | 1 000 |
| **2** | GitHub stars | 100 | 400 | 1 000 |
| **3** | Show HN rank | top 50 | top 30 | top 10 |
| **3** | Visites jour J | 1 000 | 3 000 | 10 000 |
| **3** | GitHub stars semaine | 200 | 800 | 2 000 |
| **4** | Pages SEO publiées (mois 6) | 20 | 50 | 80 |
| **4** | Trafic organique mois 6 | 2 000 | 8 000 | 25 000 |
| **4** | MAU mois 6 | 1 000 | 5 000 | 20 000 |
| **5** | MRR mois 12 | €100 | €1 000 | €5 000 |
| **5** | Conversion free→paid | 0.1% | 0.3% | 1% |

---

## Free vs Paid tier

> ⚠️ **Tarifs ci-dessous = draft v1, à valider** : (1) via les 5 dernières interviews de Phase 1 (questions explicites de willingness-to-pay sur le scope Pro), (2) en benchmarkant contre Hookdeck ($20-100/mo selon plan), Svix ($25/mo entry), Smee.io (gratuit), Mockoon Cloud ($9/mo). Ne pas figer dans la landing avant validation.

### Free (everyone, sans signup pour basique)

- ✅ Endpoints illimités
- ✅ Vanity slugs
- ✅ 30 jours rétention
- ✅ HMAC validation built-in (9 services en V3, PayPal en V3.5)
- ✅ Per-integration view + schema inference
- ✅ Search + export JSON
- ✅ Single replay manuel (button on viewer)
- ✅ OTEL timeline view
- ⚠️ 1 000 req/heure rate limit per endpoint
- ⚠️ Pas de forward / pas de transform auto / pas d'alerts

> ⚠️ La promesse "30 jours rétention free" assume que F1-F7 sont livrés ET que `endpoint_ttl_days` est passé de 7 → 30 dans `config.py`. Aujourd'hui (état repo) c'est 7 jours. À acter explicitement comme Phase 0 finale.

### Pro — €12/mo

- Tout le free **+**
- ✅ **Forward** : relayer vers 1 URL cible avec retry exponential + DLQ
- ✅ **Transform** : règle JSONata par endpoint
- ✅ **Alerts** : webhook errors, signature failures, schema drift → email/Slack
- ✅ 90 jours rétention
- ✅ 10 000 req/heure rate limit
- ✅ API tokens (lecture programmatique)
- ✅ Pas de pub / branding dans les emails outbound

### Team — €40/user/mo

- Tout le Pro **+**
- ✅ **Forward multi-targets** + fan-out
- ✅ **SSO** (Google, Microsoft, Okta SAML)
- ✅ **RBAC** (admin / dev / read-only)
- ✅ **Audit log** (qui a modifié quoi)
- ✅ **Schema validation** : règles strictes + alerts quand un payload casse le contract
- ✅ 1 an rétention
- ✅ Support email prioritaire

### Enterprise — sur devis

- Tout le Team **+**
- ✅ Self-host managed (on déploie chez vous, on opère)
- ✅ SLA 99.9% écrit
- ✅ Compliance pack (SOC2-ish, log retention 7 ans, DPA)
- ✅ Support Slack/Teams partagé

---

## Kill criteria

Acter dès **maintenant**, écrit noir sur blanc :

> Si à **12 mois après Show HN** je suis sous :
> - **1 000 GitHub stars ET**
> - **5 000 MAU ET**
> - **0 € de MRR**
>
> Alors je reconnais que le pitch ne prend pas et je redescends webhook-inspector en side-project (1h/semaine max), j'archive le repo Discord/forum, je laisse le service tourner gratuitement tant que les coûts Fly restent <€15/mo, et je passe à autre chose.

> ⚠️ Les seuils ci-dessus (1k / 5k / 0) sont des **estimations au feeling**, pas benchmarkés contre une cohorte de projets comparables. À recalibrer dès qu'on a 1-2 trimestres de données réelles post-launch (pente de stars, pente de MAU). La fonction du kill criteria n'est pas la précision du seuil, c'est l'engagement à arrêter si le signal ne vient pas.

Règle générale qui sous-tend tout ça : **un dev tool bootstrap qui n'a pas de signal de PMF à 12-18 mois n'en aura pas à 24**.

---

## Ouvertures à discuter

- **Co-founder marketing** : décision dans la première semaine de Phase 0. Solo → cap MRR à ~€3-5k, accepter. Avec co-founder → viser €20k+ MRR mais partager 30-50% equity.
- **Donations / sponsorship** : avant le paid tier (mois 6+), ouvrir un GitHub Sponsors et un OpenCollective. Pas de la monétisation sérieuse mais signal "ce projet vit".
- **Self-host docker-compose one-liner** : prioritaire dès Phase 0 pour le pitch OSS. Un `docker run hooktrace/hooktrace` qui marche en 30s.
- **Migration domaine** : `odessa-inspect.org` → `hooktrace.io`. Coupure nette (aucun utilisateur réel, pas de redirect 301 — voir décision 2).

---

## Notes finales

- **La distribution > la technique** dans cette catégorie. Tu peux avoir le meilleur produit, sans SEO+communauté tu plafonnes à 100 users.
- **L'observabilité est ton vrai moat**, pas le clone webhook.site. Capitalise ta stack OTEL/Honeycomb au max — chaque feature qui n'existerait pas sans OTEL est défensable.
- **Patience 18-24 mois** avant un éventuel €5-10k MRR. Webhook.site a mis ~10 ans pour ses $20k/mo, et c'est un produit techniquement médiocre mais distribué de manière imbattable.
- **L'angle "self-hostable" matters** : il sert le free tier (offre alternative crédible aux hosters payants), il sert la communauté (PRs externes), et il neutralise la critique "vendor lock-in" sur Show HN. Sa cohérence avec un éventuel changement de licence (cf. décision 4 postponée mois 6+) est un point à arbitrer à ce moment-là, pas un acquis.
