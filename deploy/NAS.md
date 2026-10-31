# Héberger VALO//LAB sur un NAS

Le projet est prêt pour tourner en permanence dans un conteneur Docker sur le
réseau local : données persistantes, redémarrage automatique et synchronisation
quotidienne.

> **Important — pas d'authentification.** Le dashboard n'a pas de compte ni de
> mot de passe. Il est prévu pour un réseau personnel de confiance. Ne redirige
> jamais le port `8765` depuis Internet et ne l'expose pas via QuickConnect.
> Pour un accès à distance, utilise Tailscale/WireGuard ou un reverse proxy avec
> authentification.

---

## 1. Ce que fait le conteneur

- Sert l'interface sur le port interne `8765`.
- Stocke `config.json` et `valorant.db` dans `/data`, monté sur `./data` par défaut.
- Redémarre tout seul (`restart: unless-stopped`).
- Vérifie sa santé via `/api/health`.
- Relance une synchronisation toutes les 30 minutes si les données ont plus de
  24 h : aucun cron à configurer.
- Fonctionne sur NAS **x86_64** et **ARM64** (l'image Python est multi-architecture).

Fichiers ajoutés au projet :

```text
Dockerfile
docker-compose.yml
env.example  (→ à copier en .env si besoin)
.dockerignore
deploy/NAS.md
```

---

## 2. Prérequis

- Docker (ou Container Manager sur Synology DSM 7.2+).
- Le NAS et tes appareils sur le même réseau local, ou un VPN.
- Le port `8765` libre sur le NAS.
- Un dossier persistant pour les données, par exemple :
  - Synology : `/volume1/docker/valolab`
  - QNAP : `/share/Container/valolab`
  - TrueNAS : `/mnt/<pool>/apps/valolab`
  - Unraid : `/mnt/user/appdata/valolab`

Évite de placer `data/` sur un partage SMB/NFS : SQLite préfère un volume local.

Selon le NAS, les commandes Docker doivent être préfixées par `sudo` (Synology
notamment) si ton utilisateur SSH n'a pas les droits Docker.

---

## 3. Démarrage rapide (SSH + Docker Compose)

Copie le projet sur le NAS, puis depuis le dossier du projet :

```bash
cp env.example .env
# facultatif : adapter le port, le fuseau horaire ou le chemin des données
docker compose up -d --build
```

Sur les NAS plus anciens, la commande peut être `docker-compose` (avec un tiret).

Vérifications :

```bash
docker compose ps
docker compose logs --tail=100
curl http://127.0.0.1:8765/api/health
```

Puis, depuis un autre appareil du réseau :

```text
http://IP_DU_NAS:8765
```

Remplace `IP_DU_NAS` par l'adresse locale du NAS (par exemple `192.168.1.20`).
Réserve une adresse IP fixe (bail DHCP) pour le NAS afin que l'URL ne change
pas. Configure ton Riot ID et ta clé API HenrikDev dans **Réglages**, puis lance
une synchronisation. La démo éventuelle est supprimée automatiquement.

### Variables disponibles (`.env`)

```dotenv
VALO_PORT=8765          # port exposé sur le NAS
TZ=Europe/Paris         # fuseau horaire des logs
VALO_DATA_PATH=./data   # dossier persistant (relatif ou absolu)
```

Le port interne du conteneur reste toujours `8765`. Si `8765` est déjà utilisé
sur le NAS, change seulement `VALO_PORT` (par exemple `9000`) et ouvre
`http://IP_DU_NAS:9000`.

---

## 4. Synology — Container Manager (interface graphique)

1. Installe **Container Manager** depuis le Centre de paquets.
2. Crée un dossier partagé, par exemple `docker/valolab`.
3. Copie dedans `app.py`, `valorant/`, `static/`, `Dockerfile`,
   `docker-compose.yml` et `.dockerignore` (File Station, ou `scp`).
4. Dans **Container Manager → Projet → Créer** :
   - choisis le dossier `docker/valolab` ;
   - sélectionne `docker-compose.yml` ;
   - lance la construction, puis démarre le projet.
5. Ouvre `http://IP_DU_NAS:8765`.

Container Manager redémarre le projet au boot du NAS tant que le paquet est
activé. Les données restent dans `docker/valolab/data`.

Si tu veux modifier le port ou le fuseau horaire, crée un fichier `.env` à côté
de `docker-compose.yml` (copie de `env.example`) avant de démarrer le projet.

---

## 5. QNAP, TrueNAS, Unraid

Le même `docker-compose.yml` fonctionne :

- **QNAP** : Container Station → Applications → créer une application avec le
  `docker-compose.yml` du dossier.
- **TrueNAS SCALE** : Applications → Custom App, ou `docker compose` en SSH.
- **Unraid** : plugin Docker Compose Manager, ou `docker compose` en SSH.

Adapte simplement `VALO_DATA_PATH` vers un chemin persistant du NAS.

---

## 6. Récupérer l'historique déjà présent sur ton Mac

Le conteneur démarre avec une base vide (et la démo) tant que tu ne copies pas
tes données. Pour conserver ton historique et tes réglages :

```bash
# arrête d'abord le dashboard local sur le Mac (Ctrl+C) pour une copie cohérente
scp -rp data admin@IP_DU_NAS:/volume1/docker/valolab/
```

Ou via File Station : copie `data/valorant.db` et `data/config.json` dans
`docker/valolab/data/`.

Le fichier `config.json` contient ta clé API en clair : transfère-le sur le
réseau local, garde-le en `0600` et ne le publie jamais.

Si le conteneur tourne déjà, arrête-le avant de remplacer la base :

```bash
docker compose stop
# copier data/
docker compose start
```

---

## 7. Accès, sécurité et nom de domaine local

### Rester sur le réseau local

- Ne fais **aucune redirection de port** `8765` sur la box.
- Désactive QuickConnect / l'accès distant pour ce service.
- Sur Synology : **Panneau de configuration → Sécurité → Pare-feu**, autorise
  TCP `8765` uniquement depuis ton sous-réseau local (ex. `192.168.1.0/24`).
- Toute personne sur le LAN peut voir les statistiques et modifier les réglages.

### Accès à distance recommandé

- **Tailscale** ou **WireGuard** sur le NAS : l'app reste non exposée à Internet
  et tu y accèdes via l'adresse VPN.
- Ou un reverse proxy avec authentification (Nginx Proxy Manager, Caddy,
  Traefik, reverse proxy Synology) **et** HTTPS.

### Reverse proxy

Utilise un **nom d'hôte dédié**, par exemple `valo.home.arpa`, pas un
sous-dossier. L'application utilise des chemins absolus (`/api/...`,
`/static/...`) et ne fonctionne pas correctement derrière un sous-chemin sans
réécriture.

