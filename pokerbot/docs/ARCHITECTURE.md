# Architecture et plan

Tout se passe en simulation. Le projet ne se connecte à aucun site ni à aucune application de poker en argent réel.

## Modules

```
pokerbot/
├── engine/            ÉTAPE 1 (faite) : règles du NLHE, sans aucune IA
│   ├── cards.py       cartes = int 0..51, parsing/affichage
│   ├── evaluator.py   évaluation 5-7 cartes via eval7 (C, ~2,5 M éval/s)
│   ├── actions.py     Action (fold/check/call/raise-to) + LegalActions
│   ├── state.py       machine à états d'une main (2 à 10 joueurs)
│   ├── pots.py        pot principal, side pots, split, jeton impair
│   ├── records.py     HandRecord / ActionRecord (sérialisables JSON)
│   ├── history.py     historique texte style PokerStars + base SQLite
│   └── table.py       enchaîne les mains : bouton tournant, recave à 100 bb, seeds
├── bots/              ÉTAPES 2-3
│   ├── base.py        interface Agent : act(view) / on_hand_start / on_hand_end
│   ├── random_bot.py  aléatoire (sert aussi au fuzz-testing)
│   ├── profiles.py    calling station, nit, maniac, ABC (ranges préflop par position)
│   ├── util.py        tailles de mise, lecture de l'historique
│   ├── learner.py     bot CFR : traduction des mises, stratégie, explications
│   ├── exploit.py     modèles adverses bayésiens + ajustements bornés
│   └── registry.py    construit un agent depuis une spec ('abc', 'bot:best'…)
├── training/          ÉTAPE 3
│   ├── abstraction.py groupes de cartes par équité, tailles de mise
│   ├── abstract_game.py arbre de mises heads-up compact
│   ├── mccfr.py       MCCFR external sampling + Linear CFR, multiprocessing
│   ├── registry.py    versions bot_v1, bot_v2… (rollback, meilleure version)
│   └── run.py         entraîner / reprendre une version
├── evaluation/        ÉTAPE 4
│   ├── stats.py       VPIP/PFR/3-bet/AF/c-bet/WTSD, bb/100 avec IC 95 %
│   ├── duplicate.py   matchs duplicate (rotation des places), multiprocessing
│   ├── ladder.py      niveaux 1→4, montée et descente, base evaluations.db
│   └── slumbot.py     client API Slumbot (expérimental)
└── ui/                ÉTAPE 5
    ├── session.py     un humain à une table de bots, pas à pas
    ├── terminal.py    jouer dans le terminal
    ├── web_server.py  serveur web (bibliothèque standard uniquement)
    ├── dashboard.py   données du tableau de bord + export HTML autonome
    └── web/           play.html, dashboard.html, style.css, JS (graphiques SVG)
```

Règles de dépendance : `engine` ne dépend de rien d'autre dans le projet. `bots` s'appuie sur `engine`, et `training` sur `engine` et `bots`. `evaluation` utilise tout ce qui précède, et `ui` se contente d'afficher.

## Choix techniques

- **Jetons entiers** : 1 bb = 100 jetons, 100 bb = 10 000. On évite ainsi toute erreur d'arrondi. La conservation des jetons est vérifiée après chaque main.
- **Deux moteurs pour deux usages.**
  - Le moteur `engine` est complet et sert à jouer, à évaluer et à journaliser : environ 8 000 mains/s en heads-up et 3 000 en 6-max, par cœur, en Python pur. Avec le multiprocessing on monte à plusieurs dizaines de milliers de mains/s, ce qui suffit pour des évaluations de plusieurs millions de mains.
  - L'entraînement CFR, lui, ne tourne pas sur ce moteur. Il utilise un arbre abstrait compact (tableaux numpy et noyaux numba) qui enchaîne des millions d'itérations. Les deux moteurs partagent les mêmes règles : des tests croisés le garantiront.
- **Reproductibilité** : chaque main garde son seed. Le mode duplicate rejoue exactement le même paquet en permutant les places.

## Plan par étape

1. **Moteur** (fait) : HU et 6-max, blindes et ante, all-in, side pots, split pots, showdown, SQLite et historique texte, 34 tests unitaires et fuzz.
2. **Adversaires low stakes** (fait) : random, calling station, nit, maniac, ABC (ranges préflop par position, c-bet, value bet simple). On vérifie que leurs stats (VPIP/PFR/AF) collent au profil voulu et que l'ABC bat les autres.
3. **Bot qui apprend** (fait en heads-up ; points 6 et 7 à venir).
   1. Abstraction des cartes : buckets par EHS² au flop, à la turn et à la river, plus les 169 mains canoniques au préflop. Abstraction des mises : ½ pot, pot, 2× pot, all-in.
   2. MCCFR heads-up (external sampling, Linear CFR / DCFR), stratégie moyenne = blueprint, sauvegardée en `bot_v1`.
   3. Traduction des mises hors abstraction (pseudo-harmonic mapping).
   4. Exploitation : stats par adversaire avec a priori bayésien, puis mélange GTO ↔ meilleure réponse au modèle, pondéré par le nombre de mains observées (on reste proche du GTO tant qu'on a peu de données).
   5. Apprentissage continu : les mains jouées alimentent les profils, et le self-play reprend depuis le dernier checkpoint. Une nouvelle version n'est promue que si elle bat la précédente en duplicate.
   6. 6-max : même pipeline (MCCFR multi-joueurs, façon Pluribus).
   7. v2 : Deep CFR (PyTorch) et subgame solving en temps réel.
4. **Échelle de niveaux** (faite ; Slumbot expérimental) : L1 bots simples, L2 mélange plus solide, L3 anciennes versions, L4 meilleure version puis Slumbot, s'il est joignable (bot de recherche heads-up avec une API publique prévue pour être affronté par d'autres bots).
   - Montée : au moins 50 000 mains en duplicate, et borne basse de l'IC 95 % du bb/100 > 0.
   - Descente : borne haute < 0 au niveau supérieur sur la fenêtre glissante.
5. **Suivi et interface** (fait) : dashboard HTML (courbes, bb/100 par niveau, VPIP/PFR/AF, progrès entre versions), partie dans le terminal puis interface web, avec le bot qui explique sa décision (bucket, fréquences de la stratégie, ajustement d'exploitation).
