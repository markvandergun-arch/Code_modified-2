from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "inventarisatie_energieplanner.pdf"


SECTIONS = [
    {
        "title": "1. Project en klantcontext",
        "intro": "Doel: vastleggen voor welk gebouw de simulatie wordt gemaakt en welke beperking leidend is, bijvoorbeeld gasloos worden of bouwen binnen een kleine netaansluiting.",
        "essential": [
            ("Bedrijfsnaam en locatie", "Nodig om klimaat, gebouwcontext en rapportage te koppelen."),
            ("Contactpersoon en rol", "Nodig om aannames en ontbrekende gegevens te kunnen valideren."),
            ("Doel van de analyse", "Bepaalt of de nadruk ligt op gasloosheid, netcapaciteit, kosten of opwek."),
            ("Huidig contractvermogen elektriciteit [kW]", "Bepaalt de grens voor het stoplicht en slim laden."),
            ("Beschikbare energierekeningen of meetdata", "Nodig om het model te ijken op werkelijk verbruik."),
        ],
        "extra": [
            ("Gewenste opleverdatum of besluitmoment", "Helpt bepalen hoeveel detailniveau haalbaar is."),
            ("Geplande verbouwing of uitbreiding", "Beïnvloedt toekomstige energievraag en netcapaciteit."),
        ],
    },
    {
        "title": "2. Gebouw",
        "intro": "Doel: de basisvorm van het gebouw bepalen. Dit stuurt de berekening van warmtevraag, koelvraag en standaard elektrische lasten.",
        "essential": [
            ("Gebouwtype", "Bepaalt standaardprofielen voor gebruik, bezetting en energievraag."),
            ("Bouwjaar of bouwjaarklasse", "Bepaalt isolatieniveau en warmteverlies."),
            ("Hoofdoriëntatie", "Beïnvloedt zoninstraling, warmtelast en PV-potentieel."),
            ("Gebruiksoppervlak/BVO [m²]", "Schaalt warmte-, koel- en elektriciteitsvraag."),
            ("Aantal verdiepingen", "Beïnvloedt gebouwvorm en verliesoppervlak."),
            ("Openingstijden en gebruiksdagen", "Bepaalt wanneer comforttemperaturen en lasten actief zijn."),
        ],
        "extra": [
            ("Gebouwvorm", "Verbetert inschatting van verliesoppervlak."),
            ("Glaspercentage", "Beïnvloedt zonnewinst en koelvraag."),
            ("Plattegrond of energielabel", "Helpt aannames controleren."),
        ],
    },
    {
        "title": "3. Gebouwdetails",
        "intro": "Doel: comfortinstellingen en schilparameters vastleggen. Deze bepalen hoeveel warmte en koeling het gebouw thermisch nodig heeft.",
        "essential": [
            ("Verwarmingstemperatuur tijdens gebruik [°C]", "Bepaalt warmtevraag tijdens bezetting."),
            ("Verwarmingstemperatuur buiten gebruik [°C]", "Bepaalt setback en nacht/weekend-warmtevraag."),
            ("Koeltemperatuur tijdens gebruik [°C]", "Bepaalt koelvraag tijdens bezetting."),
            ("Ventilatie of luchtverversing", "Bepaalt ventilatieverlies en benodigde warmte/koeling."),
        ],
        "extra": [
            ("WTW-rendement", "Verlaagt ventilatieverliezen als warmteterugwinning aanwezig is."),
            ("Infiltratie/qv10", "Verbetert warmteverliesberekening."),
            ("G-waarde glas en zonwering", "Verbetert inschatting van zonnewinst en koelvraag."),
        ],
    },
    {
        "title": "4. Elektrisch verbruik",
        "intro": "Doel: basisverbruik en gebruiksprofiel vastleggen. Dit bepaalt de elektrische vraag voordat opwek, warmte-installaties en opslag worden meegenomen.",
        "essential": [
            ("Jaarverbruik elektriciteit [kWh]", "Geeft de grootteorde van de elektrische vraag."),
            ("Piekvermogen of kwartierpiek [kW]", "Belangrijk voor netcapaciteit en contractoverschrijding."),
            ("Gebruikspatroon per week", "Bepaalt wanneer elektrische lasten optreden."),
            ("Grote elektrische verbruikers", "Helpt pieken verklaren en maatregelen richten."),
        ],
        "extra": [
            ("15-minuten meetdata", "Maakt validatie en piekanalyse veel betrouwbaarder."),
            ("Onderverdeling verlichting/ICT/apparatuur", "Maakt de verbruiksmix en maatregelen concreter."),
        ],
    },
    {
        "title": "5. Processen",
        "intro": "Doel: proceslasten scheiden van gebouwgebonden verbruik. Proceslasten kunnen dominant zijn voor pieken en jaarverbruik.",
        "essential": [
            ("Type processen", "Bepaalt of lasten continu, batchmatig of seizoensgebonden zijn."),
            ("Vermogen per proces [kW]", "Bepaalt piekbelasting en totaalverbruik."),
            ("Bedrijfstijden per proces", "Bepaalt timing van verbruik en load match met PV."),
            ("Gelijktijdigheid", "Bepaalt of procespieken optellen of gespreid zijn."),
        ],
        "extra": [
            ("Proceswarmte of restwarmte", "Kan relevant zijn voor gasloosheid of warmteopslag."),
            ("Sturingsmogelijkheden", "Geeft flexibiliteit voor piekverlaging."),
        ],
    },
    {
        "title": "6. Mobiliteit",
        "intro": "Doel: laadbehoefte van elektrische voertuigen modelleren. Dit bepaalt extra elektriciteitsvraag en mogelijke pieken binnen het contractvermogen.",
        "essential": [
            ("Aantal elektrische auto's", "Schaalt de totale laadenergie."),
            ("Laadvermogen per auto [kW]", "Bepaalt hoe hoog laadpieken kunnen worden."),
            ("Gemiddelde batterijcapaciteit [kWh]", "Bepaalt energiebehoefte per voertuig."),
            ("Aankomst- en vertrektijd", "Bepaalt venster waarin geladen kan worden."),
            ("Aankomstlading en gewenste vertreklading [%]", "Bepaalt hoeveel energie per auto nodig is."),
        ],
        "extra": [
            ("Percentage aanwezige auto's", "Maakt het laadprofiel realistischer."),
            ("Maximaal laadvermogen locatie [kW]", "Begrenst de totale laadpiek."),
            ("Slim laden gewenst ja/nee", "Bepaalt of laden binnen contractruimte wordt gestuurd."),
        ],
    },
    {
        "title": "7. Overig verbruik",
        "intro": "Doel: restlasten vastleggen die niet onder gebouw, processen of mobiliteit vallen, zodat de totale basislast volledig is.",
        "essential": [
            ("Type overige lasten", "Voorkomt dat structureel verbruik ontbreekt."),
            ("Geschat vermogen tijdens gebruik [kW of W/m²]", "Bepaalt bijdrage aan totaalverbruik."),
            ("Gebruikstijden", "Bepaalt timing en piekbijdrage."),
        ],
        "extra": [
            ("Buitenverlichting, pompen, terreininstallaties", "Vaak kleine maar structurele posten."),
            ("Seizoensafhankelijkheid", "Kan zomer- of winterpieken verklaren."),
        ],
    },
    {
        "title": "8. Opwek - zonnepanelen",
        "intro": "Doel: PV-opwek berekenen en vergelijken met de vraag. Richting en vermogen bepalen opbrengst en load match.",
        "essential": [
            ("PV aanwezig of gewenst", "Bepaalt of PV wordt meegenomen."),
            ("Geïnstalleerd of gewenst vermogen [kWp]", "Bepaalt jaaropwek en piekopwek."),
            ("Richting zonnepanelen", "Bepaalt ochtend-, middag- en avondopbrengst."),
            ("Dakhelling [°]", "Beïnvloedt opbrengst per seizoen."),
        ],
        "extra": [
            ("Beschikbaar dakoppervlak", "Controleert of gewenst vermogen realistisch is."),
            ("Schaduw of obstakels", "Kan opbrengst sterk beperken."),
            ("Omvormerbeperkingen", "Beïnvloedt piekvermogen en clipping."),
        ],
    },
    {
        "title": "9. Opwek - WKK en net",
        "intro": "Doel: lokale brandstofgestuurde opwek en netgrenzen vastleggen. Dit is belangrijk voor piekverlaging, warmteproductie en gasloosheidsanalyse.",
        "essential": [
            ("WKK aanwezig ja/nee", "Bepaalt of elektrische en thermische WKK-opwek wordt meegenomen."),
            ("Elektrisch WKK-vermogen [kW]", "Bepaalt maximale lokale elektriciteitsproductie."),
            ("Thermisch rendement of warmtevermogen", "Bepaalt hoeveel warmte de WKK kan leveren."),
            ("WKK-regeling", "Bepaalt of de WKK stuurt op stroomvraag, warmtevraag of piekverlaging."),
            ("Contractvermogen netaansluiting [kW]", "Bepaalt of scenario's binnen de aansluiting passen."),
        ],
        "extra": [
            ("Brandstoftype en brandstofverbruik", "Belangrijk voor gasloosheid en CO2-interpretatie."),
            ("Terugleverbeperkingen", "Beïnvloedt PV/WKK-overschot en batterijwaarde."),
        ],
    },
    {
        "title": "10. Warmte-installaties",
        "intro": "Doel: bepalen hoe thermische warmtevraag wordt ingevuld. Het gebouw bepaalt de vraag; installaties zetten die om naar elektriciteit, gas of warmte.",
        "essential": [
            ("Warmtepomp aanwezig/gewenst", "Bepaalt of warmtevraag elektrisch wordt geleverd."),
            ("Warmtepompvermogen [kWth]", "Bepaalt hoeveel warmtevraag direct gedekt kan worden."),
            ("COP-berekening of COP-waarde", "Bepaalt elektriciteitsvraag van de warmtepomp."),
            ("Ketel aanwezig ja/nee en vermogen [kWth]", "Bepaalt resterende brandstofgestuurde warmtedekking."),
            ("Warmtenet aanwezig ja/nee en capaciteit [kWth]", "Bepaalt externe warmtelevering."),
        ],
        "extra": [
            ("Aanvoertemperaturen", "Beïnvloeden haalbare COP en warmtepompgeschiktheid."),
            ("Brandstoftype ketel", "Nodig voor gasloosheidsinterpretatie."),
            ("Onderhouds- of regelbeperkingen", "Kan inzetbaarheid beperken."),
        ],
    },
    {
        "title": "11. Opslag",
        "intro": "Doel: flexibiliteit modelleren. Batterijen verlagen netpieken en benutten overschot; warmteopslag kan warmtepiek en gasvraag verlagen.",
        "essential": [
            ("Batterij aanwezig/gewenst", "Bepaalt of elektrische opslag wordt meegenomen."),
            ("Batterijcapaciteit [kWh]", "Bepaalt hoeveel energie kan worden opgeslagen."),
            ("Laad- en ontlaadvermogen [kW]", "Bepaalt hoe snel pieken kunnen worden verlaagd."),
            ("Laadstrategie batterij", "Bepaalt of de batterij alleen lokaal overschot gebruikt of ook contractruimte benut."),
        ],
        "extra": [
            ("Min/max state of charge [%]", "Bepaalt bruikbare opslagruimte."),
            ("Rendement", "Bepaalt verliezen bij laden en ontladen."),
            ("Warmteopslagcapaciteit [kWhth]", "Relevant voor gasloosheid en warmtepiekverlaging."),
        ],
    },
    {
        "title": "12. Meetdata en validatie",
        "intro": "Doel: modelresultaten vergelijken met werkelijkheid. Meetdata maakt aannames controleerbaar en verhoogt betrouwbaarheid.",
        "essential": [
            ("Elektriciteitsmeetdata of facturen", "Nodig om jaarverbruik en pieken te controleren."),
            ("Gasmeterdata of gasfacturen", "Nodig om warmtevraag en gasloosheid te toetsen."),
            ("Meetperiode en resolutie", "Bepaalt hoe goed de simulatie vergeleken kan worden."),
        ],
        "extra": [
            ("Submetering per proces of gebouwdeel", "Maakt oorzaken van pieken duidelijker."),
            ("Bekende afwijkende weken", "Voorkomt verkeerde conclusies door vakantie, storing of productiepieken."),
        ],
    },
]


