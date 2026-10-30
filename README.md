# VALO//LAB — dashboard local de performances VALORANT

Tableau de bord local qui récupère ton historique de parties VALORANT (via l'API
communautaire HenrikDev) et le transforme en statistiques lisibles : KDA, ACS,
ADR, win rate par agent, par map et par côté attaque / défense, avec une lecture
automatique de tes points forts et des axes à travailler.

Tout tourne sur ta machine. Pas de compte à créer, pas de serveur distant, pas de
Node : un seul processus Python et une base SQLite dans `./data`.

```
python3 app.py
```

---

## 1. Ce que tu obtiens

| Onglet | Contenu |
| --- | --- |
| **Vue d'ensemble** | WR, K/D, KDA, ACS, ADR, HS %, rounds, tendance ACS/partie, forces & faiblesses, 10 dernières parties |
| **Agents** | Win rate, K/D, KDA, ACS, ADR, HS %, WR attaque / défense et indice de performance par agent |
| **Maps** | Même chose par map + graphique de win rate |
| **Attaque / Défense** | Win rate de round par côté, K/D et ACS par côté, écart par map et par agent |
| **Parties** | Historique filtrable (map, agent, file) avec score, K/D/A, ACS et rounds gagnés par côté |

Filtres disponibles partout : **mode** (tactique / toutes / file précise) et
**période** (30 jours, 90 jours, 6 mois, tout).

### Comment sont calculés les indicateurs

- **K/D** = kills / morts · **KDA** = (kills + assists) / morts
- **ACS** = score de combat moyen par round · **ADR** = dégâts infligés par round
- **HS %** = têtes / (têtes + corps + jambes)
- **WR ATK / DEF** = % de rounds gagnés quand tu joues ce côté (pas le win rate des parties)
- **Indice** : 45 % ACS + 30 % K/D + 25 % win rate, ramené sur une échelle où
  100 = ta moyenne. Il sert uniquement à classer les agents et les maps entre eux ;
  les petits échantillons sont signalés par une pastille de fiabilité.
- **Forces & faiblesses** : le moteur compare chaque agent, map et côté à ta moyenne,
  pondère l'écart par la taille de l'échantillon, puis propose une action concrète.
  Une faiblesse n'est affichée que si elle a assez de rounds ou de parties derrière elle.

---

## 2. Prérequis

- **Python 3.9 ou plus** (testé sur macOS, fonctionne aussi sous Linux).
- Un navigateur récent.
- Une **clé API HenrikDev gratuite** (voir ci-dessous).
- Aucune dépendance Python externe : uniquement la bibliothèque standard.

Vérifier la version :

```bash
python3 --version
```

---

## 3. Obtenir ta clé API HenrikDev (gratuite)

L'API HenrikDev est communautaire et non officielle. Elle demande désormais une
clé, même pour l'offre gratuite :

1. Rejoins le Discord **HenrikDev** et vérifie ton compte.
2. Dans le salon `#get-a-key`, choisis **VALORANT (Basic Key)**.
3. Copie la clé obtenue (elle ressemble à une longue suite de caractères).
4. Le plan gratuit autorise **30 requêtes par minute** — largement suffisant ici,
   le dashboard attend automatiquement entre deux appels.

Ouvre ensuite le dashboard, clique sur l'icône ⚙ (en haut à droite) et renseigne :

