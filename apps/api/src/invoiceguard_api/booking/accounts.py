"""The SKR03 accounts a reviewer can book an invoice line to (ADR-020).

A short list of common purchase accounts (assets, goods, expenses) of DATEV's standard chart of
accounts SKR03, with shortened names. A real installation uses the client's chart from the tax
advisor; the export (ADR-013) still books every invoice to `datev_expense_account`.
"""

ACCOUNTS: dict[str, str] = {
    "0410": "Geschäftsausstattung",
    "0420": "Büroeinrichtung",
    "3400": "Wareneingang 19 % Vorsteuer",
    "3800": "Bezugsnebenkosten",
    "4210": "Miete",
    "4240": "Gas, Strom, Wasser",
    "4250": "Reinigung",
    "4260": "Instandhaltung betrieblicher Räume",
    "4360": "Versicherungen",
    "4530": "Laufende Kfz-Betriebskosten",
    "4540": "Kfz-Reparaturen",
    "4600": "Werbekosten",
    "4650": "Bewirtungskosten",
    "4730": "Ausgangsfrachten",
    "4806": "Wartungskosten für Hard- und Software",
    "4855": "Sofortabschreibung geringwertiger Wirtschaftsgüter",
    "4900": "Sonstige betriebliche Aufwendungen",
    "4920": "Telefon",
    "4925": "Internetkosten",
    "4930": "Bürobedarf",
    "4940": "Zeitschriften, Bücher",
    "4945": "Fortbildungskosten",
    "4950": "Rechts- und Beratungskosten",
    "4955": "Buchführungskosten",
    "4957": "Abschluss- und Prüfungskosten",
    "4964": "Lizenzen und Konzessionen",
    "4980": "Sonstiger Betriebsbedarf",
}


def account_name(number: str) -> str:
    return ACCOUNTS.get(number, "Unknown account")
