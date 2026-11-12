# pokerbot : des bots de No-Limit Hold'em qui apprennent en jouant

Projet de recherche **en simulation uniquement**. Il ne se connecte à aucun site ni à aucune application de poker en argent réel.

| Étape | Contenu | État |
|---|---|---|
| 1 | Moteur NLHE (heads-up et 6-max) : side pots, SQLite, historique texte | ✅ |
| 2 | Adversaires low stakes : aléatoire, calling station, nit, maniac, ABC | ✅ |
| 3 | Bot MCCFR (Linear CFR) + abstraction + exploitation + versions | ✅ |
| 4 | Échelle de niveaux, évaluation duplicate avec IC 95 % | ✅ |
| 5 | Jeu dans le terminal et sur le web avec explications, tableau de bord | ✅ |
| Cash | Rake, tapis qui persistent, profondeurs 50/100/200 bb, évaluation en conditions cash | ✅ |
| 6-max | Stratégie préflop MCCFR à 6 joueurs + stratégie HU pour les pots à deux | ✅ |
| Recherche | Résolution de la river en temps réel (ranges reconstruites + CFR+) | ✅ |
| Diffusion | Site web statique (bot dans le navigateur), client ACPC, client Slumbot | ✅ |
| v2 | Deep CFR, recherche sur flop/turn, MCCFR 6-max postflop | à faire |

L'architecture détaillée est dans [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Installation

```bash
cd pokerbot
pip install -e ".[dev]"          # eval7, numpy, pytest ; Python 3.10+
python -m pytest -q              # 70 tests
```

## 1. Entraîner le bot

```bash
# Nouvelle version (bot_v1, bot_v2…) : MCCFR sur 4 processus
python -m pokerbot train --iterations 1000000 --workers 4

# Reprendre l'entraînement de la meilleure version, avec une limite de 60 minutes
python -m pokerbot train --from best --iterations 5000000 --minutes 60

python -m pokerbot versions          # liste, niveau atteint, meilleure version (*)
python -m pokerbot set-best v1       # revenir à une version précédente (rollback)
```

Chaque version est rangée dans `models/bot_vN/` : la stratégie, les tables de regrets pour reprendre l'entraînement, l'abstraction et les métadonnées. Le dossier `models/` n'est pas versionné dans git.

Ordre de grandeur : environ 700 itérations/s sur 4 cœurs, soit 1 million d'itérations en 25 minutes environ. Plus le bot s'entraîne, plus il est fort. Des dizaines de millions d'itérations restent utiles.

## 2. Évaluer

```bash
# Match duplicate : mêmes cartes rejouées en inversant les places
python -m pokerbot match bot:best,abc --deals 10000

# Échelle de niveaux : montée uniquement si l'IC 95 % du bb/100 est > 0 sur 50 000 mains ou plus
python -m pokerbot ladder --bot latest --hands 50000

# Apprentissage continu : N cycles (entraîner depuis la meilleure version, puis passer l'échelle)
python -m pokerbot learn --rounds 3 --iterations 2000000
```

Niveaux :
1. bots simples (aléatoire, station, nit, maniac) ;
2. profils solides (ABC serré, normal, large) ;
3. anciennes versions du bot ;
4. meilleure version actuelle. Une version qui passe le niveau 4 devient la nouvelle meilleure.

Elle descend d'un niveau si la borne haute de son IC est sous 0.

Slumbot : `python -m pokerbot slumbot --hands 1000`. Ce client est **expérimental et non testé** : la machine de développement n'avait pas d'accès réseau à slumbot.com.

## 3. Jouer contre le bot

```bash
python -m pokerbot play                          # heads-up contre la meilleure version
python -m pokerbot play --opponents bot:best,abc,nit,maniac,station   # 6-max
python -m pokerbot web                           # http://127.0.0.1:8000 (table + tableau de bord)
```

Dans le terminal :

| Touche | Action |
|---|---|
| `f` | se coucher |
| `k` | checker |
| `c` | suivre |
| `h` / `p` / `d` | relancer ½ pot / pot / 2× pot |
| `a` | tapis |
| `r 7.5` | relancer à 7,5 bb |
| `?` | pourquoi le bot a joué ça |

Le bot explique chaque décision : sa main et son groupe d'équité, la ligne abstraite, les probabilités de sa stratégie CFR, les ajustements contre vous, puis l'action tirée.

Vos mains sont sauvegardées dans `data/human.db`.

## 4. Suivre les stats

