# HP Integrated Lights-Out (iLO) – Domoticz Plugin

Een Domoticz Python-plugin om sensordata uit te lezen van een HP iLO-interface.

---

## Vereisten

- Domoticz met ondersteuning voor Python-plugins (versie 2020.2 of nieuwer aanbevolen)
- Python 3
- De Python-bibliotheek `python-hpilo`

### Python-bibliotheek installeren

```bash
pip3 install python-hpilo
```

---

## Installatie

1. Navigeer naar de Domoticz plugins-map:

   ```bash
   cd /home/<gebruiker>/domoticz/plugins
   ```

2. Maak een map aan voor de plugin en plaats daarin `plugin.py`:

   ```bash
   mkdir HP_ilo
   cd HP_ilo
   # Kopieer plugin.py naar deze map, of clone de repository:
   git clone https://github.com/MadPatrick/HP_ilo.git .
   ```

3. Herstart Domoticz:

   ```bash
   sudo systemctl restart domoticz
   ```

---

## Configuratie

Ga in Domoticz naar **Instellingen → Hardware** en voeg een nieuw hardware-item toe van het type **HP Integrated Lights-Out (iLO)**.

| Parameter | Omschrijving | Standaard |
|-----------|-------------|-----------|
| IP-adres / Hostnaam | Het IP-adres of de hostnaam van de iLO-interface | `192.168.1.1` |
| Poort | TCP-poort van de iLO-interface | `443` |
| Gebruikersnaam | iLO-inloggebruikersnaam | `Administrator` |
| Wachtwoord | iLO-inlogwachtwoord | *(leeg)* |
| Poll-interval (sec) | Hoe vaak de gegevens worden opgehaald (10–3600 sec) | `300` |
| Debug | Uitgebreide logberichten in- of uitschakelen | `Uit` |

---

## Aangemaakte apparaten

Na de eerste verbinding worden de volgende Domoticz-apparaten automatisch aangemaakt:

| Unit | Naam | Omschrijving |
|------|------|-------------|
| 1 | Server Name | Naam van de server |
| 2 | Server FQDN | Volledig gekwalificeerde domeinnaam |
| 3 | Server Power State | Voedingsstatus (aan/uit) |
| 4 | Server Power Readings | Actueel, gemiddeld, max. en min. vermogen |
| 5 | Server Power On Time (min) | Tijd ingeschakeld in minuten |
| 6 | Server Asset Tag | Asset-tag van de server |
| 7 | Server UID Light | Status van het UID-lampje |
| 8 | Server Health | Gezondheidsoverzicht van de hardware |
| 9 | Network Settings | IP-adres, subnetmasker, gateway, DNS en MAC |
| 10 | Server Host Data | Ruwe host-data |
| 11 | Server OA Info | Onboard Administrator-informatie |

---

## Problemen oplossen

- **iLO login mislukt** – Controleer gebruikersnaam en wachtwoord.
- **iLO communicatiefout** – Controleer het IP-adres, de poort en of de iLO bereikbaar is vanuit de Domoticz-server.
- Schakel **Debug** in bij de hardware-instellingen voor gedetailleerde logberichten in het Domoticz-logboek.

---

## Licentie

Dit project is geporteerd vanuit de [Home Assistant HP iLO-integratie](https://www.home-assistant.io/integrations/hp_ilo).
