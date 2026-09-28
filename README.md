# Bosch Connect-Key K 40 RF / Buderus MX400 Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/default)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg)](https://www.home-assistant.io/)

Custom Integration (`bosch_k40rf`) für Home Assistant zum lokalen, schnellen und zuverlässigen Auslesen von Wärmepumpen, Hybrid-Systemen und Heizungsanlagen über das **Bosch Connect-Key K 40 RF** bzw. **Buderus MX400** Gateway.

Basiert auf der offiziellen Spezifikation der [Bosch Home Comfort Developer API](https://github.com/bosch-home-comfort/api-docs).

---

## Highlights

- **100% Lokale REST-API:** Direkte Kommunikation über das lokale Netzwerk – schnell, zuverlässig und komplett unabhängig von Cloud-Diensten.
- **Offizielle API-Konformität:** Basiert auf der offiziellen Schnittstellenspezifikation der [Bosch Home Comfort Developer API](https://github.com/bosch-home-comfort/api-docs).
- **Breite System-Unterstützung:** Erkennt Wärmepumpen, Kessel, Hybridsysteme sowie EEBus- und Smart-Grid-Zustände.
- **Strukturierte Geräte-Hierarchie:** Automatische Aufteilung der Entitäten auf das Gateway und die jeweiligen Systemkomponenten (Heizkreise, Warmwasser, Solarkreise, Lüftung, Raumregler und Funk-Thermostate).
- **Dynamische Erkennung:** Erstellt nur Entitäten für tatsächlich an der Anlage vorhandene Funktionen und verhindert Phantom-Sensoren.
- **Einfaches & sicheres Pairing:** Lokale Token-Authentifizierung direkt am Gateway mit Bestätigung per Tastendruck.

---

## Technische Details

| Eigenschaft | Wert |
| :--- | :--- |
| **Domain** | `bosch_k40rf` |
| **Authentifizierungs-Port** | `9442` (HTTPS POST `/auth/token`) |
| **Daten-Port** | `9443` (HTTPS GET mit Bearer Token) |
| **Protokoll** | Lokales HTTPS (`verify_ssl=False` aufgrund selbstsignierter Gateway-Zertifikate) |
| **Scan-Intervall** | 60 Sekunden (Standard) |
| **API-Referenz** | [Bosch Home Comfort API Docs](https://github.com/bosch-home-comfort/api-docs) |

---

## Installation

### Variante A: Installation via HACS (Empfohlen)

1. Öffne **HACS** in deiner Home Assistant Instanz.
2. Klicke oben rechts auf das Drei-Punkte-Menü und wähle **Benutzerdefinierte Repositories**.
3. Füge die URL dieses Repositories ein und wähle als Kategorie **Integration**.
4. Klicke auf **Herunterladen** und starte Home Assistant anschließend neu.

### Variante B: Manuelle Installation

1. Lade das Repository herunter oder klone es.
2. Kopiere den Ordner `custom_components/bosch_k40rf` in dein Home Assistant Konfigurationsverzeichnis:
   ```bash
   cp -r custom_components/bosch_k40rf /path/to/homeassistant/config/custom_components/
   ```
3. Starte Home Assistant neu.

---

## Konfiguration & Pairing

1. Halte die Zugangsdaten vom Aufkleber deines Gateways (Connect-Key K 40 RF oder Buderus MX400) bereit:
   - **IP-Adresse oder Hostname**
   - **Login**
   - **Passwort** (Bindestriche können eingegeben oder weggelassen werden)
2. Gehe in Home Assistant zu **Einstellungen -> Geräte & Dienste -> Integration hinzufügen**.
3. Suche nach **Bosch K 40 RF** (bzw. `Buderus MX400`).
4. **Wichtig vor dem Absenden:** Drücke am Gateway gleichzeitig die **WLAN-** und die **Wireless-Taste für 1 Sekunde**, sodass die LEDs kurz blau blinken (Nachweis physischer Nähe).
5. Gib die Daten im Formular ein und klicke auf **Absenden**.
6. Die Integration authentifiziert sich, erkennt alle vorhandenen Systemkomponenten und richtet die Entitäten automatisch ein.

---

## API-Dokumentation & Danksagung

Dieses Projekt nutzt die offiziellen Spezifikationen und Schemata der:
- **[Bosch Home Comfort Developer API Documentation](https://github.com/bosch-home-comfort/api-docs)** (OpenAPI-Spezifikation für Connect-Key K 40 RF / Buderus MX400).

Vielen Dank an die Bosch Home Comfort Group für die Bereitstellung der offenen Schnittstellendokumentation für lokale Steuerungen und Auswertungen.