```bash
python -m pokerbot dashboard            # data/dashboard.html, autonome
python -m pokerbot stats --db data/human.db
python -m pokerbot simulate --agents abc,station,nit,maniac,random,abc --hands 20000 --db data/sim.db
```

Le tableau de bord affiche :
- les versions et leur niveau ;
- le bb/100 par niveau, avec l'intervalle de confiance ;
- les progrès d'une version à l'autre ;
- les courbes de gains des évaluations ;
- vos gains ;
- le VPIP, le PFR, le 3-bet, l'AF, le c-bet, le fold to c-bet et le WTSD de chaque joueur.

## Cash game

- **Rake** : 5 % du pot, plafonné à 1 bb en heads-up, 2 bb à 3-4 joueurs et 3 bb à 5-6 joueurs. Pas de rake si le flop n'est pas vu (« no flop, no drop »). Les jetons restent conservés : seul le rake quitte la table.
- **Tapis qui persistent** : `Table(..., cash=CashRules())` garde les tapis d'une main à l'autre, avec recave quand un joueur est à sec (ou recave automatique en dessous d'un seuil).
- **Profondeurs** : depuis v3, le bot apprend trois stratégies dans le même entraînement (50, 100 et 200 bb). En partie, il choisit celle qui est la plus proche du tapis effectif.
- **Évaluation en conditions cash** : `ladder` et `match --cash` appliquent le rake et tirent un tapis entre 40 et 250 bb à chaque donne.

## 6-max

```bash
python -m pokerbot train-6max --version best --minutes 60     # MCCFR préflop à 6 joueurs
python -m pokerbot play --opponents bot:best,abc,nit,maniac,station
```

- **Préflop** : stratégie MCCFR à 6 joueurs avec open 2,5 bb, 3-bet, 4-bet et tapis.
- **Pot à deux après le flop** : le bot réutilise sa stratégie heads-up, en reconstruisant la ligne préflop équivalente.
- **Pot à 3 joueurs ou plus après le flop** : règles ABC, ajustées contre chaque adversaire.
- **Limite** : au préflop, le MCCFR 6-max suppose que le coup va jusqu'à l'abattage une fois le flop vu. Il ignore donc qu'une main jouée hors de position réalise moins bien son équité.

## Recherche en temps réel (river)

Avec `bot:best+search`, que le bot active automatiquement contre un humain, chaque décision river se déroule ainsi :
1. Le bot reconstruit les ranges des deux joueurs à partir des actions de la main.
2. Il résout le sous-jeu river en CFR+ sur les vraies combinaisons de cartes, blocages et rake compris.
3. Il joue la stratégie obtenue pour sa main.

Cela prend 1 à 2 s par décision, ce qui explique pourquoi l'échelle de niveaux tourne sans recherche par défaut.

## Mettre le bot sur un site web

```bash
python -m pokerbot build-site --out site                     # Pyodide chargé depuis le CDN jsdelivr
python -m pokerbot build-site --out site --pyodide-dir node_modules/pyodide   # tout embarqué (~15 Mo)
```

Le dossier `site/` est un site **statique** : le bot tourne entièrement dans le navigateur du visiteur, grâce à Python compilé en WebAssembly (Pyodide). Il n'y a ni serveur ni compte, et aucune donnée ne quitte la machine. Le bot se souvient du style de jeu de chaque visiteur, dans son navigateur.

Il se publie tel quel sur GitHub Pages, Netlify ou dans un sous-dossier d'un site existant, par exemple `/poker/`. Pour récupérer Pyodide en local : `npm pack pyodide@0.26.4`, puis décompresser l'archive.

Deux options pour les hébergeurs plus restrictifs :
- `--inline` : CSS et JS placés dans la page, sans balises `html`/`head`/`body` ;
- `--base64` : les `.zip` et `.gz` sont livrés en `.txt` encodés en base64, pour les hébergeurs qui refusent ces formats.

## Plateformes pour bots

Ce sont des endroits prévus pour que des bots s'affrontent (simulation, recherche, compétition) :

- **Compétitions ACPC et serveurs « dealer »** : `python -m pokerbot acpc <hôte> <port> --bot bot:best`. Protocole ACPC 2.0, heads-up no-limit, tapis de 200 bb.
- **Slumbot** : `python -m pokerbot slumbot --hands 1000`. Ce client n'a pas été testé faute d'accès réseau à slumbot.com.

Le bot ne se connecte pas aux sites de poker en argent réel. Leurs conditions d'utilisation l'interdisent, et ce serait tricher contre les autres joueurs.

## Comment le bot apprend

- **Stratégie de base (proche du GTO).** Elle est calculée par Monte Carlo CFR en external sampling avec pondération Linear CFR (option `--rm-plus` pour du regret-matching+ façon CFR+), en self-play heads-up à 100 bb.
  - Abstraction des cartes : les 169 mains préflop exactes, puis au flop, à la turn et à la river des groupes de mains de même équité (12, 10 et 8 groupes).
  - Abstraction des mises : ½ pot, pot, 2× pot et tapis.
  - Les mises réelles sont ramenées à ces tailles par *pseudo-harmonic mapping*.
- **Exploitation.** Pour chaque adversaire, le bot tient des fréquences lissées : VPIP, PFR, fold to 3-bet, fold face à une mise, agressivité, fold to c-bet.
  - Tant qu'il a peu de mains, il reste sur sa stratégie CFR. Le poids de l'ajustement est n / (n + 150).
  - Avec plus de données, il incline ses probabilités : plus de bluffs contre qui se couche trop, plus de mises de valeur contre une calling station, des calls plus larges contre un maniac. Ces ajustements sont bornés entre ×0,33 et ×3.
  - Les profils sont sauvegardés et s'enrichissent à chaque main.
- **Apprentissage continu.** Toutes les mains jouées alimentent les profils adverses. La stratégie progresse par cycles d'entraînement repris depuis la meilleure version. Une nouvelle version ne remplace la meilleure que si elle la bat en duplicate de façon statistiquement significative.

## Résultats obtenus (duplicate, 50 000 mains par niveau, IC 95 %)

| Version | Entraînement | N1 bots simples | N2 profils ABC | N4 contre la meilleure version |
|---|---|---|---|---|
| bot_v1 | 400 000 it., grand arbre, 10 min | +236 [+214, +258] ✅ | +0,4 [−12, +13] (reste) | – |
| bot_v2 | 1,94 M it., petit arbre, 35 min | +182 [+164, +201] ✅ | +48 [+37, +59] ✅ | +38 [+25, +52] contre v1 ✅ |

Avec un arbre plus petit, v2 a convergé beaucoup mieux que v1. Il bat les trois variantes d'ABC et la version précédente, ce qui en fait la meilleure version.

v1 gagne plus que v2 contre les bots très faibles (aléatoire, maniac). C'est attendu : le CFR vise l'équilibre, pas l'exploitation maximale. La couche d'exploitation compense en partie.

### Versions cash game (rake 5 %, tapis de 40 à 250 bb tirés à chaque donne)

| Version | Entraînement | N1 | N2 | N3 | N4 contre v2 |
|---|---|---|---|---|---|
| bot_v3 | 3 M it., rake, 3 profondeurs | +189 ✅ | +30 ✅ | +18 contre v1 ✅ | −12 [−25, +0,3] (reste) |
| bot_v4 | v3 + 1,5 M it. | +185 ✅ | +38 ✅ | +16 ✅ | −12 [−24, +0,2] (reste) |

v2 reste la meilleure version. Les versions entraînées avec rake sur trois profondeurs consacrent moins d'itérations à chaque profondeur et ne la battent pas encore en face-à-face. C'est la prochaine piste à creuser.

En 6-max, face à 5 profils ABC/station/nit, en duplicate et en conditions cash, le bot gagne +77 bb/100 [+36, +119]. La stratégie MCCFR préflop ne fait pas mieux que les règles ABC face à ce champ : l'écart apparié est de −9 [−47, +29], donc non significatif. Les ranges 6-max sont réalistes : UTG ouvre 13 %, BTN 40 %, et la BB défend 68 % face au bouton.

## Limites connues (honnêtes)

- En 6-max, seul le préflop a une stratégie MCCFR propre. Les pots à 3 joueurs ou plus après le flop se jouent avec les règles ABC. L'explication indique toujours quel mode le bot utilise.
- L'abstraction est volontairement petite pour un entraînement sur un PC : le bot est solide face aux profils simples, mais loin d'un bot de recherche comme Slumbot.
- Rejouer des mains réelles ne met pas les regrets CFR à jour directement : ce n'est pas l'algorithme. Les mains jouées servent aux modèles d'adversaires, et la stratégie progresse par self-play.

## Conventions

- Jetons entiers : 1 bb = 100 jetons. Tapis de 100 bb, recave à chaque main.
- `Action.raise_to(x)` : `x` est la mise totale du joueur sur la rue, et non l'incrément.
- Un bot hérite de `pokerbot.bots.Agent` et implémente `act(view) -> Action`. Le hook `on_hand_end(seat, record)` reçoit la main complète.