def draw_wrapped(ax, x: float, y: float, text: str, *, size: float = 9.0, weight: str = "normal", width: int = 95) -> float:
    lines = textwrap.wrap(text, width=width) or [""]
    ax.text(x, y, "\n".join(lines), ha="left", va="top", fontsize=size, fontweight=weight)
    return y - 0.035 * len(lines)


def draw_items(ax, y: float, title: str, items: list[tuple[str, str]], *, required: bool) -> float:
    color = "#0B5FFF" if required else "#56616F"
    y = draw_wrapped(ax, 0.06, y, title, size=10.5, weight="bold")
    y -= 0.006
    for label, why in items:
        ax.text(0.075, y, "□", ha="left", va="top", fontsize=10, color=color)
        field = f"{label}: ________________________________"
        y = draw_wrapped(ax, 0.105, y, field, size=8.8, weight="bold", width=76)
        y = draw_wrapped(ax, 0.105, y, f"Waarom nodig: {why}", size=7.7, width=90)
        y -= 0.012
    return y


def add_page(pdf: PdfPages, section: dict) -> None:
    fig = plt.figure(figsize=(8.27, 11.69))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.text(0.06, 0.965, "Inventarisatie energieplanner", ha="left", va="top", fontsize=10, color="#56616F")
    ax.text(0.94, 0.965, "Essentieel en aanvullend", ha="right", va="top", fontsize=10, color="#56616F")
    y = 0.925
    y = draw_wrapped(ax, 0.06, y, section["title"], size=15, weight="bold", width=80)
    y -= 0.012
    y = draw_wrapped(ax, 0.06, y, section["intro"], size=9.3, width=100)
    y -= 0.025
    y = draw_items(ax, y, "Essentiële informatie", section["essential"], required=True)
    if y < 0.30:
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)
        fig = plt.figure(figsize=(8.27, 11.69))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.axis("off")
        ax.text(0.06, 0.965, "Inventarisatie energieplanner", ha="left", va="top", fontsize=10, color="#56616F")
        y = 0.92
    y -= 0.015
    y = draw_items(ax, y, "Aanvullend handig", section["extra"], required=False)
    ax.text(0.06, 0.075, "Opmerkingen:", ha="left", va="top", fontsize=9, fontweight="bold")
    for i in range(4):
        yy = 0.055 - i * 0.022
        ax.plot([0.06, 0.94], [yy, yy], color="#CBD2D9", linewidth=0.8)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def add_cover(pdf: PdfPages) -> None:
    fig = plt.figure(figsize=(8.27, 11.69))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.text(0.06, 0.88, "Inventarisatieformulier", ha="left", va="top", fontsize=24, fontweight="bold")
    ax.text(0.06, 0.835, "Energieplanner gebouw", ha="left", va="top", fontsize=17, color="#0B5FFF", fontweight="bold")
    intro = (
        "Gebruik dit formulier bij een klantbezoek om de minimale invoer voor de app te verzamelen. "
        "Essentiële informatie is nodig voor een betrouwbare eerste simulatie; aanvullende informatie "
        "maakt de analyse nauwkeuriger en helpt bij rapportage."
    )
    draw_wrapped(ax, 0.06, 0.77, intro, size=11, width=88)
    ax.text(0.06, 0.66, "Klant/locatie: ____________________________________________", ha="left", va="top", fontsize=11)
    ax.text(0.06, 0.61, "Datum bezoek: ____________________________________________", ha="left", va="top", fontsize=11)
    ax.text(0.06, 0.56, "Consultant: ______________________________________________", ha="left", va="top", fontsize=11)
    ax.text(0.06, 0.47, "Legenda", ha="left", va="top", fontsize=13, fontweight="bold")
    ax.text(0.08, 0.43, "□ Essentieel: nodig voor een bruikbare basissimulatie.", ha="left", va="top", fontsize=10)
    ax.text(0.08, 0.39, "□ Aanvullend handig: verhoogt nauwkeurigheid of maakt maatregelen concreter.", ha="left", va="top", fontsize=10)
    ax.text(0.06, 0.16, "Tip: verzamel waar mogelijk meetdata met kwartierwaarden. Dat maakt pieken, netruimte en validatie veel sterker.", ha="left", va="top", fontsize=10, color="#56616F")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(OUT) as pdf:
        add_cover(pdf)
        for section in SECTIONS:
            add_page(pdf, section)
    print(OUT)


if __name__ == "__main__":
    main()
