# Launch plan — webhook observability service

> Plan d'exécution pour transformer webhook-inspector en service public reconnu, avec voie de monétisation SaaS différée. Pivot stratégique : positionner le projet comme **la couche d'observabilité gratuite pour webhooks**, pas comme un n-ième clone de webhook.site.

## Sommaire

- [Positionnement](#positionnement)
- [Décisions à prendre AVANT exécution](#décisions-à-prendre-avant-exécution)
- [Phase 0 — Pivot produit (2-3 semaines)](#phase-0--pivot-produit-2-3-semaines)
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

## Décisions à prendre AVANT exécution

À acter **dans la première semaine de Phase 0** :

### 1. Choix du domaine

Critères : <12 caractères, prononçable, contient `hook`/`webhook` ou un signal observability, username dispo sur GitHub/Twitter/Bluesky, TLD `.dev` > `.io` > `.sh`.

| Domaine | Pour | Contre |
|---|---|---|
| **hooktrace.io** | "trace" signale OTEL/observability fortement, court | `.io` un peu daté |
| **hookwatch.io** | Signal monitoring/observability, prononçable | "watch" peut évoquer Watch (Apple) ou ngrok |
| **hookr.dev** | Court, brandable, `.dev` pour dev tool | Pas de signal observability dans le nom |
| **webhookobservability.dev** | Imbattable SEO long-tail | Trop long pour la tape-à-la-machine |

**Recommandation** : `hooktrace.io` — alignement positioning + SEO long-tail + courte.

### 2. Sortie du domaine actuel `odessa-inspect.org`

À garder ? À redirect ? À retirer ? "Odessa" peut être problématique géopolitiquement. Recommandation : 301 redirect vers le nouveau domaine pendant 6 mois, puis abandon.

### 3. Langue du repo + landing

Choix : **100% anglais**. Le marché viable est international, "EU-only privacy" est un angle plus faible que "observability for everyone". README, CHANGELOG, commits, landing → tout en anglais. Tickets GitHub idem.

### 4. Stratégie OSS

- Repo public dès Phase 0 fin.
- License : **AGPL-3.0** (pas MIT). Force les hosters concurrents à open-sourcer leurs modifs. C'est ce que fait Plausible (Posthog est MIT + commercial license sur certaines features advanced — modèle alternatif viable mais demande de l'effort juridique en plus). MIT pur serait risqué face à un AWS qui forke.
- Contributor License Agreement (CLA) géré via cla-assistant.io pour préserver la flexibilité de relicensing futur.

### 5. Co-founder marketing ou solo

Acter explicitement avant Phase 2. Sans co-founder distribution, viser un objectif plus modeste (€2-5k MRR plafond) et tagger ça dans le kill criteria.

---

## Phase 0 — Pivot produit (2-3 semaines)

Objectif : avoir un produit qui **mérite** le pitch "observability layer" avant tout marketing.

### Features à livrer (cf. `docs/specs/2026-05-15-v3-observability-runtime-design.md`)

- [ ] **Replay** : bouton sur chaque request pour re-fire vers une URL cible
- [ ] **Forward** : config par endpoint pour relayer toutes les requests vers une (ou N) URL(s) downstream avec retry exponential + DLQ
- [ ] **Transform** : règle JSONata par endpoint pour modifier le payload avant forward
- [ ] **Per-integration view** : grouping auto des requests par source détectée (Stripe, GitHub, Shopify, Twilio, Mailgun, Discord, Slack, PayPal, Zapier, n8n) avec compteurs + p95 latency
- [ ] **HMAC signature validation built-in** pour les 9 intégrations HMAC (PayPal en V3.5) ci-dessus (config secret par endpoint)
- [ ] **Schema inference + diff** : extract JSON schema des requests, surligne les changements
- [ ] **Timeline view** : OTEL spans visibles dans le viewer (DB write / R2 offload / HMAC check / forward / etc.)
- [ ] **Rétention 30 jours** (vs 7 actuellement)

### Anti-abuse + scaling minimum

- [ ] Cloudflare WAF activé sur le domaine. **Le plan gratuit limite à 5 custom rules** — suffisant pour démarrer (bot blocking + rate limit IP de base), mais le plan Pro ($20/mo) débloque les rules avancées (managed rulesets OWASP, rate limit avancé) qui deviendront utiles dès qu'on dépasse 10k MAU. À budgéter Phase 4.
- [ ] Rate limit par IP : 100 req/min/IP en headline
- [ ] Rate limit par endpoint : 10 000 req/jour pour les nouveaux endpoints non-authentifiés
- [ ] Détection heuristique "phishing landing" : si un endpoint reçoit > X requests `GET /` (humans qui cliquent) plutôt que `POST /h/...` (webhooks), flag + freeze
- [ ] Process `abuse@hooktrace.io` documenté + auto-triage des reports

### Refonte communication

- [ ] README riche : screenshot timeline + GIF replay + quick start Docker en 3 commandes
- [ ] Landing page :
  - Démo live sans signup (`POST /api/endpoints` → URL utilisable immédiatement)
  - Capture vidéo 30s : "Stripe webhook → timeline → replay → forward"
  - CTA "Try a webhook now" → génère un endpoint éphémère cliquable
  - Lien GitHub avec compteur de stars visible
- [ ] Page `/docs` : Markdown statique (Astro recommandé pour SSG fast + bon SEO)
- [ ] Page `/integrations/{stripe,github,shopify,…}` : 10 pages templatisées avec exemple HMAC + payload de référence
- [ ] Légal : ToS + Privacy Policy minimaux mais réels (GDPR-compliant car Cloudflare R2 + Fly cdg)

### Architecture scaling minimum

- [ ] Partitionner la table `requests` par jour (`requests_2026_05_15`, ...) pour purge sans lock
- [ ] Index sur `(endpoint_id, received_at DESC)` validé EXPLAIN ANALYZE
- [ ] Upgrade PG de `shared-cpu-1x` 1GB → `shared-cpu-2x` 4GB. Coût Fly à valider sur pricing page actuelle (estimation ~$25-35/mo, encaisse confortablement 100k req/jour)
- [ ] Volume 10GB → 50GB
- [ ] Alerts Honeycomb sur p95 latency + error rate

> Estimation cost total à 100k req/jour : ~$50-70/mo (PG + volume + 3 apps + R2 toujours $0 grâce au free tier + Honeycomb free tier 20M events). **À valider concrètement avec la pricing page Fly à jour avant de figer dans le pitch publique.**

**Investissement temps** : 60-80h de dev + 10h de comm/landing. Réaliste sur 3 semaines solo.

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
- **Titre** : `Show HN: Hooktrace – observability for webhooks (replay, transform, forward, open source)`
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
- [ ] Detection "endpoint comme landing phishing" : ratio GET / (POST+PUT+PATCH) anormal → freeze + email abuse pour review
- [ ] Bloquer le rendering inline de bodies HTML/JS dans le viewer — toujours afficher en `pre` text + escape
- [ ] Content-Type allowlist : refuser `text/html`, `application/javascript`, `application/xhtml+xml` en body (refus 400)
- [ ] Slugs vanity passés au denylist français/anglais des mots offensants/marques (Stripe, Apple, PayPal interdits sauf compte vérifié)

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
- **Migration domaine** : `odessa-inspect.org` → nouveau domaine. 301 pendant 6 mois.

---

## Notes finales

- **La distribution > la technique** dans cette catégorie. Tu peux avoir le meilleur produit, sans SEO+communauté tu plafonnes à 100 users.
- **L'observabilité est ton vrai moat**, pas le clone webhook.site. Capitalise ta stack OTEL/Honeycomb au max — chaque feature qui n'existerait pas sans OTEL est défensable.
- **Patience 18-24 mois** avant un éventuel €5-10k MRR. Webhook.site a mis ~10 ans pour ses $20k/mo, et c'est un produit techniquement médiocre mais distribué de manière imbattable.
- **L'angle "self-hostable" matters** : il sert le free tier (offre alternative crédible aux hosters payants), il sert la communauté (PRs externes), il neutralise la critique "vendor lock-in" sur Show HN, et il est cohérent avec AGPL.