Exemple Synology : **Panneau de configuration → Portail de connexion →
Avancé → Proxy inverse** :

- source : `https://valo.home.arpa` (443)
- destination : `http://127.0.0.1:8765`
- HTTP/1.1, sans WebSocket nécessaire.

---

## 8. Mise à jour

```bash
cd /volume1/docker/valolab
# remplacer les fichiers (git pull, File Station, scp...)
docker compose up -d --build
```

Les données de `data/` ne sont pas touchées. Pour forcer la reconstruction sans
cache :

```bash
docker compose build --no-cache
docker compose up -d
```

---

## 9. Sauvegarde et restauration

La base SQLite est en mode WAL : arrête le conteneur pour une copie cohérente.

```bash
cd /volume1/docker/valolab
docker compose stop
tar czf /volume1/backups/valolab-$(date +%F).tgz data
docker compose start
```

Restauration :

```bash
docker compose stop
tar xzf valolab-YYYY-MM-DD.tgz -C /volume1/docker/valolab
docker compose start
```

La sauvegarde contient `config.json` et donc la clé API : conserve-la dans un
endroit privé.

---

## 10. Dépannage

| Symptôme | Piste |
| --- | --- |
| Le conteneur redémarre en boucle | `docker compose logs --tail=200` ; vérifie le port et les permissions de `data/`. |
| `permission denied` sur `/data` | Le dossier doit être inscriptible par l'utilisateur du conteneur. Par défaut il tourne en root ; voir la section ci-dessous pour un UID non-root. |
| Page inaccessible depuis le LAN | Vérifie `docker compose ps`, le pare-feu du NAS, le sous-réseau, puis `curl http://IP_DU_NAS:8765/api/health`. |
| Le port 8765 est pris | Change `VALO_PORT` dans `.env`, puis `docker compose up -d`. |
| `docker compose` introuvable | Essaie `docker-compose`. |
| Erreur de clé API | Vérifie le Riot ID, la région et la clé dans **Réglages**. |
| Le NAS dort | Garde Docker/Container Manager actif ; le conteneur reprend au réveil. |

### Faire tourner le conteneur avec un UID non-root (optionnel)

Par défaut, le conteneur tourne en root **à l'intérieur de son espace isolé**,
ce qui évite les problèmes de permissions des dossiers partagés Synology. Pour
utiliser l'utilisateur du NAS :

```yaml
services:
  valolab:
    user: "1026:100"   # id -u et id -g de l'utilisateur sur le NAS
```

Puis :

```bash
sudo chown -R 1026:100 data
docker compose up -d
```
