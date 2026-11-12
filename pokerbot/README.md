# pokerbot : des bots de No-Limit Hold'em qui apprennent en jouant

Projet de recherche **en simulation uniquement**. Il ne se connecte à aucun site ni à aucune application de poker en argent réel.

| Étape | Contenu | État |
|---|---|---|
| 1 | Moteur NLHE (heads-up et 6-max) : side pots, SQLite, historique texte | ✅ |
| 2 | Adversaires low stakes : aléatoire, calling station, nit, maniac, ABC | ✅ |
| 3 | Bot MCCFR (Linear CFR) + abstraction + exploitation + versions | ✅ (heads-up) |
| 4 | Échelle de niveaux, évaluation duplicate avec IC 95 % | ✅ (Slumbot : expérimental) |
| 5 | Jeu dans le terminal et sur le web avec explications, tableau de bord | ✅ |
| v2 | Deep CFR, résolution de sous-jeux en temps réel, MCCFR 6-max | à faire |

L'architecture détaillée est dans [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Installation

```bash
cd pokerbot
pip install -e ".[dev]"          # eval7, numpy, pytest ; Python 3.10+
python -m pytest -q              # 54 tests
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

## Limites connues (honnêtes)

- La stratégie CFR est **heads-up**. En 6-max, le bot l'utilise quand il ne reste que deux joueurs. Au préflop multiway et dans les coups hors de l'arbre abstrait, il joue avec des règles ABC (ranges et équité), ajustées par l'exploitation. L'explication indique toujours lequel des deux modes il utilise.
- L'abstraction est volontairement petite pour un entraînement sur un PC : le bot est solide face aux profils simples, mais loin d'un bot de recherche comme Slumbot.
- Rejouer des mains réelles ne met pas les regrets CFR à jour directement : ce n'est pas l'algorithme. Les mains jouées servent aux modèles d'adversaires, et la stratégie progresse par self-play.

## Conventions

- Jetons entiers : 1 bb = 100 jetons. Tapis de 100 bb, recave à chaque main.
- `Action.raise_to(x)` : `x` est la mise totale du joueur sur la rue, et non l'incrément.
- Un bot hérite de `pokerbot.bots.Agent` et implémente `act(view) -> Action`. Le hook `on_hand_end(seat, record)` reçoit la main complète.
