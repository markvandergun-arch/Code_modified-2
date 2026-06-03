from __future__ import annotations

from pathlib import Path
import textwrap

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "inventarisatie_energieplanner.pdf"


PAGES = [
    {
        "title": "Gebruik",
        "subtitle": "Zelfde structuur als de app-tab Gebruik. Verzamel hiermee de basis van het gebouw en de vraagprofielen.",
        "sections": [
            (
                "Gebouw",
                [
                    ("Gebouwtype", "Ja", "Kantoor / school / zorg / industrie / retail / anders", "Kiest standaardprofiel voor gebruik en energievraag."),
                    ("Bouwjaar / klasse", "Ja", "Voor 1992 / 1992-2005 / 2006-2014 / 2015+", "Bepaalt isolatieniveau en warmteverlies."),
                    ("Oriëntatie gebouw", "Ja", "N / NO / O / ZO / Z / ZW / W / NW", "Beïnvloedt zoninstraling, warmtelast en PV-potentieel."),
                    ("Gebruiksoppervlak BVO [m²]", "Ja", "Getal", "Schaalt warmte-, koel- en elektriciteitsvraag."),
                    ("Aantal verdiepingen", "Ja", "Getal", "Helpt gebouwvorm en verliesoppervlak inschatten."),
                    ("Gebouwvorm", "Nee", "Compact / rechthoekig / L-vormig / uitgestrekt", "Verbetert de schatting van verliesoppervlak."),
                    ("Openingstijden", "Ja", "Dagen + tijden", "Bepaalt wanneer comforttemperaturen en lasten actief zijn."),
                ],
            ),
            (
                "Gebouwdetails - temperatuurinstellingen",
                [
                    ("Verwarming tijdens gebruik [°C]", "Ja", "Bijv. 20", "Bepaalt warmtevraag tijdens bezetting."),
                    ("Verwarming buiten gebruik [°C]", "Ja", "Bijv. 15", "Bepaalt nacht/weekend-setback."),
                    ("Koeling tijdens gebruik [°C]", "Ja", "Bijv. 24", "Bepaalt koelvraag tijdens bezetting."),
                    ("Koeling buiten gebruik [°C]", "Nee", "Bijv. 28", "Bepaalt setup buiten gebruik."),
                ],
            ),
            (
                "Gebouwdetails - ventilatie, glas en zon",
                [
                    ("WTW-rendement", "Nee", "0-95%", "Verlaagt ventilatieverliezen als WTW aanwezig is."),
                    ("Luchtdichtheid / qv10", "Nee", "Getal of onbekend", "Verbetert warmteverliesberekening."),
                    ("Glaspercentage", "Nee", "Schatting per gevel", "Beïnvloedt zonnewinst en koelvraag."),
                    ("G-waarde / zonwering", "Nee", "Waarde of beschrijving", "Verbetert inschatting van zonnewinst."),
                ],
            ),
        ],
    },
    {
        "title": "Verbruik",
        "subtitle": "Gebruiksprofielen bepalen wanneer vraag optreedt en welke onderdelen pieken veroorzaken.",
        "sections": [
            (
                "Elektrisch verbruik",
                [
                    ("Jaarverbruik elektriciteit [kWh]", "Ja", "Factuur / meting", "Geeft de grootteorde van elektrische vraag."),
                    ("Piekvermogen / kwartierpiek [kW]", "Ja", "Meting / netbeheerder", "Belangrijk voor netcapaciteit."),
                    ("Basisverbruik tijdens gebruik", "Nee", "W/m² of kW", "Vult profiel in als meetdata ontbreekt."),
                    ("Basisverbruik buiten gebruik", "Nee", "W/m² of kW", "Bepaalt nacht/weekendlast."),
                    ("Meetdata beschikbaar", "Ja", "15 min / 30 min / uur / nee", "Maakt validatie en piekanalyse betrouwbaarder."),
                ],
            ),
            (
                "Processen",
                [
                    ("Procesnaam/type", "Ja", "Lijst", "Scheidt proceslasten van gebouwgebonden verbruik."),
                    ("Procesvermogen [kW]", "Ja", "Per proces", "Bepaalt piekbelasting."),
                    ("Bedrijfstijden", "Ja", "Dagen + tijden", "Bepaalt timing en load match met PV."),
                    ("Gelijktijdigheid", "Nee", "Altijd / deels / zelden", "Bepaalt of pieken optellen."),
                    ("Sturingsmogelijkheden", "Nee", "Ja/nee + toelichting", "Geeft flexibiliteit voor piekverlaging."),
                ],
            ),
            (
                "Mobiliteit",
                [
                    ("Aantal elektrische auto's", "Ja", "Getal", "Schaalt de totale laadenergie."),
                    ("Laadvermogen per auto [kW]", "Ja", "Bijv. 11/22/50", "Bepaalt laadpieken."),
                    ("Gemiddelde batterijcapaciteit [kWh]", "Ja", "Bijv. 60", "Bepaalt energiebehoefte per auto."),
                    ("Aankomst- en vertrektijd", "Ja", "Tijden", "Bepaalt laadvenster."),
                    ("Aankomst- en vertreklading [%]", "Ja", "Bijv. 50 -> 80", "Bepaalt benodigde energie per auto."),
                    ("Aanwezige auto's [%]", "Nee", "0-100%", "Maakt laadprofiel realistischer."),
                    ("Laadmodus", "Ja", "Direct laden / slim laden", "Slim laden blijft binnen contractruimte waar mogelijk."),
                ],
            ),
            (
                "Overig verbruik",
                [
                    ("Type overige lasten", "Ja", "Pompen / terrein / verlichting / anders", "Voorkomt ontbrekende structurele lasten."),
                    ("Vermogen [kW of W/m²]", "Ja", "Getal", "Bepaalt bijdrage aan totaalverbruik."),
                    ("Gebruikstijden", "Ja", "Dagen + tijden", "Bepaalt timing en piekbijdrage."),
                ],
            ),
        ],
    },
    {
        "title": "Opwek",
        "subtitle": "Deze gegevens bepalen lokale opwek, herkomst van elektriciteit en teruglevering.",
        "sections": [
            (
                "Zonnepanelen",
                [
                    ("PV aanwezig/gewenst", "Ja", "Ja / nee", "Bepaalt of PV wordt meegenomen."),
                    ("Vermogen zonnepanelen [kWp]", "Ja", "Getal", "Bepaalt jaaropwek en piekopwek."),
                    ("Richting zonnepanelen", "Ja", "N / NO / O / ZO / Z / ZW / W / NW", "Bepaalt ochtend-, middag- en jaaropbrengst."),
                    ("Dakhelling [°]", "Ja", "0-90", "Beïnvloedt seizoensopbrengst."),
                    ("Beschikbaar dakoppervlak", "Nee", "m² of tekening", "Controleert of gewenst vermogen realistisch is."),
                    ("Schaduw/obstakels", "Nee", "Beschrijving", "Kan opbrengst sterk beperken."),
                ],
            ),
            (
                "WKK",
                [
                    ("WKK aanwezig/gewenst", "Ja", "Ja / nee", "Bepaalt of WKK wordt meegenomen."),
                    ("Elektrisch vermogen [kW]", "Ja", "Getal", "Bepaalt maximale lokale elektriciteitsproductie."),
                    ("Thermisch rendement/vermogen", "Ja", "Getal", "Bepaalt hoeveel warmte WKK kan leveren."),
                    ("WKK-regeling", "Ja", "Elektriciteitsvraag / warmtevraag / hybride piekverlaging / altijd / uit", "Bepaalt wanneer WKK draait."),
                    ("Brandstoftype", "Nee", "Gas / biogas / waterstof / anders", "Belangrijk voor gasloosheid en emissie-interpretatie."),
                ],
            ),
            (
                "Net",
                [
                    ("Contractvermogen [kW]", "Ja", "Getal", "Bepaalt stoplicht en overschrijdingen."),
                    ("Terugleverlimiet [kW]", "Nee", "Getal of onbekend", "Beïnvloedt PV/WKK-overschot en batterijwaarde."),
                    ("Netverzwaring mogelijk", "Nee", "Ja / nee / onzeker", "Helpt maatregelen prioriteren."),
                ],
            ),
        ],
    },
    {
        "title": "Warmte En Opslag",
        "subtitle": "Het gebouw bepaalt de thermische vraag; installaties en opslag bepalen hoe die wordt geleverd.",
        "sections": [
            (
                "Referentie-installatie",
                [
                    ("Referentie elektrische verwarming gebruiken", "Ja", "Ja / nee", "Fallback als geen expliciete warmtebron de vraag dekt."),
                    ("Referentie COP verwarming", "Ja", "Winter/lente/zomer/herfst", "Rekent resterende warmtevraag om naar elektriciteit."),
                    ("Referentie EER koeling", "Ja", "Winter/lente/zomer/herfst", "Rekent koelvraag om naar elektriciteit."),
                ],
            ),
            (
                "Warmtepomp",
                [
                    ("Warmtepomp aanwezig/gewenst", "Ja", "Ja / nee", "Bepaalt of warmte elektrisch geleverd wordt."),
                    ("Warmtepompvermogen [kWth]", "Ja", "Getal", "Bepaalt hoeveel warmtevraag direct gedekt kan worden."),
                    ("COP-berekening", "Ja", "Vast / seizoen / weersafhankelijk", "Bepaalt elektriciteitsvraag van warmtepomp."),
                    ("Nominale COP", "Ja", "Getal", "Bepaalt stroomverbruik bij vaste COP."),
                    ("Max elektrisch vermogen locatie [kW]", "Nee", "Getal", "Begrenst warmtepomp bij krappe aansluiting."),
                ],
            ),
            (
                "Ketel en warmtenet",
                [
                    ("Ketel aanwezig + vermogen [kWth]", "Ja", "Ja/nee + getal", "Dekt resterende warmtevraag met brandstof."),
                    ("Ketelrendement", "Ja", "0-100%", "Bepaalt brandstofinput."),
                    ("Brandstoftype ketel", "Ja", "Gas / biogas / waterstof / anders", "Bepaalt gasloosheidsinterpretatie."),
                    ("Warmtenet aanwezig + capaciteit", "Ja", "Ja/nee + getal", "Dekt warmtevraag via externe warmte."),
                ],
            ),
            (
                "Opslag",
                [
                    ("Batterij aanwezig/gewenst", "Ja", "Ja / nee", "Bepaalt elektrische opslag en piekverlaging."),
                    ("Batterijcapaciteit [kWh]", "Ja", "Getal", "Bepaalt hoeveel energie kan worden opgeslagen."),
                    ("Laad-/ontlaadvermogen [kW]", "Ja", "Getal", "Bepaalt hoe snel pieken worden verlaagd."),
                    ("Laadstrategie batterij", "Ja", "Alleen lokaal overschot / laden tot contractruimte", "Bepaalt wanneer batterij mag laden."),
                    ("Warmteopslagcapaciteit [kWhth]", "Nee", "Getal", "Kan warmtepiek en gasvraag verlagen."),
                ],
            ),
        ],
    },
    {
        "title": "Meetdata En Validatie",
        "subtitle": "Meetdata maakt het model controleerbaar en voorkomt dat beslissingen op verkeerde aannames rusten.",
        "sections": [
            (
                "Meetdata",
                [
                    ("Elektriciteitsdata", "Ja", "15 min / 30 min / uur / factuur", "Controleert jaarverbruik en pieken."),
                    ("Gasdata", "Ja", "15 min / uur / factuur", "Controleert warmtevraag en gasloosheid."),
                    ("Warmtedata", "Nee", "kWth / GJ / anders", "Helpt warmtebalans valideren."),
                    ("Meetperiode", "Ja", "Start/einddatum", "Bepaalt vergelijkbaarheid met weerjaar."),
                    ("Ontbrekende waarden", "Nee", "Geen / beperkt / veel", "Bepaalt hoe betrouwbaar validatie is."),
                ],
            ),
            (
                "Bijlagen",
                [
                    ("Energiefacturen", "Ja", "Elektriciteit/gas/warmte", "Geeft snelle baseline."),
                    ("Plattegrond/dakplan", "Nee", "PDF/tekening/foto", "Helpt gebouwvorm en PV-potentieel."),
                    ("Installatielijst", "Nee", "Excel/PDF/foto", "Helpt vermogen en rendement controleren."),
                    ("Bekende afwijkende weken", "Nee", "Vakantie/storing/productiepiek", "Voorkomt verkeerde conclusies."),
                ],
            ),
        ],
    },
]


