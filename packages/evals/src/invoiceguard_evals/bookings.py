"""The booking dataset (R3-4, ADR-020): a catalogue of what made-up suppliers sell, each item
with its SKR03 account, from which a booking history and a held-out test set are generated.

- The history (`invoiceguard-eval generate`) is written to the api package, `booking/history.json`:
  the demo imports it, and the eval loads it into its database. Each item is booked with its
  `history` wordings only.
- The test lines are built here, never stored in the database:
  - `seen`: a wording that is in the history (a repeat purchase, the easy case);
  - `unseen`: a held-out wording of the same item, which no history line has (does retrieval
    find the meaning, not the words?);
  - `new_supplier`: a supplier with no history at all, wordings that are in no history line.

The truth is the item's account, set here by hand before any run. Hard cases on purpose: one IT
supplier with five accounts (hardware above and below the GWG limit, services, licences,
hosting), freight in (3800) and out (4730), rent of storage space (4210) next to hosting.
"""

import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

from invoiceguard_api.booking import history

HISTORY_PATH = Path(str(history.HISTORY))
# Fixed seed: the history is the same on every machine.
SEED = 2026
FIRST_DAY = date(2025, 1, 6)
DAYS = 600
Kind = Literal["seen", "unseen", "new_supplier"]


@dataclass(frozen=True)
class Item:
    item_id: str
    account: str
    # Wordings that appear in the history.
    history: tuple[str, ...]
    # A wording of the same item that appears in no history line.
    unseen: str


@dataclass(frozen=True)
class SupplierItems:
    vat_id: str
    name: str
    # Invoice number prefix.
    prefix: str
    # How often each wording is booked: suppliers we buy from often have more history.
    rounds: int
    items: tuple[Item, ...]


@dataclass(frozen=True)
class HeldOutLine:
    case_id: str
    kind: Kind
    supplier_vat_id: str
    supplier_name: str
    text: str
    account: str
    item_id: str


