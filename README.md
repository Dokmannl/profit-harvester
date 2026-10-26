# Profit Harvester

**Een gratis, open-source tradingbot voor Bitvavo die je munten laat staan en alleen de winst oogst.**

🌐 **Website met uitleg en screenshots:** https://dokmannl.github.io/profit-harvester/

De meeste tradingbots kopen een munt en verkopen hem later weer helemaal. Profit Harvester werkt andersom: jij kiest je munten en een budget per munt, en de bot verkoopt automatisch **alleen het deel boven je budget** zodra een munt genoeg gestegen is. Je positie blijft staan en kan steeds opnieuw winst opleveren. Een deel van die winst gaat automatisch naar een reserve in grote munten, zoals **Bitcoin, Ethereum, BNB, Solana en XRP**, verdeeld zoals jij wilt.

Draait 24/7 op een Raspberry Pi of een gewone pc, met een eigen webdashboard (ook als app op je telefoon) en meldingen via Telegram.

> 🧪 **Eerst oefenen zonder risico:** de bot heeft een demo-modus met echte koersen en nepgeld. Geen Bitvavo-account nodig om te proberen.

---

## Wat doet hij?

### 🛒 Hoofdlijst: jouw munten, automatisch winst oogsten
- Je kiest zelf munten en een budget per munt, bijvoorbeeld SOL met €250.
- Staat een munt een vast bedrag in de winst (standaard **€11 netto**), dan volgt de bot de koers omhoog.
- Zakt de koers **1%** vanaf de top, dan verkoopt hij **alleen de winst**. Je budget blijft belegd.
- **Vangnet:** zakt de winst tijdens het volgen van de top terug tot €10,50, dan verkoopt hij meteen. Zo is de helft altijd groot genoeg voor je reserve.
- **Kopen gebeurt nooit vanzelf.** Bij "Munt toevoegen" koopt de bot meteen voor het budget dat jij invult. Met "Alles Aanvullen" koopt hij in lagen bij munten die onder hun budget staan. Hij wacht op een bodem als de koers nog daalt, en legt per munt nooit meer in dan 1,5× het budget.
- **Munt verwijderen** verkoopt je hele saldo van die munt; de opbrengst wordt vrije cash. In het rendement telt dat apart, niet als oogst.
- **Munt opzoeken:** typ een afkorting of naam (bijvoorbeeld *BTC* of *Bitcoin*) en zie meteen of de munt op Bitvavo te verhandelen is, met koers, 24-uursverandering en volume. Staat hij nog nergens in je bot, dan kun je hem daar direct **toevoegen en kopen**, met een bevestiging vooraf.

### 💎 Afgeroomd: je reserve, verdeeld over grote munten
- **50%** van elke oogst gaat direct naar je reserve. Standaard kun je kiezen uit **BTC, ETH, BNB, SOL en XRP**, en je kunt zelf munten toevoegen of weghalen (maximaal 10).
- Op de **Afgeroomd**-pagina stel je per munt een **doelpercentage** in, bijvoorbeeld BTC 50%, ETH 30%, BNB 10%, SOL 5% en XRP 5%. Na elke oogst koopt de bot de munt die **het verst onder zijn doel** zit.
- Met de knop **Herbalanceren** verkoopt de bot een deel van wat te zwaar is en koopt hij met precies die opbrengst wat te licht is. Je vrije cash en de potten blijven onaangeroerd, elke munt houdt een **minimum** (standaard €25), en je ziet vooraf precies wat er gebeurt.
- Per munt zie je wat je erin hebt gestoken en wat het **resultaat** is, met een grafiek van het verloop. De telling kun je met één knop opnieuw laten beginnen.
- Loopt de verdeling scheef (standaard meer dan 10 procentpunt), dan krijg je een **seintje via Telegram**. De bot herbalanceert nooit vanzelf.

### 🧪 Pot: de bot handelt zelf
- Een apart potje waarin de bot zelf beweeglijke, goed verhandelde munten kiest, koopt en met winst weer verkoopt.
- **Bijkopen bij een dip** kun je aan- of uitzetten. Staat het uit, dan koopt de pot een munt één keer en houdt hij hem vast tot hij met winst verkocht wordt; daarna kiest hij een nieuwe.
- Met remmen: een maximum per dag, een afkoeltijd per munt, een inlegplafond en een noodstop. Munten die de pot nooit mag kiezen, sluit je uit; de lijst zie je in één oogopslag.

### 📉 Dalpot: de grootste daler van de dag
- Nog een apart potje: de bot koopt de munt die de laatste 24 uur het hardst gedaald is, en verkoopt zodra die herstelt.
- Het risicovolste onderdeel, met een eigen noodstop.

### 📊 Dashboard en meldingen
- Webdashboard in een vrolijke **moestuin-stijl**: kaarten voor totale waarde, vrije cash, potten en je afgeroomde winst (met de munt waar de volgende oogst heen gaat), een grafiek met stippen voor elke aankoop en verkoop, posities met een plantje dat meegroeit naar het doel, en rendement per periode. Op een laptop met een zijbalk, op je telefoon als app met een **compacte indeling**: alles belangrijks in het eerste scherm.
- **Status en pauzeknop**: zie of de bot draait, wanneer hij voor het laatst keek en hoe warm je Pi is. Met één knop zet je hem op pauze.
- **Activiteit** als sorteerbare tabel met filters op koop/verkoop, bron en munt, en export naar CSV.
- Alles te bedienen vanaf de **Beheren**-pagina, met **tabbladen** (Hoofdlijst, Pot, Dalpot, Instellingen) en een bevestiging met de bedragen erbij bij elke actie.
- **Meldingen op de site**: een belletje in het menu met alle berichten van de bot, en een rode stip bij belangrijke.
- **Licht of donker** thema, per apparaat onthouden.
- **Telegram**: meldingen bij elke oogst en aankoop, en bediening met knoppen en commando's.
- **Dagelijks e-mailrapport** met je hele portefeuille.
- Een uitgebreide **uitlegpagina** in het dashboard, met inklapbare onderdelen, die de instellingen toont zoals ze bij jou staan.

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