- **Nom Riot** et **TAG** : par exemple `MonPseudo` et `EUW` pour `MonPseudo#EUW`
  (le `#` n'est pas à saisir).
- **Région** : `eu`, `na`, `ap`, `kr`, `latam` ou `br`.
- **Plateforme** : `PC` (ou `Console`).
- **Clé API HenrikDev**.
- **Profondeur d'historique** : nombre de parties récentes à récupérer à chaque
  synchronisation (40 par défaut, 100 maximum).

Clique sur **Tester la connexion** pour valider le Riot ID et la clé, puis sur
**Enregistrer & synchroniser**.

> La clé est stockée en clair dans `./data/config.json` avec des permissions
> restreintes (`0600`). Elle ne quitte jamais ta machine et n'est jamais renvoyée
> au navigateur. Tu peux aussi la fournir via la variable d'environnement
> `HENRIK_API_KEY` (elle est alors prioritaire et n'est pas écrite sur disque).

---

## 4. Lancement et rafraîchissement

```bash
python3 app.py
```

Le dashboard s'ouvre sur <http://127.0.0.1:8765> (le port suivant est essayé
automatiquement s'il est occupé).

- **Au démarrage** : si la dernière synchronisation date de plus de 24 h, une
  synchronisation se lance en arrière-plan. L'interface reste utilisable pendant
  ce temps et se met à jour toute seule.
- **Toutes les 30 minutes** : le serveur revérifie la fraîcheur des données et
  relance une synchronisation si elles ont plus de 24 h. Tu peux donc laisser le
  dashboard ouvert en permanence.
- **Bouton « Synchroniser »** : relance une récupération à tout moment.
- Une synchronisation complète (`Récupérer plus d'historique` dans les réglages)
  retélécharge aussi les parties déjà connues.

Options utiles :

```bash
python3 app.py --port 9000        # changer le port
python3 app.py --no-browser       # ne pas ouvrir le navigateur
python3 app.py --no-sync          # ne pas synchroniser au démarrage
```

Le serveur n'écoute que sur `127.0.0.1` : il n'est pas accessible depuis le réseau.

### Mode démo

Sans Riot ID configuré, le dashboard génère au premier lancement un jeu de
**90 parties fictives** (déterministe) pour que tous les écrans soient utilisables
immédiatement. Ces données sont clairement signalées par un bandeau. Elles sont
supprimées automatiquement à la première vraie synchronisation, ou manuellement
via `Effacer la démo`.

---

## 5. Où vont les données

```
data/
├── config.json     # Riot ID, région, profondeur d'historique, clé API (0600)
└── valorant.db     # base SQLite : parties, rounds, profil
```

Supprimer le dossier `data/` remet le dashboard à zéro (démo incluse).
Aucune donnée n'est envoyée ailleurs qu'à l'API HenrikDev, en lecture seule.

---

## 6. Tests

```bash
python3 -m unittest discover -s tests -v
```

La suite couvre :

- `tests/test_parser.py` — normalisation des parties v4 et attribution du côté
  attaque/défense (rôle de l'équipe gagnante, plant, defuse, kill feed) ;
- `tests/test_analytics.py` — agrégations globales / agents / maps / côtés,
  filtres de mode et de période, génération des insights ;
- `tests/test_demo.py` — déterminisme et cohérence du jeu de démonstration
  (scores VALORANT valides, rounds, dates passées) ;
- `tests/test_henrik.py` — construction des requêtes, en-tête d'authentification,
  erreurs 401/404/429 et reprises réseau (réseau simulé) ;
- `tests/test_api.py` — serveur HTTP réel sur un port éphémère : endpoints JSON,
  réglages, blocage du path traversal, effacement/rechargement de la démo.

Aucun test ne contacte le réseau ni ne touche à `./data`.

---

## 7. Dépannage

| Symptôme | Cause probable / solution |
| --- | --- |
| « Clé API refusée » | Clé invalide ou révoquée : régénère-la sur le Discord HenrikDev. |
| « Compte ou partie introuvable » | Riot ID mal orthographié ou mauvaise région (`eu` pour l'Europe, etc.). |
| « Limite de requêtes atteinte » | Plan gratuit limité à 30 req/min : attends une minute, la reprise est automatique. |
| Synchronisation très lente | Chaque page de 10 parties prend ~2 s (respect de la limite). Réduis la profondeur d'historique. |
| Pas de stats attaque/défense | Certaines parties anciennes n'exposent pas le côté par round : elles comptent dans le total mais pas dans le découpage ATK/DEF. |
| Le port 8765 est occupé | Le serveur essaie les 20 ports suivants ; l'URL réelle est affichée au démarrage. |
| Données de démo encore visibles | Lance une synchronisation réelle ou clique sur « Effacer la démo ». |

---

## 8. Structure du projet

```
app.py                  # lanceur : port, navigateur, sync auto, seed de démo
valorant/
├── config.py           # chemins, lecture/écriture de config.json (0600)
├── db.py               # schéma SQLite et requêtes
├── henrik.py           # client HTTP HenrikDev (auth, retries, rate limit)
├── parser.py           # normalisation v4 + inférence attaque/défense
├── sync.py             # synchronisation en arrière-plan, profil, rang
├── analytics.py        # agrégations et moteur d'insights
├── demo.py             # jeu de données de démonstration déterministe
├── web.py              # serveur HTTP local + API JSON
└── version.py
static/                 # HTML / CSS / JS sans build, polices auto-hébergées
tests/                  # suite unittest
data/                   # créé au premier lancement (non versionné)
```

L'interface n'utilise ni framework ni bundler : `static/app.js` et
`static/style.css` sont servis tels quels, les polices Barlow sont embarquées dans
`static/fonts/` pour fonctionner hors ligne.

---

Projet personnel, vibe codé à des fins pédagogiques, non affilié à Riot Games. VALORANT est une marque de Riot Games, Inc.
Les données proviennent de l'API communautaire HenrikDev.