CATALOGUE = (
    SupplierItems("DE999000017", "Muster Bürobedarf GmbH", "MB", 3, (
        Item("paper", "4930", ("Kopierpapier A4, 80 g/m², Karton à 2.500 Blatt",
                               "Kopierpapier DIN A4 weiß, 500 Blatt"),
             "Druckerpapier A4, 5 Pakete à 500 Blatt"),
        Item("folders", "4930", ("Ordner DIN A4, 8 cm, blau", "Aktenordner breit, 10 Stück"),
             "Stehordner A4 mit 80 mm Rücken"),
        Item("toner", "4930", ("Toner schwarz für Bürodrucker",
                               "Tonerkartusche Laserdrucker schwarz"),
             "Druckerpatrone schwarz, hohe Reichweite"),
        Item("stationery", "4930", ("Haftnotizen 76 x 76 mm, gelb",
                                    "Kugelschreiber blau, 50 Stück"),
             "Schreibblöcke A4 kariert, 10 Stück"),
        Item("chair", "4855", ("Bürodrehstuhl ergonomisch mit Armlehnen",
                               "Schreibtischstuhl mit Netzrücken"),
             "Ergonomischer Bürostuhl mit Lordosenstütze"),
        Item("desk", "0420", ("Schreibtisch höhenverstellbar, 160 x 80 cm",
                              "Elektrisch höhenverstellbarer Arbeitstisch"),
             "Steh-Sitz-Schreibtisch 180 cm"),
        Item("cabinet", "0420", ("Aktenschrank abschließbar, 5 Ordnerhöhen",
                                 "Schiebetürenschrank Stahl, 120 cm"),
             "Büroschrank mit Flügeltüren, abschließbar"),
    )),
    SupplierItems("DE999000025", "Beispiel Logistik AG", "BL", 3, (
        Item("freight_out", "4730", ("Palettentransport Hamburg nach München",
                                     "Stückgutversand an Kunden, Zone 3"),
             "Spedition: Auslieferung von 6 Paletten an Kunde in Leipzig"),
        Item("storage", "4210", ("Lagerung pro Palette und Monat",
                                 "Lagerfläche 50 m², Monatsmiete"),
             "Miete Außenlager Oktober"),
        Item("freight_in", "3800", ("Expresszustellung Ersatzteile",
                                    "Eilfracht Anlieferung Rohmaterial"),
             "Kurierdienst für Wareneingang Maschinenteile"),
    )),
    SupplierItems("DE999000033", "Demo IT-Service GmbH", "IT", 3, (
        Item("notebook", "0410", ("Notebook 14 Zoll, 32 GB RAM", "Laptop 15,6 Zoll, 16 GB RAM"),
             "Business-Notebook mit Dockingstation"),
        Item("monitor", "4855", ("Monitor 27 Zoll, USB-C", "Bildschirm 24 Zoll Full HD"),
             "Flachbildschirm 27 Zoll für Arbeitsplatz"),
        Item("it_service", "4806", ("Einrichtung und Inbetriebnahme",
                                    "IT-Support-Pauschale Oktober 2026",
                                    "Fernwartung Arbeitsplatzrechner"),
             "Technischer Support vor Ort, Stunden"),
        Item("licences", "4964", ("Office-Paket Cloud-Abo, 12 Monate pro Nutzer",
                                  "Virenschutz-Lizenz, Jahresabo 10 Plätze"),
             "Softwarelizenz Buchhaltungsprogramm, Jahresgebühr"),
        Item("hosting", "4925", ("Webhosting Business-Tarif, monatlich",
                                 "Domainregistrierung .de, jährlich"),
             "Cloud-Server, monatliche Gebühr"),
    )),
    SupplierItems("DE999000041", "Fiktiv Gebäudereinigung GmbH", "GR", 3, (
        Item("cleaning", "4250", ("Unterhaltsreinigung Büroflächen Oktober 2026",
                                  "Glasreinigung Fensterfronten",
                                  "Grundreinigung Teppichböden"),
             "Reinigung Sanitärbereiche und Küche, monatlich"),
        Item("repairs", "4260", ("Reparatur Türschließanlage Büro",
                                 "Austausch defekter Deckenleuchten"),
             "Instandsetzung Bodenbelag im Flur"),
    )),
    SupplierItems("DE999000050", "Exempel Druck & Medien GmbH", "DM", 3, (
        Item("print_ads", "4600", ("Visitenkarten, 4/4-farbig, 500 Stück",
                                   "Imagebroschüre A4, 16 Seiten, Auflage 1.000",
                                   "Flyer DIN lang, 5.000 Stück"),
             "Werbeplakate A1 für den Messestand"),
        Item("books", "4940", ("Fachbuch Rechnungswesen, gedruckt",
                               "Fachzeitschrift Steuerrecht, Jahresabo"),
             "Kommentar zum Umsatzsteuergesetz, Loseblattwerk"),
    )),
    SupplierItems("DE999000076", "Stadtwerke Beispielstadt GmbH", "SW", 2, (
        Item("energy", "4240", ("Stromlieferung Abschlag November",
                                "Erdgas Abschlagszahlung Oktober"),
             "Wasser und Abwasser, Quartalsabrechnung"),
    )),
    SupplierItems("DE999000092", "Muster Versicherung AG", "MV", 2, (
        Item("insurance", "4360", ("Betriebshaftpflichtversicherung, Jahresbeitrag",
                                   "Inhaltsversicherung Büro, Jahresprämie"),
             "Elektronikversicherung für EDV-Anlagen"),
    )),
    SupplierItems("DE999000105", "Beispiel Steuerberatung Partnerschaft", "SB", 2, (
        Item("bookkeeping", "4955", ("Finanzbuchhaltung Monat Oktober",
                                     "Lohnabrechnung für 12 Mitarbeiter"),
             "Laufende Buchhaltung September, Belege kontiert"),
        Item("annual_accounts", "4957", ("Erstellung Jahresabschluss 2025",
                                         "Bilanz und Gewinn- und Verlustrechnung 2024"),
             "Abschlussarbeiten und Steuerbilanz 2025"),
        Item("advice", "4950", ("Steuerliche Beratung, 4 Stunden",
                                "Rechtsberatung Vertragsprüfung"),
             "Beratung zur Umsatzsteuer, 3 Std."),
    )),
    SupplierItems("DE999000113", "Beispielnetz Telekommunikation GmbH", "TK", 2, (
        Item("phone", "4920", ("Mobilfunkvertrag 5 Karten, monatlich",
                               "Festnetz-Telefonanlage Grundgebühr"),
             "Datenvolumen-Zusatzpaket für Diensthandys"),
        Item("internet", "4925", ("Glasfaser-Internetanschluss 1 Gbit/s, monatlich",
                                  "DSL-Anschluss Filiale, Monatsgebühr"),
             "Breitbandanschluss Büro, 500 Mbit/s"),
    )),
    SupplierItems("DE999000121", "Autohaus Exempel GmbH", "AH", 2, (
        Item("car_repair", "4540", ("Inspektion Firmenwagen nach Herstellervorgabe",
                                    "Reifenwechsel inkl. Wuchten"),
             "Ölwechsel und Bremsbeläge vorne erneuert"),
        Item("fuel", "4530", ("Tankkarte Abrechnung Oktober, Diesel",
                              "Kraftstoff Super E10, Flottenkarte"),
             "Tankrechnung Dienstfahrzeuge September"),
    )),
)  # fmt: skip

