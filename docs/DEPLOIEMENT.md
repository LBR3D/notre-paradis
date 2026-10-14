# Déploiement sur le serveur (accès privé Tailscale)

L'application tourne sur un petit serveur loué et n'est **visible que de vos appareils** grâce à Tailscale (réseau privé chiffré). Rien n'est exposé sur Internet.

## 1. Louer le serveur

Par exemple chez Hetzner (Cloud), OVH ou Scaleway :

- 4 vCPU, **8 Go de RAM**, 160 Go de disque (les données IGN sont volumineuses) ;
- Ubuntu 24.04 ;
- ajoutez votre clé SSH à la création.

## 2. Installer Docker et Tailscale

Connecté en SSH au serveur :

```bash
curl -fsSL https://get.docker.com | sh
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up            # ouvre un lien pour relier le serveur à votre compte Tailscale
tailscale ip -4              # note l'adresse 100.x.y.z
```

Installez aussi l'application Tailscale sur votre PC et votre téléphone, avec le même compte.

## 3. Pare-feu

Seuls SSH et Tailscale doivent être ouverts :

```bash
sudo ufw allow OpenSSH
sudo ufw allow in on tailscale0
sudo ufw enable
```

## 4. Installer l'application

```bash
git clone https://github.com/<vous>/notre-paradis.git
cd notre-paradis
cp .env.example .env
nano .env        # POSTGRES_PASSWORD, APP_BIND=100.x.y.z (adresse Tailscale), clés API
docker compose up -d --build
```

Ouvrez `http://100.x.y.z:8000` depuis votre PC ou votre téléphone (Tailscale actif). Astuce : dans la console Tailscale, activez « MagicDNS » pour utiliser `http://nom-du-serveur:8000`.

## 5. Sauvegardes

La base contient l'historique des annonces, irremplaçable. Sauvegarde quotidienne :

```bash
crontab -e
# ajouter :
30 3 * * * cd ~/notre-paradis && docker compose exec -T db pg_dump -U paradis paradis | gzip > ~/sauvegardes/paradis-$(date +\%F).sql.gz && find ~/sauvegardes -mtime +30 -delete
```

(`mkdir ~/sauvegardes` avant.) Pensez aussi à activer les sauvegardes automatiques proposées par l'hébergeur.

## Mise à jour

```bash
cd ~/notre-paradis && git pull && docker compose up -d --build
```
