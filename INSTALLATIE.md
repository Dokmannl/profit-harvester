# Installatie: stap voor stap

Deze handleiding is voor iedereen, ook als je nog nooit met een Raspberry Pi of een terminal hebt gewerkt. Reken op ongeveer een uur.

**Inhoud**
1. [Wat heb je nodig?](#1-wat-heb-je-nodig)
2. [Docker installeren](#2-docker-installeren)
3. [De bot downloaden](#3-de-bot-downloaden)
4. [Instellingen invullen (.env)](#4-instellingen-invullen-env)
5. [Starten in demo-modus](#5-starten-in-demo-modus)
6. [Het dashboard openen](#6-het-dashboard-openen)
7. [Telegram koppelen (aanbevolen)](#7-telegram-koppelen-aanbevolen)
8. [E-mailrapport (optioneel)](#8-e-mailrapport-optioneel)
9. [Overstappen naar echt handelen](#9-overstappen-naar-echt-handelen)
10. [Dagelijks gebruik: stoppen, logboek, bijwerken, back-up](#10-dagelijks-gebruik)
11. [Zonder Docker (Windows, Mac of Linux)](#11-zonder-docker)
12. [Problemen oplossen](#12-problemen-oplossen)

---

## 1. Wat heb je nodig?

- **Een apparaat dat altijd aan staat.** Een Raspberry Pi 4 of 5 met Raspberry Pi OS (64-bit) is ideaal: zuinig en stil. Een pc of server met Linux, Windows of macOS kan ook.
- **Een internetverbinding.**
- **Voor echt handelen:** een Bitvavo-account. Voor de demo is dat niet nodig.
- **Optioneel:** Telegram op je telefoon, en een Gmail-account voor het dagelijkse rapport.

Alle commando's hieronder typ je in een **terminal** op de Pi. Werk je vanaf een andere computer, maak dan eerst verbinding met:

```bash
ssh <gebruikersnaam>@<ip-van-je-pi>
```

---

## 2. Docker installeren

Docker zorgt ervoor dat de bot met alles wat hij nodig heeft in een eigen "container" draait, en automatisch herstart na een stroomstoring.

Op de Raspberry Pi (of een andere Linux-computer):

```bash
curl -fsSL https://get.docker.com | sh
```

```bash
sudo usermod -aG docker $USER
```

Log daarna **uit en weer in** (of herstart de Pi), zodat je Docker zonder `sudo` kunt gebruiken. Controleer of het werkt:

```bash
docker compose version
```

Zie je een versienummer, dan is Docker klaar.

> Op Windows of macOS installeer je **Docker Desktop** via docker.com. Of sla Docker over en volg [stap 11](#11-zonder-docker).

---

## 3. De bot downloaden

```bash
sudo apt install -y git
```

```bash
git clone https://github.com/Dokmannl/profit-harvester.git profit-harvester
```

```bash
cd profit-harvester
```

Alle volgende commando's doe je vanuit deze map `profit-harvester`.

---

## 4. Instellingen invullen (.env)

Alle instellingen en wachtwoorden staan in één bestand: `.env`. Maak het aan vanuit het voorbeeld:

```bash
cp .env.example .env
```

```bash
nano .env
```

In `nano` kun je gewoon typen. Opslaan doe je met **Ctrl+O** en **Enter**, afsluiten met **Ctrl+X**.

**Minimaal nodig om te starten:**

| Instelling | Wat vul je in? |
|---|---|
| `DEMO_MODUS` | Laat op `1` staan voor de demo. |
| `DASHBOARD_TOKEN` | Het wachtwoord voor je dashboard, **minimaal 16 tekens**. Maak er een met het commando hieronder. |
| `DASHBOARD_ALLEEN_HTTPS` | Zet op `0` als je het dashboard thuis opent via `http://`. Dat is bijna altijd zo bij een eerste installatie. |

Een sterk wachtwoord maken:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Kopieer de uitkomst achter `DASHBOARD_TOKEN=` en bewaar hem ook in je wachtwoordmanager.

> **Deel je `.env` nooit** met anderen en zet hem nergens online. Hij staat al in `.gitignore`.

---

## 5. Starten in demo-modus

```bash
docker compose up -d
```

De eerste keer duurt dit een paar minuten. Daarna kijk je of de bot goed gestart is:

```bash
docker compose logs -f
```

Je ziet onder andere:

```
DEMO-MODUS actief. Nep-saldo in demo_saldo.json, data in demo_*.json
Profit Harvester V5.7 gestart. Dashboard op http://0.0.0.0:5000
```

Stoppen met meekijken: **Ctrl+C**. De bot blijft gewoon draaien.

In demo-modus werkt alles precies zoals echt, met echte koersen van Bitvavo, maar met een nep-saldo (standaard €1.000). Probeer gerust van alles: munten toevoegen, aanvullen, de pot vullen.

---

## 6. Het dashboard openen

Zoek het IP-adres van je Pi op:

```bash
hostname -I
```

Open op je computer of telefoon (in hetzelfde wifi-netwerk) de browser en ga naar:

```
http://<ip-van-je-pi>:5000
```

Log in met je `DASHBOARD_TOKEN`. Bovenaan staat **"Bitvavo · DEMO"**.

**Als app op je telefoon:** open het dashboard en kies in het browsermenu *Toevoegen aan beginscherm*.

**Van buitenaf (buiten je wifi)?** Zet de poort **niet** zomaar open in je router. Gebruik een veilige tunnel zoals [Tailscale](https://tailscale.com). Met Tailscale Funnel heb je ook https: zet dan `DASHBOARD_ALLEEN_HTTPS=1` en `VERTROUW_PROXY=1` in `.env`.

---

## 7. Telegram koppelen (aanbevolen)

Met Telegram krijg je een melding bij elke oogst en aankoop, en kun je de bot bedienen.

1. Open Telegram en zoek **@BotFather**. Stuur `/newbot` en volg de stappen. Je krijgt een **token** (een lange code met een dubbele punt erin).
2. Zoek **@userinfobot** en stuur een willekeurig bericht. Je krijgt je **chat-ID** (een getal).
3. Zoek je nieuwe bot op en stuur hem `/start`. Een Telegram-bot kan je pas berichten sturen nadat jij hem eerst een bericht hebt gestuurd.
4. Vul beide in `.env` in:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_CHAT_ID=123456789
   ```
5. Herstart de bot:
   ```bash
   docker compose up -d --force-recreate
   ```

Je krijgt meteen een startbericht. De bot reageert alleen op jouw chat-ID; anderen kunnen hem niet bedienen.

---

## 8. E-mailrapport (optioneel)

Elke dag na 20:00 stuurt de bot een overzicht van je portefeuille per e-mail.

1. Zet in je Google-account **tweestapsverificatie** aan (Beveiliging).
2. Maak daarna een **app-wachtwoord** aan (Google-account → Beveiliging → App-wachtwoorden). Je krijgt een code van 16 letters.
3. Vul in `.env` in:
   ```
   EMAIL_SENDER=jouwadres@gmail.com
   EMAIL_PASSWORD=de-16-letters-van-het-app-wachtwoord
   EMAIL_RECEIVER=adres-waar-het-rapport-heen-moet@voorbeeld.nl
   ```
   Gebruik **nooit** je gewone Gmail-wachtwoord.
4. Geen Gmail? Vul dan ook `EMAIL_SMTP_SERVER` en `EMAIL_SMTP_POORT` van je provider in (STARTTLS, meestal poort 587).
5. Herstart de bot:
   ```bash
   docker compose up -d --force-recreate
   ```

---

## 9. Overstappen naar echt handelen

Doe dit pas als je de demo een tijdje hebt gebruikt en begrijpt wat de bot doet.

### Bitvavo-API-sleutel aanmaken

1. Log in bij Bitvavo en ga naar de **API-instellingen** van je account.
2. Maak een nieuwe API-sleutel aan.
3. Geef **alleen** deze rechten:
   - ✅ **Bekijken** (saldo en koersen lezen)
   - ✅ **Handelen** (kopen en verkopen)
   - ❌ **Opnemen**: zet dit **nooit** aan
4. Kan het, beperk de sleutel dan tot het IP-adres van je internetverbinding.
5. Je krijgt een **key** en een **secret**. Het secret zie je maar één keer: kopieer het direct.

### Instellingen aanpassen

```bash
nano .env
```

```
DEMO_MODUS=0
BITVAVO_API_KEY=jouw-key
BITVAVO_API_SECRET=jouw-secret
```

```bash
docker compose up -d --force-recreate
```

In het logboek staat nu geen "DEMO-MODUS" meer, en op het dashboard staat alleen "Bitvavo".

De echte administratie begint leeg. De demo-gegevens (`demo_*.json`) blijven apart bewaard en worden niet gebruikt.

> **Begin klein.** Voeg eerst één of twee munten toe met een laag budget. Kijk een paar dagen mee voor je meer inlegt.

---

## 10. Dagelijks gebruik

| Wat | Commando |
|---|---|
| Logboek bekijken | `docker compose logs -f` |
| Stoppen | `docker compose down` |
| Starten | `docker compose up -d` |
| Herstarten na een wijziging in `.env` | `docker compose up -d --force-recreate` |

### Bijwerken naar een nieuwe versie

```bash
git pull
```

```bash
docker compose up -d --build
```

Je instellingen en gegevens blijven bewaard.

### Back-up

Al je gegevens staan in de map `profit-harvester`. Maak af en toe een kopie van deze bestanden:

- `.env` (je instellingen en sleutels; bewaar die kopie veilig)
- `bot_live_config.json` (je munten en instellingen)
- `bot_state.json` (ingelegd, geoogst, pot-cash)
- `bot_trades_db.json` (orderlogboek)
- `bot_historie.json` (grafiek)
- `bot_meldingen.json` (meldingen achter het belletje)

---

## 11. Zonder Docker

Op Windows, macOS of Linux kan de bot ook rechtstreeks met Python (versie 3.11 of nieuwer) draaien. Hij herstart dan niet vanzelf na een herstart van de computer.

```bash
python3 -m venv venv
```

Activeren op **Linux of macOS**:
```bash
source venv/bin/activate
```

Activeren op **Windows**:
```bash
venv\Scripts\activate
```

Daarna:
```bash
pip install -r requirements.txt
```

```bash
python bot.py
```

Let op: zonder Docker luistert het dashboard standaard alleen op de computer zelf (`http://127.0.0.1:5000`). Wil je het vanaf je telefoon openen, zet dan `DASHBOARD_HOST=0.0.0.0` in `.env`.

---

## 12. Problemen oplossen

| Probleem | Oplossing |
|---|---|
| `DASHBOARD_TOKEN ontbreekt of is te kort` | Vul in `.env` een wachtwoord van minimaal 16 tekens in. |
| `BITVAVO_API_KEY of BITVAVO_API_SECRET ontbreekt` | Vul je Bitvavo-sleutels in, of zet `DEMO_MODUS=1`. |
| Inloggen lukt, maar je komt steeds terug op het inlogscherm | Je opent het dashboard via `http://`. Zet `DASHBOARD_ALLEEN_HTTPS=0` en herstart. |
| "Te veel mislukte pogingen" | Wacht 15 minuten en probeer het opnieuw met het juiste wachtwoord. |
| Geen Telegram-berichten | Controleer token en chat-ID, en of je je bot zelf eerst `/start` hebt gestuurd. |
| E-mail komt niet aan | Gebruik een app-wachtwoord, geen gewoon wachtwoord. Kijk ook in je spamfolder. |
| Bitvavo weigert orders | Controleer of de API-sleutel het recht **Handelen** heeft, en of een eventuele IP-beperking klopt. |
| Er wordt niets gekocht bij Aanvullen | Zie de *Veelgestelde vragen* op de uitlegpagina in het dashboard. |
| BTC of ETH toevoegen lukt niet | Dat klopt: dat zijn reservemunten. Zie de uitlegpagina. |

Meer uitleg over hoe de bot werkt staat op de **Uitleg**-pagina in het dashboard (rechtsonder **Help**).
