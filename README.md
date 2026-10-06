# Profit Harvester

**Een gratis, open-source tradingbot voor Bitvavo die je munten laat staan en alleen de winst oogst.**

🌐 **Website met uitleg en screenshots:** https://dokmannl.github.io/profit-harvester/

De meeste tradingbots kopen een munt en verkopen hem later weer helemaal. Profit Harvester werkt andersom: jij kiest je munten en een budget per munt, en de bot verkoopt automatisch **alleen het deel boven je budget** zodra een munt genoeg gestegen is. Je positie blijft staan en kan steeds opnieuw winst opleveren. Een deel van die winst gaat automatisch naar een reserve in **Bitcoin of Ethereum**.

Draait 24/7 op een Raspberry Pi of een gewone pc, met een eigen webdashboard (ook als app op je telefoon) en meldingen via Telegram.

> 🧪 **Eerst oefenen zonder risico:** de bot heeft een demo-modus met echte koersen en nepgeld. Geen Bitvavo-account nodig om te proberen.

---

## Wat doet hij?

### 🛒 Hoofdlijst: jouw munten, automatisch winst oogsten
- Je kiest zelf munten en een budget per munt, bijvoorbeeld SOL met €250.
- Staat een munt een vast bedrag in de winst (standaard **€11 netto**), dan volgt de bot de koers omhoog.
- Zakt de koers **1%** vanaf de top, dan verkoopt hij **alleen de winst**. Je budget blijft belegd.
- **Kopen gebeurt nooit vanzelf.** Jij drukt op "Alles Aanvullen", en de bot koopt in lagen bij munten die onder hun budget staan. Hij wacht op een bodem als de koers nog daalt, en legt per munt nooit meer in dan 1,5× het budget.

### 💎 Reserve: BTC of ETH
- **50%** van elke oogst gaat direct naar je reservemunt. Op het dashboard kies je **BTC of ETH**, en dat kun je per maand wisselen.
- Je bestaande reserve blijft staan bij een wissel, en beide tellen mee in je totale waarde.

### 🧪 Pot: de bot handelt zelf
- Een apart potje waarin de bot zelf beweeglijke, goed verhandelde munten kiest, koopt, bijkoopt bij een dip en verkoopt.
- Met remmen: een maximum per dag, een afkoeltijd per munt, een inlegplafond en een noodstop.

### 📉 Dalpot: de grootste daler van de dag
- Nog een apart potje: de bot koopt de munt die de laatste 24 uur het hardst gedaald is, en verkoopt zodra die herstelt.
- Het risicovolste onderdeel, met een eigen noodstop.

### 📊 Dashboard en meldingen
- Webdashboard met totale waarde, grafiek, posities, potten, rendement per periode en een orderlogboek.
- Alles te bedienen vanaf de **Beheren**-pagina, met een bevestiging bij elke actie.
- **Telegram**: meldingen bij elke oogst en aankoop, en bediening met knoppen en commando's.
- **Dagelijks e-mailrapport** met je hele portefeuille.
- Een uitgebreide **uitlegpagina** in het dashboard, die de instellingen toont zoals ze bij jou staan.

---

## Snel starten

Je hebt een Raspberry Pi (of een pc) met Docker nodig. De volledige uitleg voor beginners staat in **[INSTALLATIE.md](INSTALLATIE.md)**.

```bash
git clone https://github.com/Dokmannl/profit-harvester.git profit-harvester
cd profit-harvester
cp .env.example .env
nano .env                 # minimaal DASHBOARD_TOKEN invullen
docker compose up -d
```

Open daarna `http://<ip-van-je-pi>:5000` in je browser. De bot start standaard in **demo-modus**.

---

## Veiligheid

- Je **API-sleutels blijven bij jou**, in je eigen `.env`-bestand op je eigen apparaat. Er gaat niets naar een server van iemand anders.
- Geef je Bitvavo-sleutel alleen de rechten **Bekijken** en **Handelen**, **nooit Opnemen**. Dan kan niemand via de bot geld van je account halen.
- Het dashboard heeft een wachtwoord (minimaal 16 tekens) en blokkeert na 5 foute pogingen.
- De Telegram-bot reageert alleen op jouw eigen chat.

---

## ❤️ Steun dit project

Profit Harvester is gratis. Heb je er iets aan, dan wordt een kleine donatie erg gewaardeerd:

| | Adres |
|---|---|
| **Bitcoin (BTC)** | `bc1q0sjsskrmmmtm9zj2vaeady8h37w280xxffve6n` |
| **Ethereum (ETH)** | `0x798483b4749654Fa0C1bffb95F27d7C401955c24` |
| **Solana (SOL)** | `6Qe6o5FMQUUMifxAdzE75SsekYsFX6Bgft3JGPdmGJRT` |

Controleer het adres altijd goed voor je iets verstuurt, en stuur elke munt alleen naar het eigen adres: BTC via het Bitcoin-netwerk, ETH via het Ethereum-netwerk, SOL via het Solana-netwerk.

De donatie-adressen staan ook onderaan de uitlegpagina in het dashboard.

---

## ⚠️ Disclaimer

**Dit is geen financieel advies.** Profit Harvester is software die jouw eigen instellingen uitvoert. Handelen in crypto is risicovol: koersen kunnen hard dalen en je kunt (een deel van) je inleg verliezen. De bot heeft **geen stop-loss**. Resultaten uit het verleden bieden geen garantie voor de toekomst.

Je gebruikt deze software volledig op eigen risico. De makers zijn niet aansprakelijk voor verliezen, fouten in de software, storingen bij Bitvavo of andere schade. Test eerst in demo-modus en begin met kleine bedragen.

Dit project is niet verbonden aan Bitvavo.

---

## Licentie

[MIT](LICENSE). Je mag de software gratis gebruiken, aanpassen en delen.
