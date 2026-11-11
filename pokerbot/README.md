# pokerbot : bots de No-Limit Hold'em qui apprennent en jouant

Projet de recherche **en simulation uniquement**. Il ne se connecte à aucun site ni à aucune application de poker en argent réel.

L'architecture et le plan complet sont dans [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

| Étape | Contenu | État |
|---|---|---|
| 1 | Moteur NLHE (HU et 6-max), side pots, SQLite, tests | ✅ |
| 2 | Adversaires low stakes (station, nit, maniac, ABC) | à venir |
| 3 | Bot MCCFR + exploitation + apprentissage continu | à venir |
| 4 | Échelle de niveaux, évaluation duplicate | à venir |
| 5 | Dashboard, jeu dans le terminal et sur le web | à venir |

## Installation

```bash
cd pokerbot
pip install -e ".[dev]"      # eval7, numpy, pytest
```

## Tests

```bash
python -m pytest -q
```

## Simuler des mains (étape 1 : bots aléatoires)

```bash
# 3 mains heads-up, affichées en entier
python -m pokerbot simulate --players 2 --hands 3 --show 3

# 20 000 mains 6-max, sauvegardées dans SQLite et dans un historique texte
python -m pokerbot simulate --players 6 --hands 20000 --db data/hands.db --log data/hands.txt

# résultats par joueur, puis une main précise
python -m pokerbot results --db data/hands.db
python -m pokerbot show 42 --db data/hands.db --bb
```

## Utiliser le moteur depuis Python

```python
from pokerbot.engine import HandState, Action, format_hand

s = HandState([10_000, 10_000], button=0)        # heads-up, 100 bb, blindes 50/100
while not s.is_over:
    legal = s.legal_actions()                    # call_amount, min_raise_to, max_raise_to…
    s.apply(legal.check_or_call())               # ou Action.raise_to(300), Action.fold()…
print(format_hand(s.to_record(["alice", "bob"])))
```

Un bot hérite de `pokerbot.bots.Agent` et implémente `act(view) -> Action`, où `view` contient uniquement ce que le joueur a le droit de voir. Le hook `on_hand_end(seat, record)` reçoit la main complète, ce qui permet l'apprentissage.

## Conventions

- Jetons entiers : 1 bb = 100 jetons. Le tapis de départ est de 100 bb, avec recave automatique à chaque main.
- `Action.raise_to(x)` : `x` est la mise totale du joueur **sur la rue**, et non l'incrément. Une mise d'ouverture (bet) est un raise quand personne n'a encore misé.