# A supplier with no history: only other suppliers' bookings can help.
NEW_SUPPLIER = ("DE999000130", "Neuer Büroservice GmbH")
NEW_SUPPLIER_LINES = (
    ("paper", "4930", "Kopierpapier A4 weiß, 2.500 Blatt"),
    ("toner", "4930", "Toner cyan für Farblaser"),
    ("chair", "4855", "Drehstuhl schwarz mit Armlehnen"),
    ("print_ads", "4600", "Flyer A5, 2.000 Stück, beidseitig"),
    ("phone", "4920", "Mobilfunk-Grundgebühr April"),
    ("it_service", "4806", "Wartung der IT-Systeme, Pauschale"),
)


def history_invoices(seed: int = SEED) -> list[dict[str, Any]]:
    """Every history wording of every item, `rounds` times per supplier, shuffled and packed into
    invoices of one to three lines with dates over 600 days."""
    rng = random.Random(seed)
    invoices: list[dict[str, Any]] = []
    for supplier in CATALOGUE:
        lines = [
            {"text": wording, "account": item.account}
            for _ in range(supplier.rounds)
            for item in supplier.items
            for wording in item.history
        ]
        rng.shuffle(lines)
        number = 0
        while lines:
            size = rng.randint(1, 3)
            issued = FIRST_DAY + timedelta(days=rng.randrange(DAYS))
            number += 1
            invoices.append(
                {
                    "supplier_vat_id": supplier.vat_id,
                    "supplier_name": supplier.name,
                    "invoice_number": f"{supplier.prefix}-{issued.year}-{number:04d}",
                    "issue_date": issued.isoformat(),
                    "lines": lines[:size],
                }
            )
            lines = lines[size:]
    return sorted(invoices, key=lambda invoice: (invoice["issue_date"], invoice["invoice_number"]))


def write_history(path: Path | None = None) -> int:
    """Write the history the api imports (default: its packaged file); returns the number of
    lines."""
    path = path or HISTORY_PATH
    invoices = history_invoices()
    document = {
        "description": (
            "Generated booking history (packages/evals/src/invoiceguard_evals/bookings.py). "
            "Every supplier, invoice and amount is made up."
        ),
        "invoices": invoices,
    }
    path.write_text(
        json.dumps(document, indent=1, ensure_ascii=False) + "\n", "utf-8", newline="\n"
    )
    return sum(len(invoice["lines"]) for invoice in invoices)


def held_out_lines() -> list[HeldOutLine]:
    lines: list[HeldOutLine] = []
    for supplier in CATALOGUE:
        for item in supplier.items:
            wordings: tuple[tuple[Kind, str], ...] = (
                ("seen", item.history[0]),
                ("unseen", item.unseen),
            )
            for kind, text in wordings:
                lines.append(
                    HeldOutLine(
                        f"{kind}-{item.item_id}",
                        kind,
                        supplier.vat_id,
                        supplier.name,
                        text,
                        item.account,
                        item.item_id,
                    )
                )
    vat_id, name = NEW_SUPPLIER
    for item_id, account, text in NEW_SUPPLIER_LINES:
        lines.append(
            HeldOutLine(f"new-{item_id}", "new_supplier", vat_id, name, text, account, item_id)
        )
    return lines


def item_of_text() -> dict[str, str]:
    """History wording → item, for judging which retrieved bookings are relevant."""
    return {
        wording: item.item_id
        for supplier in CATALOGUE
        for item in supplier.items
        for wording in item.history
    }