def wrap(text: str, width: int) -> str:
    return "\n".join(textwrap.wrap(str(text), width=width)) if text else ""


def add_header(fig, title: str, subtitle: str) -> None:
    fig.text(0.045, 0.965, title, ha="left", va="top", fontsize=15, fontweight="bold")
    fig.text(0.045, 0.925, subtitle, ha="left", va="top", fontsize=8.5, color="#56616F")
    fig.text(0.955, 0.965, "Inventarisatie energieplanner", ha="right", va="top", fontsize=8.5, color="#56616F")


def add_section_table(ax, title: str, rows: list[tuple[str, str, str, str]]) -> None:
    ax.axis("off")
    ax.set_title(title, loc="left", fontsize=10.5, fontweight="bold", pad=5)
    cell_text = [[wrap(a, 23), b, wrap(c, 31), wrap(d, 38), ""] for a, b, c, d in rows]
    table = ax.table(
        cellText=cell_text,
        colLabels=["Veld", "Ess.", "Opties / invullen", "Waarom nodig", "Waarde"],
        cellLoc="left",
        colLoc="left",
        loc="upper left",
        colWidths=[0.19, 0.055, 0.24, 0.28, 0.235],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(6.6)
    table.scale(1.0, 1.42)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#D8DEE8")
        cell.PAD = 0.025
        if row == 0:
            cell.set_facecolor("#F4F7FB")
            cell.set_text_props(fontweight="bold")
        elif col == 1 and cell.get_text().get_text() == "Ja":
            cell.set_text_props(color="#0B5FFF", fontweight="bold")


def add_cover(pdf: PdfPages) -> None:
    fig = plt.figure(figsize=(11.69, 8.27))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.text(0.055, 0.78, "Inventarisatieformulier", ha="left", va="top", fontsize=25, fontweight="bold")
    ax.text(0.055, 0.71, "Energieplanner gebouw", ha="left", va="top", fontsize=16, color="#0B5FFF", fontweight="bold")
    intro = (
        "Compact klantformulier voor consultants. De structuur volgt de app: Gebruik, Verbruik, Opwek, "
        "Warmte/Opslag en Meetdata. Velden met 'Ja' zijn essentieel voor een bruikbare basissimulatie; "
        "andere velden verhogen nauwkeurigheid of rapportkwaliteit."
    )
    ax.text(0.055, 0.62, wrap(intro, 120), ha="left", va="top", fontsize=10)
    for i, label in enumerate(["Klant/locatie", "Datum bezoek", "Consultant", "Contactpersoon"]):
        y = 0.48 - i * 0.07
        ax.text(0.055, y, f"{label}:", ha="left", va="top", fontsize=10, fontweight="bold")
        ax.plot([0.19, 0.72], [y - 0.004, y - 0.004], color="#CBD2D9", linewidth=1)
    ax.text(0.055, 0.14, "Opmerking: interactieve dropdowns in PDF zijn niet beschikbaar zonder extra PDF-formulierbibliotheek. Daarom staan keuze-opties compact in de tabel.", ha="left", va="top", fontsize=8.5, color="#56616F")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def add_page(pdf: PdfPages, page: dict) -> None:
    n = len(page["sections"])
    fig, axes = plt.subplots(n, 1, figsize=(11.69, 8.27))
    if n == 1:
        axes = [axes]
    add_header(fig, page["title"], page["subtitle"])
    for ax, (title, rows) in zip(axes, page["sections"]):
        add_section_table(ax, title, rows)
    fig.tight_layout(rect=[0.035, 0.035, 0.965, 0.885], h_pad=1.0)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(OUT) as pdf:
        add_cover(pdf)
        for page in PAGES:
            add_page(pdf, page)
    print(OUT)


if __name__ == "__main__":
    main()
