from __future__ import annotations

from copy import deepcopy
import io
import json
import os
import tempfile
import zipfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "energieplanner-matplotlib"))

import altair as alt
import matplotlib

matplotlib.use("Agg")
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from src.load import (
    BuildingType,
    YearClass,
    Orientation8,
    BuildingShape,
    SHAPE_FACTOR_BY_SHAPE,
    WeeklySchedule,
    make_default_load_config,
    run_load_simulation,
    run_energy_system_simulation,
)
from src.load.weather import read_weather_excel
from src.load.total import find_peak_week
from src.evaluation.grid import evaluate_grid, find_worst_grid_week, build_grid_duration_curve
from src.evaluation.calibration import prepare_validation_dataset
from src.io.measurements import load_measurement_bundle
from src.generation import simulate_pv, dispatch_wkk

st.set_page_config(page_title="Energieplanner gebouw", layout="wide")
st.title("Energieplanner gebouw")
st.caption("Modelleer het energiegebruik van een gebouw en verken opties zoals zonnepanelen, warmtebronnen en opslag.")

APP_DIR = Path(__file__).resolve().parent
WEATHER_PATH = APP_DIR / "Weatherdata 2008-2021.xlsx"
INVENTORY_PDF_PATH = APP_DIR / "assets" / "inventarisatie_energieplanner.pdf"
METHOD_DOCX_PATH = APP_DIR / "docs" / "methode_energieplanner.docx"
SIM_FREQ = None
TZ = "Europe/Amsterdam"
DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_TO_INT = {d: i for i, d in enumerate(DAY_LABELS)}
PROJECT_SCHEMA_VERSION = 1
PV_DIRECTION_TO_AZIMUTH = {
    "N": 0.0,
    "NE": 45.0,
    "E": 90.0,
    "SE": 135.0,
    "S": 180.0,
    "SW": 225.0,
    "W": 270.0,
    "NW": 315.0,
}
PV_EAST_WEST_OPTION = "east_west"
PV_NUMERIC_AZIMUTH_OPTIONS = list(PV_DIRECTION_TO_AZIMUTH.values())
PV_AZIMUTH_OPTIONS = PV_NUMERIC_AZIMUTH_OPTIONS + [PV_EAST_WEST_OPTION]

DAY_DISPLAY = {
    "Mon": "Maandag",
    "Tue": "Dinsdag",
    "Wed": "Woensdag",
    "Thu": "Donderdag",
    "Fri": "Vrijdag",
    "Sat": "Zaterdag",
    "Sun": "Zondag",
}

CHOICE_LABELS = {
    "pre_1992": "Voor 1992",
    "1992_2005": "1992-2005",
    "2006_2014": "2006-2014",
    "2015_plus": "2015 of nieuwer",
    "N": "Noord",
    "NE": "Noordoost",
    "E": "Oost",
    "SE": "Zuidoost",
    "S": "Zuid",
    "SW": "Zuidwest",
    "W": "West",
    "NW": "Noordwest",
    "compact": "Compact",
    "rectangular": "Rechthoekig",
    "l_shape": "L-vormig",
    "sprawling": "Uitgestrekt",
    "fixed": "Vaste COP",
    "seasonal": "Seizoensafhankelijke COP",
    "weather_dependent": "Weersafhankelijke COP",
    "electricity_led": "Sturen op elektriciteitsvraag",
    "thermal_led": "Sturen op warmtevraag",
    "heat_led": "Sturen op warmtevraag",
    "hybrid_peak_shaving": "Hybride piekverlaging",
    "heat_led_with_electric_cap": "Warmtegestuurd met elektrisch maximum",
    "must_run": "Altijd draaien",
    "off": "Uit",
    "gas": "Aardgas",
    "biogas": "Biogas",
    "hydrogen": "Waterstof",
    "generic": "Algemeen",
    "kW": "Vermogen in kW",
    "kWh_per_interval": "Energie per meetinterval",
    "none": "Niet invullen",
    "ffill": "Vorige waarde doortrekken",
    "bfill": "Volgende waarde terugvullen",
    "interpolate_time": "Interpoleren op tijd",
    "zero": "Nul invullen",
    "grid_import": "Netimport",
    "grid_export": "Teruglevering",
    "electric_load": "Elektrisch verbruik",
    "heat": "Warmte",
    "mean_to_hourly": "Gemiddelde naar uurwaarde",
    "sum_to_hourly": "Som naar uurwaarde",
    "mean": "Gemiddelde",
    "sum": "Som",
    "east_west": "Oost-West",
    "allow_export": "Terugleveren toestaan",
    "no_export": "Niet terugleveren",
    "direct": "Direct laden",
    "smart": "Slim laden",
    "0.0": "Noord",
    "45.0": "Noordoost",
    "90.0": "Oost",
    "135.0": "Zuidoost",
    "180.0": "Zuid",
    "225.0": "Zuidwest",
    "270.0": "West",
    "315.0": "Noordwest",
}

LABELS = {
    "def_building_type": "Gebouwtype",
    "def_year_class": "Bouwjaarklasse",
    "def_orientation": "Oriëntatie gebouw",
    "def_bvo": "Gebruiksoppervlak [m²]",
    "def_floors": "Aantal verdiepingen",
    "def_wwr": "Raampercentage",
    "def_shape": "Gebouwvorm",
    "def_shape_metric": "Vormfactor",
    "def_manual_shape": "Vormfactor handmatig instellen",
    "def_shape_manual": "Handmatige vormfactor",
    "bld_enable": "Gebouwinstellingen aanpassen",
    "bld_sched_enable": "Gebruiksschema aanpassen",
    "schedule_days": "Gebruiksdagen",
    "schedule_start": "Starttijd",
    "schedule_end": "Eindtijd",
    "subload_add": "Deellast toevoegen",
    "process_add": "Proces toevoegen",
    "subload_name": "Naam",
    "subload_remove": "Verwijder",
    "bld_t_heat_occ": "Verwarmingstemperatuur tijdens gebruik [°C]",
    "bld_t_heat_unocc": "Verwarmingstemperatuur buiten gebruik [°C]",
    "bld_t_cool_occ": "Koeltemperatuur tijdens gebruik [°C]",
    "bld_t_cool_unocc": "Koeltemperatuur buiten gebruik [°C]",
    "bld_cop_winter": "COP referentieverwarming winter",
    "bld_cop_spring": "COP referentieverwarming lente",
    "bld_cop_summer": "COP referentieverwarming zomer",
    "bld_cop_autumn": "COP referentieverwarming herfst",
    "bld_eer_winter": "EER referentiekoeling winter",
    "bld_eer_spring": "EER referentiekoeling lente",
    "bld_eer_summer": "EER referentiekoeling zomer",
    "bld_eer_autumn": "EER referentiekoeling herfst",
    "ref_heat_enabled": "Referentie elektrische verwarming gebruiken",
    "ref_cop_winter": "Referentie COP verwarming winter",
    "ref_cop_spring": "Referentie COP verwarming lente",
    "ref_cop_summer": "Referentie COP verwarming zomer",
    "ref_cop_autumn": "Referentie COP verwarming herfst",
    "ref_eer_winter": "Referentie EER koeling winter",
    "ref_eer_spring": "Referentie EER koeling lente",
    "ref_eer_summer": "Referentie EER koeling zomer",
    "ref_eer_autumn": "Referentie EER koeling herfst",
    "bld_eta_wtw": "Warmteterugwinning ventilatie",
    "bld_qv10": "Luchtdichtheid qv10 [m³/h per m²]",
    "bld_g_value": "Zontoetreding glas",
    "bld_shading_factor": "Zonweringfactor",
    "pe_enable": "Standaard elektrisch verbruik aanpassen",
    "pe_occ": "Elektrisch vermogen tijdens gebruik [W/m²]",
    "pe_unocc": "Elektrisch vermogen buiten gebruik [W/m²]",
    "pr_enable": "Standaard procesverbruik aanpassen",
    "pr_pp": "Procesvermogen tijdens bedrijf [kW]",
    "pr_pi": "Procesvermogen buiten bedrijf [kW]",
    "subload_p_occ": "Vermogen tijdens gebruik [W/m²]",
    "subload_p_unocc": "Vermogen buiten gebruik [W/m²]",
    "proc_p_process": "Procesvermogen tijdens bedrijf [kW]",
    "proc_p_idle": "Procesvermogen buiten bedrijf [kW]",
    "mob_n_cars": "Aantal elektrische auto's",
    "mob_p_charger_max": "Laadvermogen per auto [kW]",
    "mob_duty_cycle": "Gelijktijdige laadfractie",
    "mob_battery_capacity": "Gemiddelde batterijcapaciteit [kWh]",
    "mob_arrival_soc": "Aankomstlading [%]",
    "mob_target_soc": "Gewenste vertreklading [%]",
    "mob_arrival_hour": "Aankomsttijd",
    "mob_departure_hour": "Vertrektijd",
    "mob_cars_present": "Aanwezige auto's [%]",
    "mob_charge_mode": "Laadmodus",
    "mob_site_cap": "Maximaal laadvermogen locatie [kW]",
    "ov_enable": "Standaard overig verbruik aanpassen",
    "ov_occ": "Overig vermogen tijdens gebruik [W/m²]",
    "ov_unocc": "Overig vermogen buiten gebruik [W/m²]",
    "pv_enabled": "Zonnepanelen meenemen",
    "pv_cap": "Vermogen zonnepanelen [kWp]",
    "pv_tilt": "Hellingshoek zonnepanelen [°]",
    "pv_azimuth": "Richting zonnepanelen",
    "pv_no_export": "PV niet terugleveren",
    "pv_pr": "Prestatieverhouding zonnepanelen",
    "pv_inv_eff": "Omvormerrendement",
    "pv_temp_coeff": "Temperatuurcorrectie zonnepanelen [/°C]",
    "pv_site_cap": "Maximale PV-teruglevering [kW]",
    "wkk_enabled": "WKK meenemen",
    "wkk_p_rated": "Elektrisch WKK-vermogen [kW]",
    "wkk_min_frac": "Minimale WKK-belasting",
    "wkk_el_eff": "Elektrisch rendement WKK",
    "wkk_th_eff": "Thermisch rendement WKK",
    "wkk_dispatch_mode": "WKK-regeling",
    "grid_cap_kW": "Gecontracteerd netvermogen [kW]",
    "hp_enabled": "Warmtepomp meenemen",
    "hp_capacity": "Warmtepompvermogen [kWth]",
    "hp_cop_mode": "COP-berekening warmtepomp",
    "hp_cop_nominal": "Nominale COP warmtepomp",
    "hp_min_frac": "Minimale deellast warmtepomp",
    "hp_site_cap": "Maximaal elektrisch warmtepompvermogen [kW]",
    "boiler_enabled": "Ketel meenemen",
    "boiler_capacity": "Ketelvermogen [kWth]",
    "boiler_eff": "Ketelrendement",
    "boiler_min_frac": "Minimale deellast ketel",
    "boiler_fuel_type": "Brandstoftype ketel",
    "dh_enabled": "Warmtenet meenemen",
    "dh_capacity": "Warmtenetvermogen [kWth]",
    "dh_tariff": "Warmtenettarief",
    "bat_enabled": "Batterij meenemen",
    "bat_capacity": "Batterijcapaciteit [kWh]",
    "bat_soc_init": "Startvulling batterij [%]",
    "bat_p_charge": "Laadvermogen batterij [kW]",
    "bat_soc_min": "Minimale vulling batterij [%]",
    "bat_p_discharge": "Ontlaadvermogen batterij [kW]",
    "bat_soc_max": "Maximale vulling batterij [%]",
    "bat_eff": "Rondrendement batterij",
    "bat_charge_strategy": "Laadstrategie batterij",
    "th_enabled": "Warmteopslag meenemen",
    "th_capacity": "Warmteopslagcapaciteit [kWhth]",
    "th_soc_init": "Startvulling warmteopslag [%]",
    "th_p_charge": "Laadvermogen warmteopslag [kWth]",
    "th_soc_min": "Minimale vulling warmteopslag [%]",
    "th_p_discharge": "Ontlaadvermogen warmteopslag [kWth]",
    "th_soc_max": "Maximale vulling warmteopslag [%]",
    "th_loss": "Warmteverlies per uur",
    "th_eff_charge": "Laadrendement warmteopslag",
    "th_eff_discharge": "Ontlaadrendement warmteopslag",
    "measurement_enabled": "Meetdata gebruiken",
    "measurement_power_unit_mode": "Eenheid meetdata",
    "measurement_expected_resolution": "Tijdresolutie meetdata",
    "measurement_gap_fill_method": "Ontbrekende meetwaarden",
    "measurement_comparison_mode": "Vergelijkingsgrootheid",
    "measurement_resample_policy": "Omrekening meetdata",
    "measurement_upload": "Upload meetdata (.csv, .xlsx)",
}

HELP_TEXTS = {
    "def_building_type": "Wat: het type gebouw. In het model kiest dit standaardprofielen voor gebruik, apparatuur en warmtevraag. Effect: een ander type verandert het basisverbruik en de verdeling over de dag.",
    "def_year_class": "Wat: de bouw- of renovatieperiode. In het model bepaalt dit de gebouwkwaliteit en isolatie-aannames. Effect: oudere klassen geven meestal meer warmteverlies en hogere warmtevraag.",
    "def_orientation": "Wat: de globale oriëntatie van het gebouw. In het model beïnvloedt dit zoninstraling op de gevels. Effect: een andere richting kan warmte- en koelvraag verschuiven.",
    "def_bvo": "Wat: het bruto vloeroppervlak. In het model schaalt dit gebouwvraag, apparatuur en overige lasten. Effect: meer oppervlak geeft meestal meer warmte-, koel- en elektriciteitsvraag.",
    "def_floors": "Wat: het aantal verdiepingen. In het model helpt dit bij de gebouwvorm en verhouding tussen dak, gevel en vloeroppervlak. Effect: dit kan warmteverlies en zoninvloed veranderen.",
    "def_wwr": "Wat: het aandeel gevel dat uit glas bestaat. In het model beïnvloedt dit zoninstraling, warmteverlies en koelvraag. Effect: meer glas kan meer koeling en soms minder verwarming geven.",
    "def_shape": "Wat: de globale gebouwvorm. In het model wordt dit vertaald naar een vormfactor voor warmteverlies. Effect: compactere vormen verliezen meestal minder warmte.",
    "def_manual_shape": "Wat: een handmatige overschrijving van de vormfactor. In het model vervangt dit de automatische waarde. Effect: gebruik dit alleen als de echte compactheid bekend is.",
    "def_shape_manual": "Wat: de zelf gekozen vormfactor. In het model bepaalt dit hoe groot het warmteverlies via de gebouwschil is. Effect: hoger betekent meestal meer warmtevraag.",
    "bld_enable": "Wat: hiermee pas je gebouwdetails handmatig aan. In het model overschrijven deze waarden de standaardinstellingen. Effect: de warmtevraag, koelvraag en installatievraag veranderen direct.",
    "bld_sched_enable": "Wat: hiermee stel je gebruiksdagen en gebruiksuren zelf in. In het model bepaalt dit wanneer bezette instellingen gelden. Effect: langere gebruiksuren verhogen meestal de energievraag.",
    "schedule_days": "Wat: dagen waarop het gebouw of de deellast actief is. In het model worden alleen deze dagen als gebruiksperiode behandeld. Effect: meer dagen verhogen het week- en jaarverbruik.",
    "schedule_start": "Wat: startuur van de actieve periode. In het model begint dan het bezette of actieve profiel. Effect: eerder starten verschuift verbruik naar de ochtend en verhoogt actieve uren.",
    "schedule_end": "Wat: einduur van de actieve periode. In het model stopt dan het bezette of actieve profiel. Effect: later eindigen verhoogt actieve uren en vaak de totale vraag.",
    "bld_t_heat_occ": "Wat: gewenste temperatuur tijdens gebruik. In het model bepaalt dit wanneer verwarming nodig is. Effect: hoger instellen verhoogt de warmtevraag.",
    "bld_t_heat_unocc": "Wat: gewenste temperatuur buiten gebruik. In het model bepaalt dit nacht- en weekendverwarming. Effect: hoger instellen verhoogt basiswarmtevraag.",
    "bld_t_cool_occ": "Wat: temperatuur waarboven tijdens gebruik wordt gekoeld. In het model bepaalt dit de koelvraag. Effect: lager instellen verhoogt de koelvraag.",
    "bld_t_cool_unocc": "Wat: temperatuur waarboven buiten gebruik wordt gekoeld. In het model bepaalt dit koeling buiten gebruikstijd. Effect: lager instellen kan extra nacht- en weekendkoeling geven.",
    "bld_cop_winter": "Wat: oude projectwaarde voor referentieverwarming. In het model wordt deze gemapt naar de referentie-installatie. Effect: hogere COP verlaagt stroomgebruik voor elektrische fallback-verwarming.",
    "bld_cop_spring": "Wat: oude projectwaarde voor referentieverwarming. In het model wordt deze gemapt naar de referentie-installatie. Effect: hogere COP verlaagt stroomgebruik voor elektrische fallback-verwarming.",
    "bld_cop_summer": "Wat: oude projectwaarde voor referentieverwarming. In het model wordt deze gemapt naar de referentie-installatie. Effect: hogere COP verlaagt stroomgebruik voor elektrische fallback-verwarming.",
    "bld_cop_autumn": "Wat: oude projectwaarde voor referentieverwarming. In het model wordt deze gemapt naar de referentie-installatie. Effect: hogere COP verlaagt stroomgebruik voor elektrische fallback-verwarming.",
    "bld_eer_winter": "Wat: oude projectwaarde voor referentiekoeling. In het model wordt deze gemapt naar de referentie-installatie. Effect: hogere EER verlaagt stroomgebruik voor koeling.",
    "bld_eer_spring": "Wat: oude projectwaarde voor referentiekoeling. In het model wordt deze gemapt naar de referentie-installatie. Effect: hogere EER verlaagt stroomgebruik voor koeling.",
    "bld_eer_summer": "Wat: oude projectwaarde voor referentiekoeling. In het model wordt deze gemapt naar de referentie-installatie. Effect: hogere EER verlaagt stroomgebruik voor koeling.",
    "bld_eer_autumn": "Wat: oude projectwaarde voor referentiekoeling. In het model wordt deze gemapt naar de referentie-installatie. Effect: hogere EER verlaagt stroomgebruik voor koeling.",
    "ref_heat_enabled": "Wat: elektrische fallback voor resterende warmtevraag. In het model wordt alleen warmtevraag die niet door WKK, opslag, warmtepomp, ketel of warmtenet is geleverd omgerekend naar elektriciteit. Effect: aan voorkomt ongedekte warmte, maar verhoogt netvraag; uit laat warmte ongedekt als capaciteit ontbreekt.",
    "ref_cop_winter": "Wat: rendement van referentie elektrische verwarming in de winter. In het model wordt resterende warmtevraag gedeeld door deze COP. Effect: hogere COP geeft minder elektriciteitsvraag voor dezelfde warmte.",
    "ref_cop_spring": "Wat: rendement van referentie elektrische verwarming in de lente. In het model wordt resterende warmtevraag gedeeld door deze COP. Effect: hogere COP geeft minder elektriciteitsvraag voor dezelfde warmte.",
    "ref_cop_summer": "Wat: rendement van referentie elektrische verwarming in de zomer. In het model wordt resterende warmtevraag gedeeld door deze COP. Effect: hogere COP geeft minder elektriciteitsvraag voor dezelfde warmte.",
    "ref_cop_autumn": "Wat: rendement van referentie elektrische verwarming in de herfst. In het model wordt resterende warmtevraag gedeeld door deze COP. Effect: hogere COP geeft minder elektriciteitsvraag voor dezelfde warmte.",
    "ref_eer_winter": "Wat: rendement van elektrische referentiekoeling in de winter. In het model wordt koelvraag gedeeld door deze EER. Effect: hogere EER verlaagt stroomgebruik voor koeling.",
    "ref_eer_spring": "Wat: rendement van elektrische referentiekoeling in de lente. In het model wordt koelvraag gedeeld door deze EER. Effect: hogere EER verlaagt stroomgebruik voor koeling.",
    "ref_eer_summer": "Wat: rendement van elektrische referentiekoeling in de zomer. In het model wordt koelvraag gedeeld door deze EER. Effect: hogere EER verlaagt stroomgebruik voor koeling.",
    "ref_eer_autumn": "Wat: rendement van elektrische referentiekoeling in de herfst. In het model wordt koelvraag gedeeld door deze EER. Effect: hogere EER verlaagt stroomgebruik voor koeling.",
    "bld_eta_wtw": "Wat: aandeel ventilatiewarmte dat wordt teruggewonnen. In het model verlaagt dit ventilatieverlies. Effect: hoger verlaagt de warmtevraag.",
    "bld_qv10": "Wat: maat voor luchtlekken in het gebouw. In het model verhoogt dit infiltratieverlies. Effect: hoger betekent meestal meer warmtevraag.",
    "bld_g_value": "Wat: hoeveel zonnewarmte door glas binnenkomt. In het model beïnvloedt dit zonnewinst en koeling. Effect: hoger kan verwarming verlagen maar koeling verhogen.",
    "bld_shading_factor": "Wat: correctie voor zonwering of beschaduwing. In het model verlaagt dit effectieve zoninstraling. Effect: lager verlaagt vaak koelvraag, maar ook nuttige zonnewarmte.",
    "pe_enable": "Wat: handmatige aanpassing van standaard elektrisch verbruik. In het model vervangt dit de standaard vermogens per m². Effect: hogere waarden verhogen elektrisch verbruik.",
    "pe_occ": "Wat: elektrisch vermogen per m² tijdens gebruik. In het model vormt dit de actieve elektrische basislast. Effect: hoger verhoogt pieken en jaarverbruik.",
    "pe_unocc": "Wat: elektrisch vermogen per m² buiten gebruik. In het model vormt dit sluip- en basisverbruik. Effect: hoger verhoogt nacht- en weekendverbruik.",
    "pr_enable": "Wat: handmatige aanpassing van procesverbruik. In het model vervangt dit het standaard procesprofiel. Effect: hogere waarden verhogen vooral procesuren en basislast.",
    "pr_pp": "Wat: vermogen van processen tijdens bedrijf. In het model wordt dit als proceslast meegenomen. Effect: hoger verhoogt elektriciteitsvraag tijdens procesuren.",
    "pr_pi": "Wat: rustvermogen van processen buiten bedrijf. In het model blijft dit buiten actieve uren aanwezig. Effect: hoger verhoogt basislast.",
    "subload_name": "Wat: herkenbare naam van deze deellast. In het model verandert de naam de berekening niet. Effect: maakt resultaten en instellingen beter te begrijpen.",
    "subload_p_occ": "Wat: vermogen van deze deellast tijdens gebruik. In het model telt dit mee in het actieve profiel. Effect: hoger verhoogt pieken en jaarverbruik.",
    "subload_p_unocc": "Wat: vermogen van deze deellast buiten gebruik. In het model telt dit mee in het rustprofiel. Effect: hoger verhoogt basisverbruik.",
    "proc_p_process": "Wat: vermogen van dit proces tijdens bedrijf. In het model wordt dit toegevoegd aan procesverbruik. Effect: hoger verhoogt elektriciteitsvraag tijdens procesuren.",
    "proc_p_idle": "Wat: rustvermogen van dit proces buiten bedrijf. In het model blijft dit aanwezig buiten actieve uren. Effect: hoger verhoogt basislast.",
    "mob_n_cars": "Wat: aantal elektrische auto's dat kan laden. In het model schaalt dit de totale laadenergie en het maximale laadvermogen. Effect: meer auto's verhogen laadverbruik en mogelijk pieken.",
    "mob_p_charger_max": "Wat: maximaal laadvermogen per auto. In het model begrenst dit laadsnelheid per aanwezige auto. Effect: hoger kan sneller laden, maar ook hogere pieken veroorzaken.",
    "mob_duty_cycle": "Wat: aandeel auto's dat tegelijk laadt. In het model begrenst dit gelijktijdig laadvermogen. Effect: hoger verhoogt de piekbelasting.",
    "mob_battery_capacity": "Wat: gemiddelde batterijgrootte van de auto's. In het model bepaalt dit hoeveel energie nodig is om van aankomstlading naar vertreklading te gaan. Effect: groter betekent meer laadenergie.",
    "mob_arrival_soc": "Wat: gemiddelde lading bij aankomst. In het model is dit het startpunt voor de laadbehoefte. Effect: hoger betekent minder benodigde laadenergie.",
    "mob_target_soc": "Wat: gewenste lading bij vertrek. In het model is dit het doelniveau voor laden. Effect: hoger betekent meer benodigde laadenergie.",
    "mob_arrival_hour": "Wat: uur waarop auto's gemiddeld aankomen. In het model start dan het laadvenster. Effect: eerder aankomen geeft meer tijd om slim te laden.",
    "mob_departure_hour": "Wat: uur waarop auto's gemiddeld vertrekken. In het model eindigt dan het laadvenster. Effect: later vertrekken geeft meer tijd om binnen contractruimte te laden.",
    "mob_cars_present": "Wat: aandeel auto's dat gemiddeld aanwezig is. In het model schaalt dit de laadenergie en laadpiek. Effect: lager betekent minder totale laadbehoefte.",
    "mob_charge_mode": "Wat: bepaalt hoe auto's laden.\n\nOpties:\n- Direct laden: start bij aankomst en laadt zo snel mogelijk tot de gewenste vertreklading is gehaald.\n- Slim laden: laadt alleen wanneer de gebouwbasislast plus laden onder het contractvermogen blijft.\n\nEffect: slim laden verlaagt contractoverschrijding, maar kan laadtekort geven als er te weinig netruimte is.",
    "mob_site_cap": "Wat: maximum voor alle laadpunten samen. In het model kapt dit mobiliteitsvermogen af. Effect: lager beperkt pieken, maar kan laden spreiden of onvolledig maken.",
    "ov_enable": "Wat: handmatige aanpassing van overig verbruik. In het model vervangt dit de standaard restlast. Effect: hogere waarden verhogen het totale elektriciteitsverbruik.",
    "ov_occ": "Wat: overig vermogen per m² tijdens gebruik. In het model telt dit mee als restverbruik. Effect: hoger verhoogt actieve basislast.",
    "ov_unocc": "Wat: overig vermogen per m² buiten gebruik. In het model telt dit mee als rustverbruik. Effect: hoger verhoogt nacht- en weekendverbruik.",
    "pv_enabled": "Wat: keuze om zonnepanelen mee te nemen. In het model wordt PV-opwek dan berekend uit weerdata en paneelinstellingen. Effect: aan verlaagt netimport en kan teruglevering geven.",
    "pv_cap": "Wat: totaal piekvermogen van de zonnepanelen. In het model schaalt dit de PV-opbrengst. Effect: hoger geeft meer zonnestroom en mogelijk meer teruglevering.",
    "pv_tilt": "Wat: hoek van de panelen ten opzichte van horizontaal. In het model beïnvloedt dit instraling op het paneel. Effect: andere hoek verschuift opbrengst per seizoen.",
    "pv_azimuth": "Wat: windrichting van de zonnepanelen. In het model wordt deze richting vertaald naar graden en beïnvloedt dit de PV-opbrengst. Effect: zuid geeft vaak hoge jaaropbrengst; oost geeft meer ochtendopbrengst en west meer middagopbrengst.",
    "pv_no_export": "Wat: simuleert een EMS dat PV-overschot niet teruglevert. In het model wordt PV eerst lokaal gebruikt, daarna kan de batterij laden, en resterend overschot wordt afgetopt.",
    "pv_pr": "Wat: praktijkfactor voor verliezen zoals vuil, bekabeling en mismatch. In het model vermenigvuldigt dit de PV-opbrengst. Effect: lager verlaagt de berekende opbrengst.",
    "pv_inv_eff": "Wat: rendement van de omvormer. In het model wordt DC-opwek hiermee naar bruikbare AC-stroom vertaald. Effect: hoger geeft iets meer bruikbare stroom.",
    "pv_temp_coeff": "Wat: rendementsverlies bij warme panelen. In het model corrigeert dit PV-opbrengst op basis van temperatuur. Effect: sterker negatief verlaagt opbrengst op warme dagen.",
    "pv_site_cap": "Wat: maximale PV-teruglevering of output. In het model wordt PV boven deze grens afgetopt. Effect: lager beperkt terugleverpieken maar kan opwek afregelen.",
    "wkk_enabled": "Wat: keuze om WKK mee te nemen. In het model levert WKK tegelijk elektriciteit en warmte. Effect: aan kan netimport en warmtevraag verlagen, maar verhoogt brandstofgebruik.",
    "wkk_p_rated": "Wat: maximaal elektrisch vermogen van de WKK. In het model begrenst dit WKK-stroomproductie. Effect: hoger kan meer netimport vervangen.",
    "wkk_min_frac": "Wat: minimale belasting waarop de WKK mag draaien. In het model voorkomt dit te laag moduleren. Effect: hoger maakt de WKK minder flexibel.",
    "wkk_el_eff": "Wat: deel van brandstof dat elektriciteit wordt. In het model bepaalt dit brandstofgebruik per kWh stroom. Effect: hoger verlaagt brandstofgebruik.",
    "wkk_th_eff": "Wat: deel van brandstof dat nuttige warmte wordt. In het model bepaalt dit warmtelevering uit WKK. Effect: hoger verlaagt resterende warmtevraag.",
    "wkk_dispatch_mode": "Wat: regelstrategie voor de WKK. In het model bepaalt dit wanneer de WKK draait.\n\nOpties:\n- Sturen op elektriciteitsvraag: gebruiken als de WKK vooral netimport moet verlagen.\n- Sturen op warmtevraag: gebruiken als warmteproductie leidend is.\n- Hybride piekverlaging: gebruiken als netpieken belangrijk zijn.\n- Warmtegestuurd met elektrisch maximum: gebruiken als warmte nodig is, maar elektrische pieken begrensd moeten blijven.\n- Altijd draaien: gebruiken voor een vaste must-run aanname.\n- Uit: WKK levert niets.\n\nEffect: de keuze verschuift netimport, warmtelevering en brandstofgebruik.",
    "grid_cap_kW": "Wat: afgesproken maximaal netvermogen. In het model wordt dit gebruikt om overschrijdingen en netstress te beoordelen. Effect: lager maakt knelpunten sneller zichtbaar.",
    "hp_enabled": "Wat: keuze om de warmtepomp mee te nemen. In het model levert de warmtepomp warmte met elektriciteit. Effect: aan verlaagt gasvraag maar verhoogt elektriciteitsvraag.",
    "hp_capacity": "Wat: maximale warmteproductie van de warmtepomp. In het model begrenst dit hoeveel warmtevraag de warmtepomp dekt. Effect: hoger dekt meer warmte maar kan meer netvermogen vragen.",
    "hp_cop_mode": "Wat: manier waarop warmtepomprendement wordt bepaald.\n\nOpties:\n- Vaste COP: één rendement voor het hele jaar; handig voor snelle scenario's.\n- Seizoensafhankelijke COP: rendement verschilt per seizoen; geschikt als detaildata ontbreekt.\n- Weersafhankelijke COP: rendement reageert op buitentemperatuur; meest realistisch voor jaarprofielen.\n\nEffect: lagere COP verhoogt elektriciteitsvraag van de warmtepomp.",
    "hp_cop_nominal": "Wat: standaardrendement van de warmtepomp. In het model zet dit warmte om naar elektriciteitsverbruik. Effect: hoger verlaagt stroomvraag voor dezelfde warmte.",
    "hp_min_frac": "Wat: laagste deelvermogen waarop de warmtepomp kan draaien. In het model beperkt dit modulatie. Effect: hoger maakt de warmtepomp minder flexibel bij lage vraag.",
    "hp_site_cap": "Wat: maximaal elektrisch vermogen voor de warmtepomp. In het model begrenst dit stroomgebruik van de warmtepomp. Effect: lager verlaagt pieken maar kan ongedekte warmte geven.",
    "boiler_enabled": "Wat: keuze om een ketel mee te nemen. In het model kan de ketel resterende warmtevraag leveren. Effect: aan verhoogt leveringszekerheid maar kan brandstofgebruik geven.",
    "boiler_capacity": "Wat: maximale warmteproductie van de ketel. In het model begrenst dit ketelwarmte. Effect: hoger dekt meer piekvraag.",
    "boiler_eff": "Wat: rendement van brandstof naar warmte. In het model bepaalt dit brandstofgebruik. Effect: hoger verlaagt brandstofgebruik voor dezelfde warmte.",
    "boiler_min_frac": "Wat: laagste deelvermogen waarop de ketel kan draaien. In het model beperkt dit modulatie. Effect: hoger maakt de ketel minder flexibel.",
    "boiler_fuel_type": "Wat: brandstofsoort van de ketel. In het model labelt dit de brandstofstroom.\n\nOpties:\n- Aardgas: gebruik voor de huidige fossiele referentie.\n- Biogas: gebruik voor een hernieuwbaar gas-scenario.\n- Waterstof: gebruik voor een toekomstscenario.\n- Algemeen: gebruik als de brandstof nog onbekend is.\n\nEffect: nu vooral interpretatie; later bruikbaar voor emissies en kosten.",
    "dh_enabled": "Wat: keuze om warmtenet mee te nemen. In het model kan het warmtenet warmtevraag leveren. Effect: aan kan ketel of warmtepomp aanvullen.",
    "dh_capacity": "Wat: maximale warmte uit het warmtenet. In het model begrenst dit warmtenetlevering. Effect: hoger dekt meer warmtevraag.",
    "dh_tariff": "Wat: tarief of kostenplaceholder voor warmtenet. In het model wordt dit nog beperkt gebruikt. Effect: aanpassen heeft nu vooral documenterende waarde.",
    "bat_enabled": "Wat: keuze om batterijopslag mee te nemen. In het model kan elektriciteit tijdelijk worden opgeslagen. Effect: aan kan pieken verlagen en eigen PV-gebruik verhogen.",
    "bat_capacity": "Wat: hoeveelheid elektriciteit die de batterij kan opslaan. In het model bepaalt dit opslagduur. Effect: groter kan meer energie verschuiven.",
    "bat_soc_init": "Wat: vulling aan het begin van de simulatie. In het model start de batterij hiermee. Effect: beïnvloedt vooral de eerste simulatiedagen.",
    "bat_p_charge": "Wat: maximale laadsnelheid van de batterij. In het model begrenst dit hoeveel overschot per uur wordt opgeslagen. Effect: hoger benut meer piekoverschot.",
    "bat_soc_min": "Wat: minimale toegestane vulling. In het model voorkomt dit verder ontladen. Effect: hoger verlaagt bruikbare capaciteit.",
    "bat_p_discharge": "Wat: maximale ontlaadsnelheid van de batterij. In het model begrenst dit hoeveel netvraag kan worden verlaagd. Effect: hoger verlaagt pieken sterker.",
    "bat_soc_max": "Wat: maximale toegestane vulling. In het model voorkomt dit verder laden. Effect: lager verlaagt opslagruimte.",
    "bat_eff": "Wat: totaalrendement van laden en ontladen. In het model gaat bij opslag een deel verloren. Effect: lager betekent meer energieverlies.",
    "bat_charge_strategy": "Wat: manier waarop de batterij mag laden.\n\nOpties:\n- Alleen lokaal overschot: batterij laadt alleen met PV/WKK-overschot; goed voor hoger eigenverbruik.\n- Laden tot contractruimte: batterij mag laden zolang netimport onder contractvermogen blijft; goed om beschikbare netruimte te benutten.\n\nEffect: dit verandert batterijvulling, netimport en teruglevering.",
    "th_enabled": "Wat: keuze om warmteopslag mee te nemen. In het model kan warmte tijdelijk worden opgeslagen. Effect: aan kan warmteproductie verschuiven.",
    "th_capacity": "Wat: hoeveelheid warmte die kan worden opgeslagen. In het model bepaalt dit opslagduur voor warmte. Effect: groter kan warmtevraag langer overbruggen.",
    "th_soc_init": "Wat: startvulling van de warmteopslag. In het model begint de opslag hiermee. Effect: beïnvloedt vooral het begin van de simulatie.",
    "th_p_charge": "Wat: maximale snelheid waarmee warmte wordt opgeslagen. In het model begrenst dit laden van warmteopslag. Effect: hoger slaat meer overschot of productie op.",
    "th_soc_min": "Wat: minimale toegestane vulling. In het model voorkomt dit verder ontladen. Effect: hoger verlaagt bruikbare warmteopslag.",
    "th_p_discharge": "Wat: maximale snelheid waarmee warmte wordt geleverd. In het model begrenst dit ontladen. Effect: hoger kan warmtepiek beter afdekken.",
    "th_soc_max": "Wat: maximale toegestane vulling. In het model voorkomt dit verder laden. Effect: lager verlaagt opslagruimte.",
    "th_loss": "Wat: warmteverlies per uur. In het model neemt opgeslagen warmte hiermee af. Effect: hoger maakt opslag minder effectief.",
    "th_eff_charge": "Wat: rendement bij warmte opslaan. In het model gaat bij laden warmte verloren. Effect: lager geeft meer verlies.",
    "th_eff_discharge": "Wat: rendement bij warmte gebruiken. In het model gaat bij ontladen warmte verloren. Effect: lager geeft minder bruikbare warmte.",
    "measurement_enabled": "Wat: keuze om meetdata te gebruiken. In het model wordt meetdata naast simulatie gezet. Effect: aan maakt validatie van modelresultaten mogelijk.",
    "measurement_power_unit_mode": "Wat: geeft aan of meetdata vermogen of energie per interval is.\n\nOpties:\n- Vermogen in kW: gebruik als elke waarde een gemiddeld/actueel vermogen is.\n- Energie per meetinterval: gebruik als elke waarde kWh per kwartier/uur is.\n\nEffect: verkeerde keuze maakt de vergelijking te hoog of te laag.",
    "measurement_expected_resolution": "Wat: tijdstap van de meetdata. In het model wordt data hierop gecontroleerd en omgerekend. Effect: verkeerde resolutie kan validatie vertekenen.",
    "measurement_gap_fill_method": "Wat: methode voor ontbrekende meetwaarden.\n\nOpties:\n- Niet invullen: behoudt gaten; veilig bij onzekerheid.\n- Vorige waarde doortrekken: handig bij korte meetgaten.\n- Volgende waarde terugvullen: alternatief bij korte gaten.\n- Interpoleren op tijd: geschikt voor geleidelijke signalen.\n- Nul invullen: alleen gebruiken als ontbrekend echt nul betekent.\n\nEffect: invullen kan vergelijking stabieler maken, maar voegt aannames toe.",
    "measurement_comparison_mode": "Wat: grootheid waarop simulatie en meting worden vergeleken.\n\nOpties:\n- Netimport: vergelijk afname van het net.\n- Teruglevering: vergelijk levering aan het net.\n- Elektrisch verbruik: vergelijk gebouwvraag.\n- Gas: vergelijk brandstofgebruik.\n- Warmte: vergelijk warmtevraag of levering.\n\nEffect: verkeerde keuze vergelijkt de verkeerde energiestroom.",
    "measurement_resample_policy": "Wat: manier waarop meetdata naar een andere tijdstap gaat.\n\nOpties:\n- Gemiddelde naar uurwaarde: geschikt voor vermogen in kW.\n- Som naar uurwaarde: geschikt voor energie per interval.\n- Gemiddelde: behoudt gemiddelde bij andere resolutie.\n- Som: telt waarden op.\n- Niet invullen: geen omrekening.\n\nEffect: verkeerde keuze kan waarden te hoog of te laag maken.",
    "measurement_upload": "Wat: bestand met werkelijke meetdata. In het model wordt dit ingelezen voor validatie. Effect: goede meetdata maakt modelcontrole betrouwbaarder.",
}


def label_for(key: str, fallback: str | None = None) -> str:
    return LABELS.get(key, fallback or key)


def help_for(key: str) -> str | None:
    return HELP_TEXTS.get(key)


def choice_label(value: str) -> str:
    return CHOICE_LABELS.get(str(value), str(value))


def app_state_defaults() -> dict:
    return {
        "pelektro_subloads": [],
        "pprocess_subloads": [],
        "poverig_subloads": [],
        "def_building_type": BuildingType.OFFICE.value,
        "def_year_class": YearClass.Y2015_PLUS.value,
        "def_orientation": Orientation8.S.value,
        "def_bvo": 2500.0,
        "def_floors": 1,
        "def_wwr": 0.35,
        "def_shape": BuildingShape.RECTANGULAR.value,
        "def_manual_shape": False,
        "def_shape_manual": 1.0,
        "grid_cap_kW": 50.0,
        "pv_enabled": True,
        "pv_cap": 250.0,
        "pv_tilt": 35.0,
        "pv_azimuth": 180.0,
        "pv_no_export": False,
        "pv_pr": 0.85,
        "pv_inv_eff": 0.98,
        "pv_temp_coeff": -0.004,
        "pv_site_cap": 0.0,
        "wkk_enabled": False,
        "wkk_p_rated": 150.0,
        "wkk_min_frac": 0.0,
        "wkk_el_eff": 0.40,
        "wkk_th_eff": 0.45,
        "bat_enabled": False,
        "bat_capacity": 0.0,
        "bat_p_charge": 0.0,
        "bat_p_discharge": 0.0,
        "bat_eff": 0.92,
        "bat_soc_init": 50.0,
        "bat_soc_min": 10.0,
        "bat_soc_max": 90.0,
        "bat_charge_strategy": "surplus_only",
        "th_enabled": False,
        "th_capacity": 0.0,
        "th_p_charge": 0.0,
        "th_p_discharge": 0.0,
        "th_loss": 0.0,
        "th_soc_init": 50.0,
        "th_soc_min": 10.0,
        "th_soc_max": 90.0,
        "th_eff_charge": 0.95,
        "th_eff_discharge": 0.95,
        "hp_enabled": False,
        "hp_capacity": 0.0,
        "hp_cop_mode": "fixed",
        "hp_cop_nominal": 3.5,
        "hp_min_frac": 0.0,
        "hp_site_cap": 0.0,
        "boiler_enabled": False,
        "boiler_capacity": 0.0,
        "boiler_eff": 0.92,
        "boiler_min_frac": 0.0,
        "boiler_fuel_type": "gas",
        "dh_enabled": False,
        "dh_capacity": 0.0,
        "dh_tariff": 0.0,
        "wkk_dispatch_mode": "electricity_led",
        "heat_dispatch_mode": "power_min_grid",
        "thermal_storage_strategy": "passive",
        "heat_source_priority_mode": "prefer_hp_then_storage_then_boiler_then_dh",
        "measurement_enabled": False,
        "measurement_time_resolution": "15min",
        "measurement_expected_resolution": "15min",
        "measurement_timezone": TZ,
        "measurement_power_unit_mode": "kW",
        "measurement_resample_policy": "mean_to_hourly",
        "measurement_gap_fill_method": "none",
        "measurement_comparison_mode": "grid_import",
        "evaluation_calibration_metrics_enabled": False,
        "evaluation_peak_p1": 0.95,
        "evaluation_peak_p2": 0.99,
        "evaluation_max_exceedance_duration_h": 0.0,
        "evaluation_max_exceedance_energy_kWh": 0.0,
        "evaluation_robust_green_margin_fraction": 0.05,
        "last_load_df": None,
        "last_total_df": None,
        "last_generation_df": None,
        "last_measurement_bundle": None,
        "last_measurement_metadata": None,
        "last_validation_result": None,
        "last_measurement_filename": None,
        "bld_enable": False,
        "bld_sched_enable": False,
        "bld_t_heat_occ": 20.0,
        "bld_t_heat_unocc": 16.0,
        "bld_t_cool_occ": 24.0,
        "bld_t_cool_unocc": 27.0,
        "bld_cop_winter": 3.6,
        "bld_cop_spring": 4.1,
        "bld_cop_summer": 4.4,
        "bld_cop_autumn": 4.0,
        "bld_eer_winter": 3.3,
        "bld_eer_spring": 3.5,
        "bld_eer_summer": 3.1,
        "bld_eer_autumn": 3.4,
        "ref_heat_enabled": True,
        "ref_cop_winter": 3.6,
        "ref_cop_spring": 4.1,
        "ref_cop_summer": 4.4,
        "ref_cop_autumn": 4.0,
        "ref_eer_winter": 3.3,
        "ref_eer_spring": 3.5,
        "ref_eer_summer": 3.1,
        "ref_eer_autumn": 3.4,
        "bld_eta_wtw": 0.80,
        "bld_qv10": 0.40,
        "bld_g_value": 0.50,
        "bld_shading_factor": 0.80,
        "pe_enable": False,
        "pe_occ": 10.0,
        "pe_unocc": 3.0,
        "pr_enable": False,
        "pr_pp": 0.0,
        "pr_pi": 0.0,
        "mob_n_cars": 0,
        "mob_p_charger_max": 11.0,
        "mob_duty_cycle": 0.30,
        "mob_battery_capacity": 60.0,
        "mob_arrival_soc": 50.0,
        "mob_target_soc": 80.0,
        "mob_arrival_hour": 8,
        "mob_departure_hour": 17,
        "mob_cars_present": 100.0,
        "mob_charge_mode": "smart",
        "mob_site_cap": 0.0,
        "ov_enable": False,
        "ov_occ": 2.0,
        "ov_unocc": 0.5,
    }


def init_state() -> None:
    for k, v in app_state_defaults().items():
        st.session_state.setdefault(k, deepcopy(v))


init_state()


PROJECT_EXTRA_STATE_KEYS = (
    "bld_sched_days",
    "bld_sched_start",
    "bld_sched_end",
)

DYNAMIC_WIDGET_PREFIXES = (
    "pe_name_",
    "pe_days_",
    "pe_start_",
    "pe_end_",
    "pe_pocc_",
    "pe_punocc_",
    "ov_name_",
    "ov_days_",
    "ov_start_",
    "ov_end_",
    "ov_pocc_",
    "ov_punocc_",
    "proc_name_",
    "proc_days_",
    "proc_start_",
    "proc_end_",
    "proc_pp_",
    "proc_pi_",
)


def project_state_keys() -> list[str]:
    defaults = app_state_defaults()
    keys = [k for k in defaults if not k.startswith("last_")]
    keys.extend(k for k in PROJECT_EXTRA_STATE_KEYS if k in st.session_state)
    return keys


def build_project_payload() -> dict:
    defaults = app_state_defaults()
    state = {}
    for key in project_state_keys():
        if key in st.session_state:
            state[key] = deepcopy(st.session_state[key])
        elif key in defaults:
            state[key] = deepcopy(defaults[key])
    return {
        "schema_version": PROJECT_SCHEMA_VERSION,
        "app": "energiesysteem",
        "state": state,
    }


def project_payload_bytes() -> bytes:
    payload = build_project_payload()
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")


def clear_result_state() -> None:
    defaults = app_state_defaults()
    for key, value in defaults.items():
        if key.startswith("last_"):
            st.session_state[key] = deepcopy(value)


def clear_dynamic_widget_state() -> None:
    for key in list(st.session_state.keys()):
        if key in PROJECT_EXTRA_STATE_KEYS or any(key.startswith(prefix) for prefix in DYNAMIC_WIDGET_PREFIXES):
            st.session_state.pop(key, None)


def closest_pv_azimuth(value) -> float:
    if str(value) == PV_EAST_WEST_OPTION:
        return PV_EAST_WEST_OPTION
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return 180.0
    raw = raw % 360.0
    return min(PV_NUMERIC_AZIMUTH_OPTIONS, key=lambda x: abs(((raw - x + 180.0) % 360.0) - 180.0))


def normalize_input_constraints() -> list[str]:
    corrections: list[str] = []

    pv_before = st.session_state.get("pv_azimuth", 180.0)
    pv_after = closest_pv_azimuth(pv_before)
    if pv_after == PV_EAST_WEST_OPTION:
        st.session_state["pv_azimuth"] = PV_EAST_WEST_OPTION
    elif float(pv_after) != float(pv_before):
        st.session_state["pv_azimuth"] = pv_after
        corrections.append("Richting zonnepanelen is gekoppeld aan de dichtstbijzijnde windrichting.")

    heat_occ = float(st.session_state.get("bld_t_heat_occ", 20.0))
    heat_unocc = float(st.session_state.get("bld_t_heat_unocc", 16.0))
    cool_occ = float(st.session_state.get("bld_t_cool_occ", 24.0))
    cool_unocc = float(st.session_state.get("bld_t_cool_unocc", 27.0))

    if heat_unocc > heat_occ:
        st.session_state["bld_t_heat_unocc"] = heat_occ
        heat_unocc = heat_occ
        corrections.append("Verwarmingstemperatuur buiten gebruik is verlaagd tot maximaal de gebruikstemperatuur.")

    if cool_occ <= heat_occ:
        cool_occ = heat_occ + 0.5
        st.session_state["bld_t_cool_occ"] = cool_occ
        corrections.append("Koeltemperatuur tijdens gebruik is verhoogd zodat die boven de verwarmingstemperatuur ligt.")

    if cool_unocc < cool_occ:
        cool_unocc = cool_occ
        st.session_state["bld_t_cool_unocc"] = cool_unocc
        corrections.append("Koeltemperatuur buiten gebruik is verhoogd tot minimaal de gebruikskoeltemperatuur.")

    if cool_unocc <= heat_unocc:
        st.session_state["bld_t_cool_unocc"] = heat_unocc + 0.5
        corrections.append("Koeltemperatuur buiten gebruik is verhoogd zodat die boven de verwarmingstemperatuur buiten gebruik ligt.")

    if int(st.session_state.get("mob_departure_hour", 17)) <= int(st.session_state.get("mob_arrival_hour", 8)):
        st.session_state["mob_departure_hour"] = min(int(st.session_state.get("mob_arrival_hour", 8)) + 1, 24)
        corrections.append("Vertrektijd is aangepast zodat die na aankomsttijd ligt.")

    if float(st.session_state.get("mob_target_soc", 80.0)) < float(st.session_state.get("mob_arrival_soc", 50.0)):
        st.session_state["mob_target_soc"] = float(st.session_state.get("mob_arrival_soc", 50.0))
        corrections.append("Gewenste vertreklading is verhoogd tot minimaal de aankomstlading.")

    if float(st.session_state.get("dh_tariff", 0.0)) < 0.0:
        st.session_state["dh_tariff"] = 0.0
        corrections.append("Warmtenettarief is teruggezet naar minimaal 0.")

    return corrections


def reset_input_state() -> None:
    defaults = app_state_defaults()
    clear_dynamic_widget_state()
    for key, value in defaults.items():
        st.session_state[key] = deepcopy(value)
    st.session_state["_project_corrections"] = normalize_input_constraints()


def apply_project_payload(payload: dict) -> tuple[int, list[str]]:
    if not isinstance(payload, dict):
        raise ValueError("Projectbestand moet een JSON-object zijn.")

    raw_state = payload.get("state", payload)
    if not isinstance(raw_state, dict):
        raise ValueError("Projectbestand bevat geen geldige 'state'.")

    raw_state = dict(raw_state)
    legacy_reference_map = {
        "ref_cop_winter": "bld_cop_winter",
        "ref_cop_spring": "bld_cop_spring",
        "ref_cop_summer": "bld_cop_summer",
        "ref_cop_autumn": "bld_cop_autumn",
        "ref_eer_winter": "bld_eer_winter",
        "ref_eer_spring": "bld_eer_spring",
        "ref_eer_summer": "bld_eer_summer",
        "ref_eer_autumn": "bld_eer_autumn",
    }
    for new_key, old_key in legacy_reference_map.items():
        if new_key not in raw_state and old_key in raw_state:
            raw_state[new_key] = raw_state[old_key]

    defaults = app_state_defaults()
    allowed = set(defaults) | set(PROJECT_EXTRA_STATE_KEYS)
    ignored = sorted(k for k in raw_state if k not in allowed or k.startswith("last_"))

    clear_dynamic_widget_state()
    for key, value in raw_state.items():
        if key in allowed and not key.startswith("last_"):
            st.session_state[key] = deepcopy(value)
    clear_result_state()
    st.session_state["_project_corrections"] = normalize_input_constraints()
    return len(raw_state) - len(ignored), ignored


normalize_input_constraints()


def render_project_controls() -> None:
    with st.expander("Projectbestand", expanded=False):
        st.caption("Sla alleen invoerinstellingen op. Resultaten, uploads en meetdata worden niet in het projectbestand bewaard.")
        c1, c2, c3 = st.columns([1, 2, 1])
        with c1:
            st.download_button(
                "Download instellingen",
                project_payload_bytes(),
                file_name="energieproject_instellingen.json",
                mime="application/json",
                help="Wat: downloadt de huidige invoerinstellingen als projectbestand. In het model verandert dit niets. Effect: je kunt later met dezelfde instellingen verder werken.",
            )
        with c2:
            uploaded_project = st.file_uploader(
                "Upload projectbestand",
                type=["json"],
                key="project_file_upload",
                help="Wat: laad een eerder opgeslagen projectbestand. In het model worden invoerinstellingen teruggezet, maar resultaten en meetdata niet. Effect: de app gaat verder met de opgeslagen configuratie.",
            )
            if uploaded_project is not None and st.button("Laad instellingen", key="load_project_file", help="Past de geüploade invoerinstellingen toe en wist oude resultaten."):
                try:
                    payload = json.loads(uploaded_project.getvalue().decode("utf-8"))
                    loaded_count, ignored = apply_project_payload(payload)
                    st.success(f"Projectbestand geladen: {loaded_count} instellingen toegepast.")
                    if ignored:
                        st.caption(f"Genegeerde velden: {', '.join(ignored)}")
                    for correction in st.session_state.pop("_project_corrections", []):
                        st.warning(correction)
                except Exception as exc:
                    st.error(f"Projectbestand kon niet worden geladen: {exc}")
        with c3:
            if INVENTORY_PDF_PATH.exists():
                st.download_button(
                    "Download inventarisatieformulier",
                    INVENTORY_PDF_PATH.read_bytes(),
                    file_name="inventarisatie_energieplanner.pdf",
                    mime="application/pdf",
                    help="Wat: downloadt een invulformulier voor klantbezoeken. In het model verandert dit niets. Effect: consultants weten welke gegevens essentieel zijn voor een goede simulatie.",
                )
            else:
                st.caption("Inventarisatieformulier nog niet gegenereerd.")
        with c3:
            if st.button("Reset invoer", key="reset_project_inputs", help="Zet alle invoerinstellingen terug naar de standaardwaarden en wist oude resultaten."):
                reset_input_state()
                st.success("Invoerinstellingen teruggezet naar standaardwaarden.")
                for correction in st.session_state.pop("_project_corrections", []):
                    st.warning(correction)


render_project_controls()


@st.cache_data(show_spinner=False)
def load_weather(path: str) -> pd.DataFrame:
    return read_weather_excel(path, year=None, freq=None, tz=TZ)


try:
    WEATHER_DF = load_weather(str(WEATHER_PATH))
except Exception as exc:
    st.error(f"Weerdata kon niet worden geladen: {exc}")
    st.info("Controleer of 'Weatherdata 2008-2021.xlsx' in de hoofdmap van de repo staat en mee gedeployed is.")
    st.stop()
if not WEATHER_DF.index.is_unique:
    dupes = WEATHER_DF.index[WEATHER_DF.index.duplicated(keep=False)]
    st.error(f"Weather index bevat duplicates: {len(dupes)} rijen")
    st.stop()
st.caption(
    f"Weerdata geladen: {len(WEATHER_DF)} tijdstappen voor één simulatiejaar."
)
DT_HOURS = (WEATHER_DF.index[1] - WEATHER_DF.index[0]).total_seconds() / 3600.0 if len(WEATHER_DF.index) > 1 else 1.0


def series_dt_hours(df: pd.DataFrame | None) -> float:
    if df is None or not isinstance(df.index, pd.DatetimeIndex) or len(df.index) < 2:
        return DT_HOURS
    return float((df.index[1] - df.index[0]).total_seconds() / 3600.0)


def safe_contract_value(raw_value) -> float | None:
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    return None if value <= 0 else value


def consultant_summary(df: pd.DataFrame, grid_cap_kW: float | None) -> dict[str, str]:
    grid_eval = df.attrs.get("grid_evaluation") or {}
    kpis = df.attrs.get("kpis") or {}
    peak_ratio = grid_eval.get("peak_ratio_to_contract")
    p99_ratio = grid_eval.get("p99_ratio_to_contract")
    stoplight = str(grid_eval.get("stoplight", "unknown")).capitalize()
    unserved_heat = float(kpis.get("annual_heat_unserved_kWhth", 0.0) or 0.0)
    annual_gas = float(kpis.get("annual_gas_input_kWh", 0.0) or 0.0)
    return {
        "Consultant summary": stoplight,
        "Peak netimport vs contract": "-" if peak_ratio is None else f"{_fmt_nl_number(peak_ratio, 2)}x",
        "P99 netimport vs contract": "-" if p99_ratio is None else f"{_fmt_nl_number(p99_ratio, 2)}x",
        "Exceedance duration": "-" if grid_eval.get("contract_exceedance_hours") is None else _fmt_kpi(grid_eval["contract_exceedance_hours"], "h", 1),
        "Peak netimport": _fmt_kpi(float(grid_eval.get("peak_grid_import_kW", 0.0) or 0.0), "kW", 1),
        "Grid contract": "-" if grid_cap_kW is None else _fmt_kpi(grid_cap_kW, "kW", 1),
        "Annual grid import": _fmt_kpi(float(kpis.get("annual_grid_import_kWh", 0.0) or 0.0), "kWh", 0),
        "Annual grid export": _fmt_kpi(float(kpis.get("annual_grid_export_kWh", 0.0) or 0.0), "kWh", 0),
        "Annual gas input": _fmt_kpi(annual_gas, "kWh", 0),
        "Annual unmet heat": _fmt_kpi(unserved_heat, "kWhth", 0),
    }


def current_shape_factor() -> float:
    mapped = float(SHAPE_FACTOR_BY_SHAPE[BuildingShape(st.session_state["def_shape"])])
    return float(st.session_state["def_shape_manual"]) if st.session_state["def_manual_shape"] else mapped


def schedule_editor(
    prefix: str,
    default_days=("Mon", "Tue", "Wed", "Thu", "Fri"),
    default_start=8,
    default_end=18,
) -> WeeklySchedule:
    days = st.multiselect(
        label_for("schedule_days"),
        DAY_LABELS,
        default=list(default_days),
        key=f"{prefix}_days",
        format_func=lambda d: DAY_DISPLAY.get(d, d),
        help=help_for("schedule_days"),
    )
    c1, c2 = st.columns(2)
    with c1:
        start = st.number_input(label_for("schedule_start"), 0, 23, int(default_start), 1, key=f"{prefix}_start", help=help_for("schedule_start"))
    with c2:
        end = st.number_input(label_for("schedule_end"), 1, 24, int(default_end), 1, key=f"{prefix}_end", help=help_for("schedule_end"))
    return WeeklySchedule(
        days_active=tuple(DAY_TO_INT[d] for d in days) if days else (0, 1, 2, 3, 4),
        start_hour=int(start),
        end_hour=int(end),
    )


def subload_payload(list_key: str, mode: str):
    out = []
    for sl in st.session_state[list_key]:
        payload = {
            "name": sl["name"],
            "schedule": WeeklySchedule(
                days_active=tuple(DAY_TO_INT[d] for d in sl["days"]) if sl["days"] else (0, 1, 2, 3, 4),
                start_hour=int(sl["start"]),
                end_hour=int(sl["end"]),
            ),
        }
        if mode == "occ":
            payload["p_occ_W_per_m2"] = float(sl["p_occ"])
            payload["p_unocc_W_per_m2"] = float(sl["p_unocc"])
        else:
            payload["p_process_kW"] = float(sl["p_process"])
            payload["p_idle_kW"] = float(sl["p_idle"])
        out.append(payload)
    return out or None


def edit_occ_subloads(list_key: str, prefix: str, default_occ: float, default_unocc: float):
    if st.button(label_for("subload_add"), key=f"{prefix}_add", help="Wat: voegt een aparte verbruiksgroep toe. In het model wordt deze als extra profiel opgeteld. Effect: dit maakt het totale verbruik specifieker en meestal hoger."):
        st.session_state[list_key].append({
            "name": f"{prefix.capitalize()} {len(st.session_state[list_key]) + 1}",
            "days": ("Mon", "Tue", "Wed", "Thu", "Fri"),
            "start": 8,
            "end": 18,
            "p_occ": default_occ,
            "p_unocc": default_unocc,
        })
    for i, sl in enumerate(list(st.session_state[list_key])):
        with st.expander(sl["name"], expanded=False):
            sl["name"] = st.text_input(label_for("subload_name"), value=sl["name"], key=f"{prefix}_name_{i}", help=help_for("subload_name"))
            if st.button(label_for("subload_remove"), key=f"{prefix}_rm_{i}"):
                st.session_state[list_key].pop(i)
                st.rerun()
            sl["days"] = tuple(st.multiselect(
                label_for("schedule_days"),
                DAY_LABELS,
                default=list(sl["days"]),
                key=f"{prefix}_days_{i}",
                format_func=lambda d: DAY_DISPLAY.get(d, d),
                help=help_for("schedule_days"),
            ))
            c1, c2 = st.columns(2)
            with c1:
                sl["start"] = st.number_input(label_for("schedule_start"), 0, 23, int(sl["start"]), 1, key=f"{prefix}_start_{i}", help=help_for("schedule_start"))
            with c2:
                sl["end"] = st.number_input(label_for("schedule_end"), 1, 24, int(sl["end"]), 1, key=f"{prefix}_end_{i}", help=help_for("schedule_end"))
            c3, c4 = st.columns(2)
            with c3:
                sl["p_occ"] = st.number_input(label_for("subload_p_occ"), value=float(sl["p_occ"]), step=0.2, key=f"{prefix}_pocc_{i}", help=help_for("subload_p_occ"))
            with c4:
                sl["p_unocc"] = st.number_input(label_for("subload_p_unocc"), value=float(sl["p_unocc"]), step=0.2, key=f"{prefix}_punocc_{i}", help=help_for("subload_p_unocc"))
            st.session_state[list_key][i] = sl


def edit_process_subloads():
    if st.button(label_for("process_add"), key="proc_add", help="Wat: voegt een apart proces toe. In het model wordt dit als extra procesprofiel opgeteld. Effect: dit maakt procesverbruik specifieker en meestal hoger."):
        st.session_state["pprocess_subloads"].append({
            "name": f"Process {len(st.session_state['pprocess_subloads']) + 1}",
            "days": ("Mon", "Tue", "Wed", "Thu", "Fri"),
            "start": 9,
            "end": 17,
            "p_process": 10.0,
            "p_idle": 0.0,
        })
    for i, sl in enumerate(list(st.session_state["pprocess_subloads"])):
        with st.expander(sl["name"], expanded=False):
            sl["name"] = st.text_input(label_for("subload_name"), value=sl["name"], key=f"proc_name_{i}", help=help_for("subload_name"))
            if st.button(label_for("subload_remove"), key=f"proc_rm_{i}"):
                st.session_state["pprocess_subloads"].pop(i)
                st.rerun()
            sl["days"] = tuple(st.multiselect(
                label_for("schedule_days"),
                DAY_LABELS,
                default=list(sl["days"]),
                key=f"proc_days_{i}",
                format_func=lambda d: DAY_DISPLAY.get(d, d),
                help=help_for("schedule_days"),
            ))
            c1, c2 = st.columns(2)
            with c1:
                sl["start"] = st.number_input(label_for("schedule_start"), 0, 23, int(sl["start"]), 1, key=f"proc_start_{i}", help=help_for("schedule_start"))
            with c2:
                sl["end"] = st.number_input(label_for("schedule_end"), 1, 24, int(sl["end"]), 1, key=f"proc_end_{i}", help=help_for("schedule_end"))
            c3, c4 = st.columns(2)
            with c3:
                sl["p_process"] = st.number_input(label_for("proc_p_process"), value=float(sl["p_process"]), step=1.0, key=f"proc_pp_{i}", help=help_for("proc_p_process"))
            with c4:
                sl["p_idle"] = st.number_input(label_for("proc_p_idle"), value=float(sl["p_idle"]), step=1.0, key=f"proc_pi_{i}", help=help_for("proc_p_idle"))
            st.session_state["pprocess_subloads"][i] = sl


def first_week(df: pd.DataFrame) -> pd.DataFrame:
    start = df.index.min()
    return df.loc[(df.index >= start) & (df.index < start + pd.Timedelta(days=7))]


COLUMN_LABELS = {
    "P_heat_kW": "Referentie elektrische verwarming",
    "P_heat_ref_el_kW": "Referentie elektrische verwarming",
    "P_cool_kW": "Elektrische koeling",
    "P_cool_el_kW": "Elektrische koeling",
    "Q_heat_kWth": "Warmtevraag",
    "Q_cool_kWth": "Koelvraag",
    "P_elektro_kW": "Elektrisch verbruik",
    "P_process_kW": "Processen",
    "P_mobility_kW": "Mobiliteit laden",
    "P_overig_kW": "Overig verbruik",
    "P_base_without_mobility_kW": "Basislast zonder mobiliteit",
    "P_load_total_kW": "Totaal verbruik",
    "P_pv_kW": "Zonnepanelen",
    "P_pv_available_kW": "Beschikbare PV",
    "P_pv_used_kW": "Benutte PV",
    "P_pv_curtailed_kW": "Afgetopte PV",
    "P_pv_east_kW": "PV oost",
    "P_pv_west_kW": "PV west",
    "P_wkk_el_kW": "WKK elektrisch",
    "P_wkk_th_kW": "WKK warmte",
    "Q_wkk_used_kWth": "Benutte WKK-warmte",
    "P_generation_total_kW": "Totale opwek",
    "P_battery_charge_kW": "Batterij laden",
    "P_battery_discharge_kW": "Batterij ontladen",
    "P_grid_import_kW": "Netimport",
    "P_grid_export_kW": "Teruglevering",
    "P_electric_load_kW": "Elektrisch verbruik gemeten",
    "F_gas_kW": "Gasvermogen",
    "F_total_fuel_kW": "Brandstofinput",
    "F_total_gas_kW": "Gasinput",
    "F_wkk_fuel_kW": "WKK brandstof",
    "F_wkk_gas_kW": "WKK gas",
    "F_boiler_fuel_kW": "Ketel brandstof",
    "F_boiler_gas_kW": "Ketel gas",
    "P_grid_contract_excess_kW": "Boven contract",
    "battery_soc_pct": "Vullingsgraad batterij",
    "Q_heat_demand_kWth": "Warmtevraag",
    "Q_hp_th_kWth": "Warmtepompwarmte",
    "Q_wkk_used_kWth": "WKK-warmte",
    "Q_boiler_th_kWth": "Ketelwarmte",
    "Q_dh_th_kWth": "Warmtenet",
    "Q_heat_from_reference_kWth": "Referentieverwarming",
    "Q_thermal_storage_charge_kWth": "Warmteopslag laden",
    "Q_thermal_storage_discharge_kWth": "Warmteopslag ontladen",
    "Q_heat_unserved_final_kWth": "Ongedekte warmte",
    "P_hp_el_kW": "Warmtepomp elektriciteit",
}

PLOT_EXPLANATIONS = {
    "building": "Deze grafiek toont de thermische warmtevraag en koelvraag van het gebouw in de getoonde periode. De y-as is kWth: hogere pieken betekenen dat warmte- of koelinstallaties meer capaciteit moeten leveren.",
    "electric": "Deze grafiek toont het elektrische basisverbruik in de getoonde periode. De y-as is vermogen in kW. Een hoge basislast verhoogt netimport en beperkt ruimte voor slim laden.",
    "process": "Deze grafiek toont procesverbruik in de getoonde periode. Pieken geven momenten waarop processen veel elektrisch vermogen vragen.",
    "mobility": "Deze grafiek toont het laadvermogen voor elektrische auto's. Bij slim laden blijft laden binnen de beschikbare contractruimte; een tekort betekent dat de gewenste vertreklading niet volledig gehaald wordt.",
    "other": "Deze grafiek toont overige elektrische lasten in de getoonde periode. Dit is restverbruik dat meetelt in de totale basislast.",
    "load_total": "Deze grafiek combineert totaal elektrisch verbruik, elektrische koeling en eventuele referentie-elektrische verwarming. Gebruik dit om te zien welke elektrische componenten pieken veroorzaken.",
    "pv": "Deze grafiek toont de PV-opbrengst in kW. Richting, helling en vermogen bepalen wanneer en hoeveel zonnestroom beschikbaar is.",
    "wkk": "Deze grafiek toont elektrische en thermische WKK-productie. De regeling bepaalt wanneer de WKK draait en of die vooral stroom of warmte levert.",
    "generation": "Deze grafiek toont lokale opwek, opslagstromen en netimport. Zo zie je of opwek samenvalt met de energievraag.",
    "grid_week": "Deze grafiek toont de zwaarste netweek. De y-as is vermogen in kW; de contractlijn laat zien wanneer netcapaciteit krap wordt.",
    "duration": "Deze duurcurve sorteert netimport van hoog naar laag. Links staan de hoogste pieken; hoe breder de curve boven contract ligt, hoe structureler het knelpunt.",
    "heat_balance": "Deze grafiek toont hoe warmtevraag wordt ingevuld door warmtepomp, WKK, ketel, warmtenet en opslag. Ongedekte warmte wijst op onvoldoende warmtecapaciteit.",
    "gas_week": "Deze grafiek toont de week met de hoogste gas- of brandstofvraag. De y-as is vermogen in kW; pieken wijzen op momenten waarop gasloos maken extra warmtecapaciteit, opslag of elektrische ruimte vraagt.",
    "battery_soc": "Deze grafiek toont de vullingsgraad van de batterij. Een vaak lege batterij kan pieken niet verlagen; een vaak volle batterij kan overschot niet opnemen.",
    "monthly_energy": "Deze grafiek toont maandtotalen. Hiermee zie je seizoenseffecten duidelijker dan in losse weekgrafieken, bijvoorbeeld winterse warmtevraag of zomerse PV-opwek.",
    "load_match": "Deze grafiek toont hoe lokale opwek, verbruik, netimport en teruglevering zich tot elkaar verhouden. Veel netimport wijst op tekort aan lokale opwek op dat moment; veel teruglevering wijst op overschot dat mogelijk met opslag of sturing benut kan worden.",
    "validation": "Deze grafiek vergelijkt simulatie met meetdata. Grote verschillen wijzen op ontbrekende aannames, verkeerde meeteenheid of een modelinstelling die moet worden bijgesteld.",
}


def render_plot_explanation(key: str, context: str | None = None) -> None:
    text = PLOT_EXPLANATIONS.get(key)
    if not text:
        return
    with st.expander("Wat zie ik?", expanded=False):
        st.write(text)
        if context:
            st.caption(context)


def render_timeseries_plot(df: pd.DataFrame, cols: list[str], title: str, *, y_title: str = "Vermogen [kW]", explanation_key: str | None = None, context: str | None = None) -> None:
    available = [c for c in cols if c in df.columns]
    if not available:
        return
    plot_df = first_week(df)[available].reset_index().rename(columns={"index": "timestamp"})
    time_col = plot_df.columns[0]
    long_df = plot_df.melt(id_vars=time_col, var_name="series", value_name="value")
    long_df["series_label"] = long_df["series"].map(lambda c: COLUMN_LABELS.get(c, c))
    long_df["waarde"] = long_df["value"].map(lambda v: _fmt_kpi(v, y_title.split("[")[-1].rstrip("]") if "[" in y_title else "", 2))
    st.markdown(f"**{title}**")
    chart = (
        alt.Chart(long_df)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X(f"{time_col}:T", title="Tijd"),
            y=alt.Y("value:Q", title=y_title),
            color=alt.Color("series_label:N", title="Reeks"),
            tooltip=[f"{time_col}:T", "series_label:N", alt.Tooltip("waarde:N", title=y_title)],
        )
        .interactive()
    )
    st.altair_chart(chart, width='stretch')
    render_plot_explanation(explanation_key or "load_total", context)


def preview_week_chart(df: pd.DataFrame, cols: list[str], title: str, explanation_key: str = "load_total", context: str | None = None):
    render_timeseries_plot(df, cols, title, explanation_key=explanation_key, context=context)


def _fmt_nl_number(value, decimals: int = 0) -> str:
    if value is None:
        return "-"
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if pd.isna(value_f):
        return "-"
    if decimals == 0:
        text = f"{value_f:,.0f}"
    else:
        text = f"{value_f:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_kpi(value, unit: str = "", decimals: int = 0) -> str:
    text = _fmt_nl_number(value, decimals)
    if text == "-":
        return text
    return f"{text} {unit}".strip()


def _format_nl_dataframe(df: pd.DataFrame, decimals: int = 2) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_numeric_dtype(out[col]):
            out[col] = out[col].map(lambda v: _fmt_nl_number(v, decimals))
    return out


KPI_HELP_TEXTS = {
    "Jaarverbruik elektriciteit": "Wat: totale elektrische energie over het jaar. In het model: som van alle elektrische vermogens maal de tijdstap. Effect: hogere elektrische lasten vragen meer netcapaciteit of lokale opwek.",
    "Elektriciteitsintensiteit": "Wat: jaarverbruik elektriciteit gedeeld door vloeroppervlak. In het model: kWh per m². Effect: handig om gebouwen eerlijker te vergelijken; een hoge waarde wijst op intensief gebruik of inefficiëntie.",
    "Piek totaal verbruik": "Wat: hoogste momentane elektrische vraag van alle gebruikers samen. In het model: maximum van de totale load. Effect: bepaalt mede of de aansluiting groot genoeg is.",
    "Jaarlijkse warmtevraag": "Wat: totale nuttige warmte die het gebouw nodig heeft. In het model: som van de thermische warmtevraag. Effect: bepaalt hoeveel warmtepomp-, ketel-, WKK- of warmtenetcapaciteit nodig is.",
    "Warmtevraag": "Wat: nuttige warmte die het gebouw vraagt. In het model: thermische vraag vóór omzetting naar elektriciteit of brandstof. Effect: hogere warmtevraag maakt gasloosheid en netruimte lastiger.",
    "Piek warmtevraag": "Wat: hoogste thermische warmtevraag. In het model: maximum van de warmtevraag in kWth. Effect: bepaalt de benodigde capaciteit van warmtebronnen.",
    "Jaarlijkse koelvraag": "Wat: totale nuttige koeling die het gebouw nodig heeft. In het model: thermische koelvraag, daarna omgerekend naar elektriciteit via EER. Effect: hogere koelvraag verhoogt vooral zomerse elektriciteitspieken.",
    "Piek koelvraag": "Wat: hoogste thermische koelvraag. In het model: maximum van de koelvraag in kWth. Effect: bepaalt de benodigde koelcapaciteit en elektrische piekbelasting.",
    "Jaaropwek PV": "Wat: totale jaaropbrengst van zonnepanelen. In het model: PV-vermogen maal tijdstap, afhankelijk van vermogen, richting, helling en weer. Effect: meer PV verlaagt netimport maar kan ook teruglevering verhogen.",
    "Jaaropwek WKK": "Wat: totale elektrische jaaropwek van de WKK. In het model: dispatch volgens de gekozen WKK-regeling. Effect: kan netimport verlagen, maar gebruikt brandstof en levert ook warmte.",
    "Piekvermogen PV": "Wat: hoogste berekende PV-vermogen. In het model: maximum van de PV-tijdreeks. Effect: bepaalt hoeveel lokale opwek op zonnige momenten beschikbaar is.",
    "Piek WKK elektrisch": "Wat: hoogste elektrische WKK-output. In het model: begrensd door WKK-vermogen en regeling. Effect: kan pieken verlagen, maar beïnvloedt brandstofgebruik.",
    "Piek WKK warmte": "Wat: hoogste thermische WKK-output. In het model: gekoppeld aan elektrische WKK-output en thermisch rendement. Effect: helpt warmtevraag dekken, vooral als de regeling warmtevraag volgt.",
    "Netimport": "Wat: vermogen of energie uit het elektriciteitsnet. In het model: resterende vraag na lokale opwek en opslag. Effect: hoge waarden bepalen netcapaciteitsknelpunten.",
    "Jaarlijkse netimport": "Wat: totale elektriciteit uit het net over het jaar. In het model: som van positieve netafname. Effect: laat zien hoeveel energie nog extern nodig is.",
    "Piek netimport": "Wat: hoogste momentane afname uit het net. In het model: maximum na opwek en batterij. Effect: belangrijkste indicator voor contractvermogen.",
    "Teruglevering": "Wat: elektriciteit die niet lokaal wordt gebruikt en terug het net op gaat. In het model: overschot na vraag en opslag. Effect: veel teruglevering kan wijzen op batterij- of sturingspotentieel.",
    "Ongedekte warmte": "Wat: warmtevraag die niet door installaties wordt geleverd. In het model: resterende warmte na warmtepomp, WKK, ketel, warmtenet, opslag en referentie. Effect: moet nul of acceptabel laag zijn voor een haalbaar scenario.",
    "Gas-/brandstofinput": "Wat: totale brandstofenergie voor ketel en WKK. In het model: som van brandstofstromen. Effect: voor gasloosheid moet fossiele gasinput naar nul.",
    "Zelfvoorziening": "Wat: aandeel elektriciteitsvraag dat niet via netimport hoeft te komen. In het model: 1 min netimport gedeeld door totale elektrische vraag. Effect: hoger betekent betere lokale dekking, maar zegt niet alles over pieken.",
    "Mobiliteit laden": "Wat: energie voor elektrische auto's. In het model: laadprofiel op basis van aantal auto's, batterij, SoC en laadmodus. Effect: kan pieken veroorzaken of via slim laden worden begrensd.",
    "Warmtepomp elektriciteit": "Wat: elektriciteit die de warmtepomp gebruikt. In het model: geleverde warmte gedeeld door COP. Effect: gasloos verwarmen verlaagt brandstofgebruik maar verhoogt elektrische vraag.",
    "Referentieverwarming elektriciteit": "Wat: fallback-elektriciteit voor resterende warmtevraag. In het model: resterende warmte gedeeld door referentie-COP. Effect: voorkomt ongedekte warmte, maar kan netpieken verhogen.",
    "Elektrische koeling": "Wat: elektriciteit voor koeling. In het model: koelvraag gedeeld door EER. Effect: beïnvloedt vooral warme perioden en zomerse pieken.",
    "Benuttingsgraad": "Wat: gemiddelde netimport gedeeld door piek netimport. In het model: maat voor hoe vlak of piekerig de netvraag is. Effect: lage waarde betekent dat korte pieken de aansluiting domineren.",
}


def render_kpi_help(label: str, explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    label_norm = str(label).strip()
    if label_norm in KPI_HELP_TEXTS:
        return KPI_HELP_TEXTS[label_norm]
    for key, text in KPI_HELP_TEXTS.items():
        if key.lower() in label_norm.lower():
            return text
    return None


def render_kpi_row(items: list[tuple], columns: int | None = None) -> None:
    if not items:
        return
    cols = st.columns(columns or min(len(items), 4))
    for col, item in zip(cols, items):
        label, value, unit, decimals = item[:4]
        help_text = render_kpi_help(label, item[4] if len(item) > 4 else None)
        col.metric(label, _fmt_kpi(value, unit, decimals), help=help_text)


def annual_sum(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns:
        return 0.0
    return float((df[column].fillna(0.0) * series_dt_hours(df)).sum())


def peak_value(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns or df.empty:
        return 0.0
    return float(df[column].fillna(0.0).max())


def intensity_per_m2(value: float, bvo_m2: float | None = None) -> float | None:
    area = float(bvo_m2 if bvo_m2 is not None else st.session_state.get("def_bvo", 0.0))
    if area <= 0:
        return None
    return float(value) / area


def render_input_default_kpis(cfg) -> None:
    render_kpi_row(
        [
            ("Elektrisch vermogen gebruik", float(cfg.pelektro.p_occ_W_per_m2), "W/m²", 1),
            ("Elektrisch vermogen rust", float(cfg.pelektro.p_unocc_W_per_m2), "W/m²", 1),
            ("Gebruiksoppervlak", float(cfg.building.bvo_m2), "m²", 0),
        ],
        columns=3,
    )


def render_load_component_kpis(df: pd.DataFrame, specs: list[tuple[str, str, str, int]]) -> None:
    items = []
    for label, column, unit, decimals in specs:
        if unit in {"kWh", "kWhth"}:
            value = annual_sum(df, column)
        elif unit in {"kWh/m²", "kWhth/m²"}:
            source_unit = "kWhth" if "kWhth" in unit else "kWh"
            source = annual_sum(df, column)
            value = intensity_per_m2(source)
            unit = source_unit + "/m²"
        else:
            value = peak_value(df, column)
        items.append((label, value, unit, decimals))
    render_kpi_row(items)


ELECTRIC_CONSUMPTION_CATEGORIES = [
    ("Elektrisch basisverbruik", "P_elektro_kW"),
    ("Processen", "P_process_kW"),
    ("Mobiliteit", "P_mobility_kW"),
    ("Koeling", "P_cool_el_kW"),
    ("Warmtepomp", "P_hp_el_kW"),
    ("Referentieverwarming", "P_heat_ref_el_kW"),
    ("Overig verbruik", "P_overig_kW"),
]

GENERATION_CATEGORIES = [
    ("Zonnepanelen", "P_pv_kW"),
    ("WKK elektrisch", "P_wkk_el_kW"),
]

ELECTRICITY_SUPPLY_CATEGORIES = [
    ("Zonnepanelen benut", "P_pv_used_kW"),
    ("WKK elektrisch", "P_wkk_el_kW"),
    ("Batterij ontladen", "P_battery_discharge_kW"),
    ("Netimport", "P_grid_import_kW"),
]

HEAT_SUPPLY_CATEGORIES = [
    ("Warmtepomp", "Q_hp_th_kWth"),
    ("WKK-warmte", "Q_wkk_used_kWth"),
    ("Ketel", "Q_boiler_th_kWth"),
    ("Warmtenet", "Q_dh_th_kWth"),
    ("Referentie", "Q_heat_from_reference_kWth"),
    ("Warmteopslag", "Q_thermal_storage_discharge_kWth"),
    ("Ongedekt", "Q_heat_unserved_final_kWth"),
]

STORAGE_CATEGORIES = [
    ("Batterij laden", "P_battery_charge_kW"),
    ("Batterij ontladen", "P_battery_discharge_kW"),
    ("Warmteopslag laden", "Q_thermal_storage_charge_kWth"),
    ("Warmteopslag ontladen", "Q_thermal_storage_discharge_kWth"),
]

SEASON_ORDER = ["Winter", "Lente", "Zomer", "Herfst"]
MONTH_ORDER = ["Jan", "Feb", "Mrt", "Apr", "Mei", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"]


def _positive_categories(df: pd.DataFrame, mapping: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out = []
    for label, column in mapping:
        if column in df.columns and float(df[column].fillna(0.0).clip(lower=0.0).sum()) > 1e-9:
            out.append((label, column))
    return out


def annual_energy_by_category(df: pd.DataFrame, mapping: list[tuple[str, str]]) -> pd.DataFrame:
    rows = []
    dt_h = series_dt_hours(df)
    for label, column in _positive_categories(df, mapping):
        rows.append({"categorie": label, "energie_kWh": float((df[column].clip(lower=0.0) * dt_h).sum())})
    return pd.DataFrame(rows)


def _season_label(month: int) -> str:
    if month in (12, 1, 2):
        return "Winter"
    if month in (3, 4, 5):
        return "Lente"
    if month in (6, 7, 8):
        return "Zomer"
    return "Herfst"


def seasonal_energy_by_category(df: pd.DataFrame, mapping: list[tuple[str, str]]) -> pd.DataFrame:
    rows = []
    dt_h = series_dt_hours(df)
    seasons = pd.Series([_season_label(int(m)) for m in df.index.month], index=df.index)
    for label, column in _positive_categories(df, mapping):
        energy = df[column].clip(lower=0.0) * dt_h
        grouped = energy.groupby(seasons).sum()
        for season in SEASON_ORDER:
            rows.append({"seizoen": season, "categorie": label, "energie_kWh": float(grouped.get(season, 0.0))})
    return pd.DataFrame(rows)


def monthly_energy_by_category(df: pd.DataFrame, mapping: list[tuple[str, str]]) -> pd.DataFrame:
    rows = []
    if df.empty:
        return pd.DataFrame(rows)
    dt_h = series_dt_hours(df)
    month_numbers = pd.Series(df.index.month, index=df.index)
    for label, column in _positive_categories(df, mapping):
        energy = df[column].clip(lower=0.0) * dt_h
        grouped = energy.groupby(month_numbers).sum()
        for month_number, month_label in enumerate(MONTH_ORDER, start=1):
            rows.append(
                {
                    "maand_nummer": month_number,
                    "maand": month_label,
                    "categorie": label,
                    "energie_kWh": float(grouped.get(month_number, 0.0)),
                }
            )
    return pd.DataFrame(rows)


def daily_energy_by_category(df: pd.DataFrame, mapping: list[tuple[str, str]]) -> pd.DataFrame:
    rows = []
    dt_h = series_dt_hours(df)
    for label, column in _positive_categories(df, mapping):
        energy = (df[column].clip(lower=0.0) * dt_h).resample("D").sum()
        for ts, value in energy.items():
            rows.append({"datum": ts, "categorie": label, "energie_kWh": float(value)})
    return pd.DataFrame(rows)


def timeseries_energy_by_category(df: pd.DataFrame, mapping: list[tuple[str, str]]) -> pd.DataFrame:
    rows = []
    for label, column in _positive_categories(df, mapping):
        series = df[column].clip(lower=0.0)
        for ts, value in series.items():
            rows.append({"timestamp": ts, "categorie": label, "vermogen_kW": float(value)})
    return pd.DataFrame(rows)


def render_donut_chart(title: str, data: pd.DataFrame, *, unit: str = "kWh") -> None:
    if data.empty or float(data["energie_kWh"].sum()) <= 0:
        st.info(f"Geen data beschikbaar voor {title.lower()}.")
        return
    data = data.copy()
    data["energie"] = data["energie_kWh"].map(lambda v: _fmt_kpi(v, unit, 0))
    st.markdown(f"**{title}**")
    chart = (
        alt.Chart(data)
        .mark_arc(innerRadius=65, outerRadius=120)
        .encode(
            theta=alt.Theta("energie_kWh:Q", title=f"Energie [{unit}]"),
            color=alt.Color("categorie:N", title="Categorie"),
            tooltip=[
                "categorie:N",
                alt.Tooltip("energie:N", title=f"Energie [{unit}]"),
            ],
        )
    )
    st.altair_chart(chart, width='stretch')


def render_stacked_bar_chart(title: str, data: pd.DataFrame, *, x_col: str = "seizoen", unit: str = "kWh") -> None:
    if data.empty:
        st.info(f"Geen data beschikbaar voor {title.lower()}.")
        return
    data = data.copy()
    data["energie"] = data["energie_kWh"].map(lambda v: _fmt_kpi(v, unit, 0))
    st.markdown(f"**{title}**")
    chart = (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X(f"{x_col}:N", title=x_col.capitalize(), sort=SEASON_ORDER if x_col == "seizoen" else None),
            y=alt.Y("energie_kWh:Q", stack=True, title=f"Energie [{unit}]"),
            color=alt.Color("categorie:N", title="Categorie"),
            tooltip=[
                f"{x_col}:N",
                "categorie:N",
                alt.Tooltip("energie:N", title=f"Energie [{unit}]"),
            ],
        )
        .interactive()
    )
    st.altair_chart(chart, width='stretch')


def render_monthly_stacked_bar_chart(title: str, data: pd.DataFrame, *, unit: str = "kWh") -> None:
    if data.empty:
        st.info(f"Geen data beschikbaar voor {title.lower()}.")
        return
    data = data.copy()
    data["energie"] = data["energie_kWh"].map(lambda v: _fmt_kpi(v, unit, 0))
    st.markdown(f"**{title}**")
    chart = (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X("maand:N", title="Maand", sort=MONTH_ORDER),
            y=alt.Y("energie_kWh:Q", stack=True, title=f"Energie [{unit}]"),
            color=alt.Color("categorie:N", title="Categorie"),
            tooltip=[
                alt.Tooltip("maand:N", title="Maand"),
                "categorie:N",
                alt.Tooltip("energie:N", title=f"Energie [{unit}]"),
            ],
        )
        .interactive()
    )
    st.altair_chart(chart, width='stretch')
    render_plot_explanation("monthly_energy")


def render_grouped_monthly_energy_chart(title: str, data: pd.DataFrame, *, unit: str = "kWh") -> None:
    if data.empty:
        st.info(f"Geen data beschikbaar voor {title.lower()}.")
        return
    data = data.copy()
    data["energie"] = data["energie_kWh"].map(lambda v: _fmt_kpi(v, unit, 0))
    st.markdown(f"**{title}**")
    chart = (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X("maand:N", title="Maand", sort=MONTH_ORDER),
            xOffset=alt.XOffset("categorie:N", title="Categorie"),
            y=alt.Y("energie_kWh:Q", title=f"Energie [{unit}]"),
            color=alt.Color("categorie:N", title="Categorie"),
            tooltip=[
                alt.Tooltip("maand:N", title="Maand"),
                "categorie:N",
                alt.Tooltip("energie:N", title=f"Energie [{unit}]"),
            ],
        )
        .interactive()
    )
    st.altair_chart(chart, width='stretch')
    render_plot_explanation("monthly_energy")


def render_stacked_area_chart(title: str, data: pd.DataFrame, *, unit: str = "kW") -> None:
    if data.empty:
        st.info(f"Geen data beschikbaar voor {title.lower()}.")
        return
    data = data.copy()
    data["vermogen"] = data["vermogen_kW"].map(lambda v: _fmt_kpi(v, unit, 1))
    st.markdown(f"**{title}**")
    chart = (
        alt.Chart(data)
        .mark_area(opacity=0.85)
        .encode(
            x=alt.X("timestamp:T", title="Tijd"),
            y=alt.Y("vermogen_kW:Q", stack=True, title=f"Vermogen [{unit}]"),
            color=alt.Color("categorie:N", title="Categorie"),
            tooltip=[
                "timestamp:T",
                "categorie:N",
                alt.Tooltip("vermogen:N", title=f"Vermogen [{unit}]"),
            ],
        )
        .interactive()
    )
    st.altair_chart(chart, width='stretch')


def render_daily_energy_chart(title: str, data: pd.DataFrame, *, unit: str = "kWh/dag") -> None:
    if data.empty:
        st.info(f"Geen data beschikbaar voor {title.lower()}.")
        return
    data = data.copy()
    data["energie"] = data["energie_kWh"].map(lambda v: _fmt_kpi(v, unit, 0))
    st.markdown(f"**{title}**")
    chart = (
        alt.Chart(data)
        .mark_line(strokeWidth=1.8)
        .encode(
            x=alt.X("datum:T", title="Datum"),
            y=alt.Y("energie_kWh:Q", title=f"Energie [{unit}]"),
            color=alt.Color("categorie:N", title="Categorie"),
            tooltip=[
                "datum:T",
                "categorie:N",
                alt.Tooltip("energie:N", title=f"Energie [{unit}]"),
            ],
        )
        .interactive()
    )
    st.altair_chart(chart, width='stretch')


def render_daily_stacked_area_chart(title: str, data: pd.DataFrame, *, unit: str = "kWh/dag") -> None:
    if data.empty:
        st.info(f"Geen data beschikbaar voor {title.lower()}.")
        return
    data = data.copy()
    data["energie"] = data["energie_kWh"].map(lambda v: _fmt_kpi(v, unit, 0))
    st.markdown(f"**{title}**")
    chart = (
        alt.Chart(data)
        .mark_area(opacity=0.85)
        .encode(
            x=alt.X("datum:T", title="Tijd"),
            y=alt.Y("energie_kWh:Q", stack=True, title=f"Energie [{unit}]"),
            color=alt.Color("categorie:N", title="Categorie"),
            tooltip=[
                "datum:T",
                "categorie:N",
                alt.Tooltip("energie:N", title=f"Energie [{unit}]"),
            ],
        )
        .interactive()
    )
    st.altair_chart(chart, width='stretch')


def render_peak_week_chart(
    df: pd.DataFrame,
    peak_column: str,
    cols: list[str],
    title: str,
    *,
    y_title: str = "Vermogen [kW]",
    explanation_key: str | None = None,
    context: str | None = None,
) -> None:
    if df.empty or peak_column not in df.columns:
        return
    week = df.loc[find_peak_week(df, peak_column)].copy()
    render_timeseries_plot(week, cols, title, y_title=y_title, explanation_key=explanation_key, context=context)


def find_highest_energy_week(df: pd.DataFrame, column: str, *, window_days: int = 7) -> pd.DatetimeIndex:
    if column not in df.columns:
        return pd.DatetimeIndex([])
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex) or len(idx) < 2:
        return idx
    dt = idx[1] - idx[0]
    window_len = max(int(window_days * pd.Timedelta(days=1) / dt), 1)
    values = df[column].fillna(0.0).clip(lower=0.0).to_numpy(dtype=float)
    best_i = 0
    best_sum = -1.0
    for i in range(0, max(len(values) - window_len + 1, 1)):
        total = float(values[i : i + window_len].sum())
        if total > best_sum:
            best_sum = total
            best_i = i
    return idx[best_i : best_i + window_len]


def render_peak_grid_week_interactive(df: pd.DataFrame, contract_kW: float | None) -> None:
    if df.empty or "P_grid_import_kW" not in df.columns:
        return
    week = df.loc[find_peak_week(df, "P_grid_import_kW")].copy()
    cols = [
        "P_grid_import_kW",
        "P_load_total_kW",
        "P_elektro_kW",
        "P_process_kW",
        "P_mobility_kW",
        "P_cool_el_kW",
        "P_hp_el_kW",
        "P_heat_ref_el_kW",
        "P_pv_kW",
        "P_pv_used_kW",
        "P_pv_curtailed_kW",
        "P_wkk_el_kW",
        "P_battery_discharge_kW",
    ]
    available = [c for c in cols if c in week.columns]
    plot_df = week[available].reset_index().rename(columns={"index": "timestamp"})
    focus_col = "P_grid_import_kW"
    focus_df = plot_df[["timestamp", focus_col]].rename(columns={focus_col: "vermogen_kW"})
    focus_df["serie"] = COLUMN_LABELS.get(focus_col, focus_col)
    context_cols = [c for c in available if c != focus_col]
    context_long = plot_df[["timestamp"] + context_cols].melt(id_vars="timestamp", var_name="serie", value_name="vermogen_kW")
    context_long["serie"] = context_long["serie"].map(lambda c: COLUMN_LABELS.get(c, c))
    context_long["vermogen"] = context_long["vermogen_kW"].map(lambda v: _fmt_kpi(v, "kW", 1))
    focus_df["vermogen"] = focus_df["vermogen_kW"].map(lambda v: _fmt_kpi(v, "kW", 1))

    context_layer = (
        alt.Chart(context_long)
        .mark_line(strokeWidth=1.4, opacity=0.62)
        .encode(
            x=alt.X("timestamp:T", title="Tijd"),
            y=alt.Y("vermogen_kW:Q", title="Vermogen [kW]"),
            color=alt.Color("serie:N", title="Reeks"),
            tooltip=["timestamp:T", "serie:N", alt.Tooltip("vermogen:N", title="Vermogen")],
        )
    )
    focus_layer = (
        alt.Chart(focus_df)
        .mark_line(strokeWidth=4.2, color="#0B5FFF")
        .encode(
            x=alt.X("timestamp:T", title="Tijd"),
            y=alt.Y("vermogen_kW:Q", title="Vermogen [kW]"),
            tooltip=["timestamp:T", "serie:N", alt.Tooltip("vermogen:N", title="Netimport")],
        )
    )
    layers = [context_layer, focus_layer]
    if contract_kW is not None:
        contract_df = pd.DataFrame({"timestamp": plot_df["timestamp"], "contract_kW": float(contract_kW)})
        layers.append(
            alt.Chart(contract_df)
            .mark_line(color="#D62728", strokeDash=[6, 4], strokeWidth=2.2)
            .encode(x="timestamp:T", y=alt.Y("contract_kW:Q", title="Vermogen [kW]"))
        )
    st.markdown("**Zwaarste netweek**")
    st.altair_chart(alt.layer(*layers).interactive(), width='stretch')
    render_plot_explanation("grid_week", f"Contractvermogen: {'niet ingesteld' if contract_kW is None else _fmt_kpi(contract_kW, 'kW', 1)}.")


def render_heat_week_interactive(df: pd.DataFrame) -> None:
    if df.empty or "Q_heat_demand_kWth" not in df.columns:
        return
    week = df.loc[find_peak_week(df, "Q_heat_demand_kWth")].copy()
    cols = [c for c in ["Q_heat_demand_kWth", "Q_hp_th_kWth", "Q_wkk_used_kWth", "Q_boiler_th_kWth", "Q_dh_th_kWth", "Q_heat_from_reference_kWth", "Q_thermal_storage_discharge_kWth", "Q_heat_unserved_final_kWth"] if c in week.columns]
    render_timeseries_plot(week, cols, "Zwaarste warmteweek", y_title="Warmtevermogen [kWth]", explanation_key="heat_balance")


def render_peak_gas_week_interactive(df: pd.DataFrame) -> None:
    st.markdown("**Zwaarste gasweek**")
    gas_col = "F_total_gas_kW" if "F_total_gas_kW" in df.columns and float(df["F_total_gas_kW"].fillna(0.0).sum()) > 1e-9 else "F_total_fuel_kW"
    if df.empty or gas_col not in df.columns or float(df[gas_col].fillna(0.0).sum()) <= 1e-9:
        st.info("Geen gas- of brandstofvraag aanwezig in deze simulatie.")
        return
    cols = [c for c in [gas_col, "F_wkk_gas_kW", "F_boiler_gas_kW", "F_wkk_fuel_kW", "F_boiler_fuel_kW"] if c in df.columns]
    week = df.loc[find_highest_energy_week(df, gas_col)].copy()
    render_timeseries_plot(week, cols, "Gas-/brandstofprofiel", y_title="Gas-/brandstofvermogen [kW]", explanation_key="gas_week")


def render_load_match_balance_charts(df: pd.DataFrame) -> None:
    balance_mapping = [
        ("Totaal verbruik", "P_load_total_kW"),
        ("Lokale opwek", "P_generation_total_kW"),
        ("Netimport", "P_grid_import_kW"),
        ("Teruglevering", "P_grid_export_kW"),
    ]
    render_grouped_monthly_energy_chart("Maandelijkse energiebalans", monthly_energy_by_category(df, balance_mapping))

    flow_data = daily_energy_by_category(
        df,
        [
            ("Netimport", "P_grid_import_kW"),
            ("Teruglevering", "P_grid_export_kW"),
        ],
    )
    load_data = daily_energy_by_category(df, [("Totaal verbruik", "P_load_total_kW")])
    if flow_data.empty and load_data.empty:
        st.info("Geen data beschikbaar voor dagelijkse netafhankelijkheid.")
        return

    st.markdown("**Dagelijkse netafhankelijkheid**")
    layers = []
    if not flow_data.empty:
        flow_data = flow_data.copy()
        flow_data["energie"] = flow_data["energie_kWh"].map(lambda v: _fmt_kpi(v, "kWh/dag", 0))
        layers.append(
            alt.Chart(flow_data)
            .mark_bar(opacity=0.75)
            .encode(
                x=alt.X("datum:T", title="Datum"),
                y=alt.Y("energie_kWh:Q", title="Energie [kWh/dag]"),
                color=alt.Color("categorie:N", title="Categorie"),
                tooltip=[
                    "datum:T",
                    "categorie:N",
                    alt.Tooltip("energie:N", title="Energie [kWh/dag]"),
                ],
            )
        )
    if not load_data.empty:
        load_line = load_data.copy()
        load_line["categorie"] = "Totaal verbruik"
        load_line["energie"] = load_line["energie_kWh"].map(lambda v: _fmt_kpi(v, "kWh/dag", 0))
        layers.append(
            alt.Chart(load_line)
            .mark_line(strokeWidth=2.4, color="#3D3D3D")
            .encode(
                x=alt.X("datum:T", title="Datum"),
                y=alt.Y("energie_kWh:Q", title="Energie [kWh/dag]"),
                tooltip=[
                    "datum:T",
                    "categorie:N",
                    alt.Tooltip("energie:N", title="Totaal verbruik [kWh/dag]"),
                ],
            )
        )
    st.altair_chart(alt.layer(*layers).interactive(), width='stretch')
    render_plot_explanation("load_match")


def render_load_calculation_results(df: pd.DataFrame) -> None:
    st.markdown("### Verbruiksoverzicht")
    render_kpi_row(
        [
            ("Jaarverbruik elektriciteit", annual_sum(df, "P_load_total_kW"), "kWh", 0),
            ("Elektriciteitsintensiteit", intensity_per_m2(annual_sum(df, "P_load_total_kW")), "kWh/m²", 1),
            ("Piek totaal verbruik", peak_value(df, "P_load_total_kW"), "kW", 1),
            ("Mobiliteit laden", annual_sum(df, "P_mobility_kW"), "kWh", 0),
        ]
    )
    render_kpi_row(
        [
            ("Jaarlijkse warmtevraag", annual_sum(df, "Q_heat_kWth"), "kWhth", 0),
            ("Warmte-intensiteit", intensity_per_m2(annual_sum(df, "Q_heat_kWth")), "kWhth/m²", 1),
            ("Jaarlijkse koelvraag", annual_sum(df, "Q_cool_kWth"), "kWhth", 0),
            ("Piek koelvraag", peak_value(df, "Q_cool_kWth"), "kWth", 1),
        ]
    )

    st.markdown("### Piekweken")
    render_peak_week_chart(
        df,
        "Q_heat_kWth",
        ["Q_heat_kWth", "Q_hp_th_kWth", "Q_heat_from_reference_kWth", "Q_boiler_th_kWth", "Q_dh_th_kWth"],
        "Week met hoogste warmtevraag",
        y_title="Warmtevermogen [kWth]",
        explanation_key="heat_balance",
    )
    render_peak_week_chart(
        df,
        "Q_cool_kWth",
        ["Q_cool_kWth", "P_cool_el_kW"],
        "Week met hoogste koelvraag",
        y_title="Koelvraag [kWth] / elektriciteit [kW]",
        explanation_key="building",
        context="Koelvraag is thermisch; elektrische koeling wordt via de referentie-EER omgerekend.",
    )
    render_peak_week_chart(
        df,
        "P_load_total_kW",
        ["P_load_total_kW", "P_elektro_kW", "P_process_kW", "P_mobility_kW", "P_cool_el_kW", "P_hp_el_kW", "P_heat_ref_el_kW", "P_overig_kW"],
        "Week met hoogste elektriciteitsvraag",
        y_title="Vermogen [kW]",
        explanation_key="load_total",
        context="Deze grafiek toont de elektrische impact van verwarming via warmtepomp of referentieverwarming, plus koeling via EER.",
    )

    st.markdown("### Jaar- En Maandprofiel")
    render_daily_stacked_area_chart(
        "Gebruikte energie per dag",
        daily_energy_by_category(df, ELECTRIC_CONSUMPTION_CATEGORIES),
    )
    c_load_mix1, c_load_mix2 = st.columns(2)
    with c_load_mix1:
        render_donut_chart("Jaarmix verbruik", annual_energy_by_category(df, ELECTRIC_CONSUMPTION_CATEGORIES))
    with c_load_mix2:
        render_monthly_stacked_bar_chart("Maandverbruik", monthly_energy_by_category(df, ELECTRIC_CONSUMPTION_CATEGORIES))

    heat_electric_mapping = [
        ("Warmtepomp elektriciteit", "P_hp_el_kW"),
        ("Referentieverwarming elektriciteit", "P_heat_ref_el_kW"),
        ("Elektrische koeling", "P_cool_el_kW"),
    ]
    heat_electric = monthly_energy_by_category(df, heat_electric_mapping)
    if not heat_electric.empty:
        render_monthly_stacked_bar_chart("Elektrische impact van warmte en koeling", heat_electric)

    with st.expander("Resultaatdata bekijken", expanded=False):
        st.dataframe(_format_nl_dataframe(df.head(200)))


def render_generation_calculation_results(df: pd.DataFrame) -> None:
    st.markdown("### Opwekoverzicht")
    render_kpi_row(
        [
            ("Piek totale opwek", peak_value(df, "P_generation_total_kW"), "kW", 1),
            ("Jaaropwek PV", annual_sum(df, "P_pv_kW"), "kWh", 0),
            ("Benutte PV", annual_sum(df, "P_pv_used_kW"), "kWh", 0),
            ("Afgetopte PV", annual_sum(df, "P_pv_curtailed_kW"), "kWh", 0),
            ("Jaaropwek WKK", annual_sum(df, "P_wkk_el_kW"), "kWh", 0),
            ("Piek netimport", peak_value(df, "P_grid_import_kW"), "kW", 1),
        ]
    )
    render_daily_stacked_area_chart(
        "Opgewekte energie per dag",
        daily_energy_by_category(df, GENERATION_CATEGORIES),
    )
    c_gen_mix1, c_gen_mix2 = st.columns(2)
    with c_gen_mix1:
        render_donut_chart("Herkomst elektriciteit", annual_energy_by_category(df, ELECTRICITY_SUPPLY_CATEGORIES))
    with c_gen_mix2:
        render_monthly_stacked_bar_chart("Herkomst elektriciteit per maand", monthly_energy_by_category(df, ELECTRICITY_SUPPLY_CATEGORIES))
    render_load_match_balance_charts(df)

def plot_peak_grid_import_week_stacked(
    df: pd.DataFrame,
    title: str = "Zwaarste netweek",
    contract_kW: float | None = None,
):
    if df is None or df.empty or "P_grid_import_kW" not in df.columns:
        return

    week_df = df.loc[find_peak_week(df, "P_grid_import_kW")].copy()
    week_df = week_df.reset_index().rename(columns={"index": "timestamp"})

    supply_cols = [
        "P_pv_used_kW" if "P_pv_used_kW" in week_df.columns else "P_pv_kW",
        "P_wkk_el_kW",
        "P_battery_discharge_kW",
        "P_grid_import_kW",
    ]
    supply_cols = [c for c in supply_cols if c in week_df.columns]

    st.markdown(f"**{title}**")

    if not supply_cols:
        st.info("Geen assets beschikbaar voor stacked plot.")
        return

    supply_long = week_df[["timestamp"] + supply_cols].melt(
        id_vars="timestamp",
        var_name="asset",
        value_name="power_kW",
    )
    supply_long["asset_label"] = supply_long["asset"].map(lambda c: COLUMN_LABELS.get(c, c))
    supply_long["vermogen"] = supply_long["power_kW"].map(lambda v: _fmt_kpi(v, "kW", 2))

    stacked_area = (
        alt.Chart(supply_long)
        .mark_area()
        .encode(
            x=alt.X("timestamp:T", title="Tijd"),
            y=alt.Y("power_kW:Q", stack=True, title="Vermogen [kW]"),
            color=alt.Color("asset_label:N", title="Energiedrager"),
            tooltip=[
                "timestamp:T",
                "asset_label:N",
                alt.Tooltip("vermogen:N", title="Vermogen"),
            ],
        )
    )

    layers = [stacked_area]

    if contract_kW is not None:
        contract_df = pd.DataFrame(
            {
                "timestamp": week_df["timestamp"],
                "contract_kW": float(contract_kW),
            }
        )
        contract_df["contract"] = contract_df["contract_kW"].map(lambda v: _fmt_kpi(v, "kW", 2))

        contract_line = (
            alt.Chart(contract_df)
            .mark_line(color="red", strokeDash=[8, 4], strokeWidth=2)
            .encode(
                x=alt.X("timestamp:T", title="Tijd"),
                y=alt.Y("contract_kW:Q", title="Vermogen [kW]"),
                tooltip=[
                    "timestamp:T",
                    alt.Tooltip("contract:N", title="Contractvermogen"),
                ],
            )
        )

        layers.append(contract_line)

    chart = alt.layer(*layers).interactive()
    st.altair_chart(chart, width='stretch')
    render_plot_explanation("grid_week", f"Contractvermogen: {'niet ingesteld' if contract_kW is None else _fmt_kpi(contract_kW, 'kW', 1)}.")

    if "battery_soc_pct" in week_df.columns:
        st.markdown("**Vullingsgraad batterij [%]**")
        week_df["battery_soc_label"] = week_df["battery_soc_pct"].map(lambda v: _fmt_kpi(v, "%", 2))
        soc_chart = (
            alt.Chart(week_df)
            .mark_line(strokeWidth=2)
            .encode(
                x=alt.X("timestamp:T", title="Tijd"),
                y=alt.Y("battery_soc_pct:Q", title="Vullingsgraad batterij [%]"),
                tooltip=["timestamp:T", alt.Tooltip("battery_soc_label:N", title="Vullingsgraad")],
            )
            .interactive()
        )
        st.altair_chart(soc_chart, width='stretch')
        render_plot_explanation("battery_soc")

def energy_kpis(df: pd.DataFrame) -> dict:
    zero = pd.Series(0.0, index=df.index)
    peak_before = float(df.get("P_grid_import_before_battery_kW", zero).max())
    peak_after = float(df.get("P_grid_import_kW", zero).max())
    peak_contract_excess = float(df.get("P_grid_contract_excess_kW", zero).max())
    out = {
        "Piek totaal verbruik [kW]": round(float(df["P_load_total_kW"].max()), 2) if "P_load_total_kW" in df else 0.0,
        "Piek netimport voor batterij [kW]": round(peak_before, 2),
        "Piek netimport na batterij [kW]": round(peak_after, 2),
        "Piekverlaging door batterij [kW]": round(max(peak_before - peak_after, 0.0), 2),
        "Piek boven contractvermogen [kW]": round(peak_contract_excess, 2),
        "Jaarverbruik elektriciteit [kWh]": round(float((df.get("P_load_total_kW", zero) * DT_HOURS).sum()), 0),
        "Jaaropwek zonnepanelen [kWh]": round(float((df.get("P_pv_kW", zero) * DT_HOURS).sum()), 0),
        "Jaarlijks benutte PV [kWh]": round(float((df.get("P_pv_used_kW", df.get("P_pv_kW", zero)) * DT_HOURS).sum()), 0),
        "Jaarlijks afgetopte PV [kWh]": round(float((df.get("P_pv_curtailed_kW", zero) * DT_HOURS).sum()), 0),
        "Jaaropwek WKK elektrisch [kWh]": round(float((df.get("P_wkk_el_kW", zero) * DT_HOURS).sum()), 0),
        "Jaarverbruik warmtepomp elektriciteit [kWh]": round(float((df.get("P_hp_el_kW", zero) * DT_HOURS).sum()), 0),
        "Jaarverbruik referentie verwarming elektriciteit [kWh]": round(float((df.get("P_heat_ref_el_kW", zero) * DT_HOURS).sum()), 0),
        "Jaarverbruik koeling elektriciteit [kWh]": round(float((df.get("P_cool_el_kW", zero) * DT_HOURS).sum()), 0),
        "Jaarlijkse netimport [kWh]": round(float((df.get("P_grid_import_kW", zero) * DT_HOURS).sum()), 0),
        "Jaarlijkse teruglevering [kWh]": round(float((df.get("P_grid_export_kW", zero) * DT_HOURS).sum()), 0),
        "Jaarlijks laden batterij [kWh]": round(float((df.get("P_battery_charge_kW", zero) * DT_HOURS).sum()), 0),
        "Jaarlijks ontladen batterij [kWh]": round(float((df.get("P_battery_discharge_kW", zero) * DT_HOURS).sum()), 0),
        "Jaarlijkse warmtevraag [kWhth]": round(float((df.get("Q_heat_demand_kWth", zero) * DT_HOURS).sum()), 0),
        "Jaarlijks geleverde warmte [kWhth]": round(float((df.get("Q_heat_supply_total_kWth", zero) * DT_HOURS).sum()), 0),
        "Jaarlijkse ongedekte warmte [kWhth]": round(float((df.get("Q_heat_unserved_final_kWth", zero) * DT_HOURS).sum()), 0),
        "Jaarlijkse ketelwarmte [kWhth]": round(float((df.get("Q_boiler_th_kWth", zero) * DT_HOURS).sum()), 0),
        "Jaarlijkse warmtenetlevering [kWhth]": round(float((df.get("Q_dh_th_kWth", zero) * DT_HOURS).sum()), 0),
        "Jaarlijkse referentieverwarming [kWhth]": round(float((df.get("Q_heat_from_reference_kWth", zero) * DT_HOURS).sum()), 0),
        "Jaarlijkse WKK-warmte benut [kWhth]": round(float((df.get("Q_wkk_used_kWth", zero) * DT_HOURS).sum()), 0),
        "Jaarlijkse WKK-warmte niet benut [kWhth]": round(float((df.get("Q_wkk_dumped_kWth", zero) * DT_HOURS).sum()), 0),
        "Jaarlijks ontladen warmteopslag [kWhth]": round(float((df.get("Q_thermal_storage_discharge_kWth", zero) * DT_HOURS).sum()), 0),
    }
    return out

def compute_grid_stress_metrics(df: pd.DataFrame, contract_kW: float):
    if contract_kW is None or contract_kW <= 0:
        return {}

    imp = df.get("P_grid_import_kW")
    if imp is None:
        return {}

    dt_h = series_dt_hours(df)
    metrics = {}

    metrics["hours_above_90"] = float((imp > 0.9 * contract_kW).sum() * dt_h)
    metrics["hours_above_95"] = float((imp > 0.95 * contract_kW).sum() * dt_h)
    metrics["hours_above_100"] = float((imp > contract_kW).sum() * dt_h)
    metrics["avg_headroom_kW"] = float((contract_kW - imp).clip(lower=0).mean())

    peak = float(imp.max()) if len(imp) else 0.0
    avg = float(imp.mean()) if len(imp) else 0.0
    metrics["load_factor"] = avg / peak if peak > 0 else 0.0

    total_load = df.get("P_load_total_kW")
    if total_load is not None:
        total_energy = float((total_load * dt_h).sum())
        grid_energy = float((imp * dt_h).sum())
        metrics["self_sufficiency"] = 1.0 - (grid_energy / total_energy) if total_energy > 0 else 0.0
    else:
        metrics["self_sufficiency"] = None

    return metrics

def render_grid_stoplight(df: pd.DataFrame, grid_cap_kW: float | None, cfg=None) -> dict | None:
    if df is None or df.empty or "P_grid_import_kW" not in df.columns:
        st.info("Stoplicht beschikbaar zodra een total-run met netimport is uitgevoerd.")
        return None

    grid_eval = df.attrs.get("grid_evaluation")
    if grid_eval is None:
        if cfg is None:
            st.info("Stoplicht beschikbaar zodra evaluatieconfig of contractvermogen beschikbaar is.")
            return None
        grid_eval = evaluate_grid(
            df,
            grid_contract_kW=grid_cap_kW,
            stoplight_thresholds=getattr(cfg.evaluation, "stoplight_thresholds", None),
            max_exceedance_duration_h=float(getattr(cfg.evaluation, "max_exceedance_duration_h", 0.0)),
            max_exceedance_energy_kWh=float(getattr(cfg.evaluation, "max_exceedance_energy_kWh", 0.0)),
            peak_percentiles=tuple(getattr(cfg.evaluation, "peak_percentiles", (0.95, 0.99))),
            robust_green_margin_fraction=float(getattr(cfg.evaluation, "robust_green_margin_fraction", 0.05)),
        )
        df.attrs["grid_evaluation"] = grid_eval

    status = str(grid_eval.get("stoplight", "unknown"))
    contract = grid_eval.get("grid_contract_kW")
    peak = float(grid_eval.get("peak_grid_import_kW", 0.0) or 0.0)
    peak_ratio = grid_eval.get("peak_ratio_to_contract")
    exceed_h = grid_eval.get("contract_exceedance_hours")
    exceed_energy = grid_eval.get("contract_exceedance_energy_kWh")
    worst_run = grid_eval.get("worst_continuous_exceedance_h")
    p99 = grid_eval.get("p99_grid_import_kW")

    if status == "green":
        st.success(f"Groen · piek netimport {_fmt_kpi(peak, 'kW', 1)} bij contract {_fmt_kpi(contract, 'kW', 1)}")
    elif status == "orange":
        st.warning(f"Oranje · netimport zit dicht op of net boven contract ({_fmt_kpi(peak, 'kW', 1)} / {_fmt_kpi(contract, 'kW', 1)})")
    elif status == "red":
        st.error(f"Rood · netimport overschrijdt contract ({_fmt_kpi(peak, 'kW', 1)} / {_fmt_kpi(contract, 'kW', 1)})")
    else:
        st.info("Stoplicht onbekend: stel een contractvermogen > 0 in.")
        return grid_eval

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Piek netimport [kW]", _fmt_nl_number(peak, 1))
    c2.metric("Piek / contract", "-" if peak_ratio is None else f"{_fmt_nl_number(peak_ratio, 2)}x")
    c3.metric("Duur overschrijding [h]", "-" if exceed_h is None else _fmt_nl_number(exceed_h, 2))
    c4.metric("Energie boven contract [kWh]", "-" if exceed_energy is None else _fmt_nl_number(exceed_energy, 1))
    c5.metric("Langste overschrijding [h]", "-" if worst_run is None else _fmt_nl_number(worst_run, 2))

    if p99 is not None:
        st.caption(f"P99 netimport: {_fmt_kpi(p99, 'kW', 1)}")

    return grid_eval


def render_grid_duration_curve(df: pd.DataFrame, grid_cap_kW: float | None) -> None:
    if df is None or df.empty or "P_grid_import_kW" not in df.columns:
        return

    duration_df = build_grid_duration_curve(df, contract_kW=grid_cap_kW)
    duration_long = duration_df[["duration_h", "P_grid_import_kW", "P_grid_contract_kW"]].melt(
        id_vars="duration_h",
        var_name="series",
        value_name="power_kW",
    )
    duration_long = duration_long.dropna(subset=["power_kW"])

    st.markdown("**Duurcurve netbelasting**")
    duration_long = duration_long.copy()
    duration_long["duur"] = duration_long["duration_h"].map(lambda v: _fmt_kpi(v, "h", 0))
    duration_long["vermogen"] = duration_long["power_kW"].map(lambda v: _fmt_kpi(v, "kW", 1))
    chart = (
        alt.Chart(duration_long)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("duration_h:Q", title="Uren per jaar (gesorteerd)"),
            y=alt.Y("power_kW:Q", title="Vermogen [kW]"),
            color=alt.Color("series:N", title="Serie"),
            tooltip=[
                alt.Tooltip("duur:N", title="Duur"),
                alt.Tooltip("vermogen:N", title="Vermogen"),
                "series:N"
            ],
        )
        .interactive()
    )
    st.altair_chart(chart, width='stretch')
    render_plot_explanation("duration", f"Contractvermogen: {'niet ingesteld' if grid_cap_kW is None else _fmt_kpi(grid_cap_kW, 'kW', 1)}.")


def render_measurement_metadata(metadata: dict | None) -> None:
    if not metadata:
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rijen", _fmt_nl_number(metadata.get("row_count"), 0) if metadata.get("row_count") is not None else "-")
    c2.metric("Dubbele tijdstippen", _fmt_nl_number(metadata.get("duplicate_timestamp_count"), 0) if metadata.get("duplicate_timestamp_count") is not None else "-")
    c3.metric("Detecteerde resolutie", str(metadata.get("detected_resolution") or "-")[:18])
    coverage = metadata.get("coverage_fraction_vs_expected")
    c4.metric("Dekking", "-" if coverage is None else f"{_fmt_nl_number(100.0 * float(coverage), 1)}%")

    st.caption(
        f"Bron: {metadata.get('source_path', '-') } · tijdzone: {metadata.get('timezone', '-') } · "
        f"verwachte resolutie: {metadata.get('expected_resolution', '-') } · omrekening: {metadata.get('resample_policy', '-') }"
    )
    warnings = list(metadata.get("warnings", []))
    if warnings:
        for w in warnings:
            st.warning(w)


def render_validation_results(validation: dict | None) -> None:
    if not validation:
        return

    warnings = validation.get("warnings", [])
    for w in warnings:
        st.warning(w)

    metrics = validation.get("metrics", {})
    peak = validation.get("peak_summary", {})

    st.markdown("**Validatiematen**")
    validation_label_by_period = {
        "hourly": "Uurwaarden",
        "daily": "Dagwaarden",
        "monthly": "Maandwaarden",
    }
    for label in ["hourly", "daily", "monthly"]:
        m = metrics.get(label, {})
        if not m:
            continue
        st.markdown(f"***{validation_label_by_period[label]}***")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("N", _fmt_nl_number(m.get("n_points", 0), 0))
        c2.metric("RMSE", "-" if pd.isna(m.get("rmse")) else _fmt_nl_number(m["rmse"], 2))
        c3.metric("MAE", "-" if pd.isna(m.get("mae")) else _fmt_nl_number(m["mae"], 2))
        c4.metric("NMBE [%]", "-" if pd.isna(m.get("nmbe_pct")) else _fmt_nl_number(m["nmbe_pct"], 2))
        c5.metric("CV(RMSE) [%]", "-" if pd.isna(m.get("cv_rmse_pct")) else _fmt_nl_number(m["cv_rmse_pct"], 2))

    if peak:
        st.markdown("**Vergelijking piekvermogen**")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Piek simulatie [kW]", "-" if pd.isna(peak.get("peak_simulated")) else _fmt_nl_number(peak["peak_simulated"], 2))
        c2.metric("Piek meting [kW]", "-" if pd.isna(peak.get("peak_measured")) else _fmt_nl_number(peak["peak_measured"], 2))
        c3.metric("Piekverschil [kW]", "-" if pd.isna(peak.get("peak_bias_kW")) else _fmt_nl_number(peak["peak_bias_kW"], 2))
        c4.metric("Piekverschil [%]", "-" if pd.isna(peak.get("peak_bias_pct")) else _fmt_nl_number(peak["peak_bias_pct"], 2))

    aligned = validation.get("aligned")
    if aligned is not None and not aligned.empty:
        st.markdown("**Simulatie en meting**")
        compare_df = aligned[["simulated", "measured"]].reset_index()
        ts_col = compare_df.columns[0]
        compare_long = compare_df.melt(id_vars=ts_col, var_name="series", value_name="value")
        compare_long["waarde"] = compare_long["value"].map(lambda v: _fmt_kpi(v, "kW", 2))
        chart = (
            alt.Chart(compare_long)
            .mark_line()
            .encode(
                x=alt.X(f"{ts_col}:T", title="Tijd"),
                y=alt.Y("value:Q", title="Vermogen"),
                color=alt.Color("series:N", title="Serie"),
                tooltip=[f"{ts_col}:T", "series:N", alt.Tooltip("waarde:N", title="Vermogen")],
            )
            .interactive()
        )
        st.altair_chart(chart, width='stretch')
        render_plot_explanation("validation", "De blauwe/oranje reeksen laten zien of de simulatie dezelfde orde van grootte en timing heeft als de meting.")

        st.markdown("**Spreiding simulatie en meting**")
        scatter_base = aligned.reset_index()[["measured", "simulated", "residual"]].copy()
        scatter_base["meting"] = scatter_base["measured"].map(lambda v: _fmt_kpi(v, "kW", 2))
        scatter_base["simulatie"] = scatter_base["simulated"].map(lambda v: _fmt_kpi(v, "kW", 2))
        scatter_base["residu"] = scatter_base["residual"].map(lambda v: _fmt_kpi(v, "kW", 2))
        lo = float(min(scatter_base["measured"].min(), scatter_base["simulated"].min()))
        hi = float(max(scatter_base["measured"].max(), scatter_base["simulated"].max()))
        ref_df = pd.DataFrame({"ref_x": [lo, hi], "ref_y": [lo, hi]})
        scatter_chart = alt.layer(
            alt.Chart(scatter_base).mark_circle(size=45).encode(
                x=alt.X("measured:Q", title="Meting"),
                y=alt.Y("simulated:Q", title="Simulatie"),
                tooltip=[alt.Tooltip("meting:N", title="Meting"), alt.Tooltip("simulatie:N", title="Simulatie"), alt.Tooltip("residu:N", title="Residu")],
            ),
            alt.Chart(ref_df).mark_line(strokeDash=[6, 4]).encode(x="ref_x:Q", y="ref_y:Q")
        ).interactive()
        st.altair_chart(scatter_chart, width='stretch')
        render_plot_explanation("validation", "Punten dicht bij de diagonale lijn betekenen dat simulatie en meting goed overeenkomen.")

        st.markdown("**Verschil tussen simulatie en meting**")
        residual_df = aligned.reset_index()
        residual_df["residu"] = residual_df["residual"].map(lambda v: _fmt_kpi(v, "kW", 2))
        residual_chart = (
            alt.Chart(residual_df)
            .mark_line()
            .encode(
                x=alt.X(f"{aligned.reset_index().columns[0]}:T", title="Tijd"),
                y=alt.Y("residual:Q", title="Verschil [simulatie - meting]"),
                tooltip=[alt.Tooltip("residu:N", title="Residu")],
            )
            .interactive()
        )
        st.altair_chart(residual_chart, width='stretch')
        render_plot_explanation("validation", "Een residu rond nul betekent weinig afwijking; structureel positief of negatief wijst op bias in het model.")

    monthly = validation.get("aggregations", {}).get("monthly")
    if monthly is not None and not monthly.empty:
        st.markdown("**Maandtotalen**")
        monthly_reset = monthly[["simulated", "measured"]].reset_index()
        ts_col = monthly_reset.columns[0]
        monthly_long = monthly_reset.melt(id_vars=ts_col, var_name="series", value_name="value")
        monthly_long["waarde"] = monthly_long["value"].map(lambda v: _fmt_nl_number(v, 2))
        month_chart = (
            alt.Chart(monthly_long)
            .mark_bar()
            .encode(
                x=alt.X(f"{ts_col}:T", title="Maand"),
                y=alt.Y("value:Q", title="Totaal"),
                color=alt.Color("series:N", title="Serie"),
                xOffset="series:N",
                tooltip=[f"{ts_col}:T", "series:N", alt.Tooltip("waarde:N", title="Totaal")],
            )
            .interactive()
        )
        st.altair_chart(month_chart, width='stretch')
        render_plot_explanation("validation", "Maandtotalen laten zien of het model over langere perioden te hoog of te laag uitkomt.")



def render_sanity_checks(df: pd.DataFrame | None) -> None:
    if df is None:
        return
    checks = df.attrs.get("sanity_checks") or {}
    if not checks:
        return
    st.markdown("**Modelchecks**")
    c1, c2, c3 = st.columns(3)
    c1.metric("Warmtebalans klopt", "Ja" if checks.get("heat_balance_within_tolerance") else "Nee")
    c2.metric("Negatieve fysica", "Nee" if checks.get("no_non_physical_negatives") else "Ja")
    c3.metric("Vermogensgrenzen", "Ok" if checks.get("all_capacity_constraints_respected") else "Overschreden")
    st.caption(
        f"max |heat residual| = {_fmt_kpi(checks.get('heat_balance_max_abs_residual_kWth', float('nan')), 'kWth', 4)}"
    )
    if checks.get("non_physical_negative_columns"):
        st.warning("Niet-fysische negatieve waarden in: " + ", ".join(checks["non_physical_negative_columns"]))
    violations = checks.get("capacity_violations") or {}
    active_violations = {k: v for k, v in violations.items() if float(v) > 1e-9}
    if active_violations:
        st.warning("Overschreden vermogensgrenzen: " + ", ".join(f"{k}={_fmt_nl_number(v, 3)}" for k, v in active_violations.items()))


def build_export_bundle(df: pd.DataFrame, measurement_metadata: dict | None = None, validation_result: dict | None = None) -> bytes:
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("energy_system_results.csv", df.to_csv())

        summary = {
            "kpis": df.attrs.get("kpis", {}),
            "grid_evaluation": df.attrs.get("grid_evaluation", {}),
            "sanity_checks": df.attrs.get("sanity_checks", {}),
            "measurement_metadata": measurement_metadata or {},
            "validation_metrics": (validation_result or {}).get("metrics", {}),
            "validation_peak_summary": (validation_result or {}).get("peak_summary", {}),
            "validation_warnings": (validation_result or {}).get("warnings", []),
        }
        zf.writestr("summary.json", json.dumps(summary, indent=2, default=str))

        if validation_result is not None and validation_result.get("aligned") is not None:
            zf.writestr("validation_aligned.csv", validation_result["aligned"].to_csv())
        if validation_result is not None:
            aggs = validation_result.get("aggregations", {})
            for name, agg_df in aggs.items():
                if agg_df is not None and not agg_df.empty:
                    zf.writestr(f"validation_{name}.csv", agg_df.to_csv())
    memory.seek(0)
    return memory.getvalue()


def _pdf_finish_page(pdf: PdfPages, fig) -> None:
    fig.tight_layout(rect=[0.035, 0.035, 0.965, 0.945])
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _pdf_header(fig, title: str, subtitle: str | None = None) -> None:
    fig.suptitle(title, x=0.04, y=0.985, ha="left", va="top", fontsize=15, fontweight="bold")
    if subtitle:
        fig.text(0.04, 0.945, subtitle, ha="left", va="top", fontsize=9, color="#56616F")


def _pdf_table(ax, rows: list[tuple[str, object, str]], *, title: str | None = None) -> None:
    ax.axis("off")
    if title:
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold", pad=8)
    cell_text = [[label, _fmt_kpi(value, unit, 1 if unit in {"%", "kW", "kWth", "h"} else 0)] for label, value, unit in rows]
    table = ax.table(cellText=cell_text, colLabels=["Indicator", "Waarde"], cellLoc="left", colLoc="left", loc="upper left")
    table.auto_set_font_size(False)
    table.set_fontsize(8.5)
    table.scale(1, 1.18)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#D8DEE8")
        if row == 0:
            cell.set_facecolor("#F4F7FB")
            cell.set_text_props(fontweight="bold")


def _pdf_monthly_pivot(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return pd.DataFrame()
    pivot = data.pivot_table(index="maand", columns="categorie", values="energie_kWh", aggfunc="sum", fill_value=0.0)
    return pivot.reindex([m for m in MONTH_ORDER if m in pivot.index]).fillna(0.0)


def _pdf_plot_monthly(ax, title: str, data: pd.DataFrame, *, unit: str = "kWh") -> None:
    pivot = _pdf_monthly_pivot(data)
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold")
    if pivot.empty:
        ax.text(0.02, 0.5, "Geen data beschikbaar.", transform=ax.transAxes, fontsize=9)
        ax.axis("off")
        return
    pivot.plot(kind="bar", stacked=True, ax=ax, width=0.78)
    ax.set_xlabel("Maand")
    ax.set_ylabel(f"Energie [{unit}]")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1.0))


def _pdf_plot_daily_area(ax, title: str, data: pd.DataFrame, *, unit: str = "kWh/dag") -> None:
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold")
    if data.empty:
        ax.text(0.02, 0.5, "Geen data beschikbaar.", transform=ax.transAxes, fontsize=9)
        ax.axis("off")
        return
    pivot = data.pivot_table(index="datum", columns="categorie", values="energie_kWh", aggfunc="sum", fill_value=0.0)
    pivot.index = pd.to_datetime(pivot.index).tz_localize(None) if getattr(pivot.index, "tz", None) is not None else pd.to_datetime(pivot.index)
    pivot.plot.area(ax=ax, alpha=0.82, linewidth=0)
    ax.set_xlabel("Datum")
    ax.set_ylabel(f"Energie [{unit}]")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1.0))


def _pdf_plot_pie(ax, title: str, data: pd.DataFrame) -> None:
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold")
    if data.empty or float(data["energie_kWh"].sum()) <= 0:
        ax.text(0.02, 0.5, "Geen data beschikbaar.", transform=ax.transAxes, fontsize=9)
        ax.axis("off")
        return
    values = data["energie_kWh"].to_numpy(dtype=float)
    labels = data["categorie"].tolist()
    ax.pie(values, labels=labels, autopct=lambda p: f"{p:.0f}%" if p >= 4 else "", startangle=90, textprops={"fontsize": 7})
    ax.axis("equal")


def _pdf_time_index(index) -> pd.DatetimeIndex:
    x = pd.DatetimeIndex(pd.to_datetime(index))
    if x.tz is not None:
        return x.tz_localize(None)
    return x


def _pdf_plot_peak_grid_week(ax, df: pd.DataFrame, contract: float | None) -> None:
    ax.set_title("Zwaarste netweek", loc="left", fontsize=10, fontweight="bold")
    if df.empty or "P_grid_import_kW" not in df.columns:
        ax.axis("off")
        return
    week = df.loc[find_peak_week(df, "P_grid_import_kW")].copy()
    x = _pdf_time_index(week.index)
    context_cols = [c for c in ["P_load_total_kW", "P_pv_kW", "P_wkk_el_kW", "P_battery_discharge_kW"] if c in week.columns]
    for col in context_cols:
        ax.plot(x, week[col], linewidth=1.0, alpha=0.55, label=COLUMN_LABELS.get(col, col))
    ax.plot(x, week["P_grid_import_kW"], linewidth=2.7, color="#0B5FFF", label="Netimport")
    if contract is not None:
        ax.axhline(float(contract), color="#D62728", linestyle="--", linewidth=1.4, label="Contractvermogen")
    ax.set_ylabel("Vermogen [kW]")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1.0))


def _pdf_plot_duration(ax, df: pd.DataFrame, contract: float | None) -> None:
    ax.set_title("Duurcurve netbelasting", loc="left", fontsize=10, fontweight="bold")
    if df.empty or "P_grid_import_kW" not in df.columns:
        ax.axis("off")
        return
    duration = build_grid_duration_curve(df, contract_kW=contract)
    ax.plot(duration["duration_h"], duration["P_grid_import_kW"], linewidth=2.0, color="#0B5FFF", label="Netimport")
    if "P_grid_contract_kW" in duration.columns and contract is not None:
        ax.plot(duration["duration_h"], duration["P_grid_contract_kW"], linestyle="--", color="#D62728", linewidth=1.4, label="Contract")
    ax.set_xlabel("Uren per jaar gesorteerd")
    ax.set_ylabel("Vermogen [kW]")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(fontsize=7)


def _pdf_plot_peak_week(ax, df: pd.DataFrame, peak_col: str, cols: list[str], title: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=10, fontweight="bold")
    if df.empty or peak_col not in df.columns:
        ax.axis("off")
        return
    week = df.loc[find_peak_week(df, peak_col)].copy()
    x = _pdf_time_index(week.index)
    for col in [c for c in cols if c in week.columns]:
        ax.plot(x, week[col], linewidth=1.5 if col == peak_col else 1.0, label=COLUMN_LABELS.get(col, col))
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1.0))


def _pdf_plot_gas_week(ax, df: pd.DataFrame) -> None:
    gas_col = "F_total_gas_kW" if "F_total_gas_kW" in df.columns and float(df["F_total_gas_kW"].fillna(0.0).sum()) > 1e-9 else "F_total_fuel_kW"
    ax.set_title("Zwaarste gasweek", loc="left", fontsize=10, fontweight="bold")
    if df.empty or gas_col not in df.columns or float(df[gas_col].fillna(0.0).sum()) <= 1e-9:
        ax.text(0.02, 0.5, "Geen gas- of brandstofvraag aanwezig.", transform=ax.transAxes, fontsize=9)
        ax.axis("off")
        return
    week = df.loc[find_highest_energy_week(df, gas_col)].copy()
    x = _pdf_time_index(week.index)
    for col in [c for c in [gas_col, "F_wkk_gas_kW", "F_boiler_gas_kW", "F_wkk_fuel_kW", "F_boiler_fuel_kW"] if c in week.columns]:
        ax.plot(x, week[col], linewidth=1.5 if col == gas_col else 1.0, label=COLUMN_LABELS.get(col, col))
    ax.set_ylabel("Gas-/brandstofvermogen [kW]")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(fontsize=7, loc="upper left", bbox_to_anchor=(1.01, 1.0))


def build_results_report_pdf(df: pd.DataFrame, contract: float | None) -> bytes:
    kpis = energy_kpis(df)
    grid_eval = df.attrs.get("grid_evaluation") or {}
    grid_metrics = compute_grid_stress_metrics(df, contract)
    generated_at = pd.Timestamp.now(tz=TZ).strftime("%Y-%m-%d %H:%M")
    memory = io.BytesIO()
    with PdfPages(memory) as pdf:
        fig, axes = plt.subplots(2, 1, figsize=(11.69, 8.27), gridspec_kw={"height_ratios": [1, 1.05]})
        _pdf_header(fig, "Resultatenrapport energieplanner", f"Gegenereerd op {generated_at}")
        _pdf_table(
            axes[0],
            [
                ("Stoplicht", str(grid_eval.get("stoplight", "onbekend")).capitalize(), ""),
                ("Piek netimport", kpis.get("Piek netimport na batterij [kW]"), "kW"),
                ("Piek boven contract", kpis.get("Piek boven contractvermogen [kW]"), "kW"),
                ("Jaarlijkse netimport", kpis.get("Jaarlijkse netimport [kWh]"), "kWh"),
                ("Ongedekte warmte", kpis.get("Jaarlijkse ongedekte warmte [kWhth]"), "kWhth"),
                ("Gas-/brandstofinput", float(df.attrs.get("kpis", {}).get("annual_fuel_input_kWh", 0.0)), "kWh"),
            ],
            title="Beslissingssamenvatting",
        )
        _pdf_table(
            axes[1],
            [
                ("Contractvermogen", contract, "kW"),
                ("Uren > 90% contract", grid_metrics.get("hours_above_90"), "h"),
                ("Uren > 95% contract", grid_metrics.get("hours_above_95"), "h"),
                ("Uren > 100% contract", grid_metrics.get("hours_above_100"), "h"),
                ("Gemiddelde netruimte", grid_metrics.get("avg_headroom_kW"), "kW"),
                ("Benuttingsgraad", grid_metrics.get("load_factor"), ""),
                ("Zelfvoorziening", None if grid_metrics.get("self_sufficiency") is None else 100.0 * float(grid_metrics["self_sufficiency"]), "%"),
            ],
            title="Netcapaciteit",
        )
        _pdf_finish_page(pdf, fig)

        fig, axes = plt.subplots(2, 1, figsize=(11.69, 8.27))
        _pdf_header(fig, "Netcapaciteit")
        _pdf_plot_peak_grid_week(axes[0], df, contract)
        _pdf_plot_duration(axes[1], df, contract)
        _pdf_finish_page(pdf, fig)

        fig, axes = plt.subplots(2, 1, figsize=(11.69, 8.27))
        _pdf_header(fig, "Jaarprofielen")
        _pdf_plot_daily_area(axes[0], "Jaarprofiel verbruik", daily_energy_by_category(df, ELECTRIC_CONSUMPTION_CATEGORIES))
        _pdf_plot_daily_area(axes[1], "Jaarprofiel opwek", daily_energy_by_category(df, GENERATION_CATEGORIES))
        _pdf_finish_page(pdf, fig)

        fig, axes = plt.subplots(2, 2, figsize=(11.69, 8.27))
        _pdf_header(fig, "Verbruik En Herkomst Elektriciteit")
        _pdf_plot_pie(axes[0, 0], "Jaarmix verbruik", annual_energy_by_category(df, ELECTRIC_CONSUMPTION_CATEGORIES))
        _pdf_plot_monthly(axes[0, 1], "Maandverbruik", monthly_energy_by_category(df, ELECTRIC_CONSUMPTION_CATEGORIES))
        _pdf_plot_pie(axes[1, 0], "Herkomst elektriciteit", annual_energy_by_category(df, ELECTRICITY_SUPPLY_CATEGORIES))
        _pdf_plot_monthly(axes[1, 1], "Herkomst elektriciteit per maand", monthly_energy_by_category(df, ELECTRICITY_SUPPLY_CATEGORIES))
        _pdf_finish_page(pdf, fig)

        fig, axes = plt.subplots(3, 1, figsize=(11.69, 8.27))
        _pdf_header(fig, "Warmte En Gasloosheid")
        _pdf_plot_monthly(axes[0], "Warmtebalans per maand", monthly_energy_by_category(df, HEAT_SUPPLY_CATEGORIES), unit="kWhth")
        _pdf_plot_peak_week(axes[1], df, "Q_heat_demand_kWth", ["Q_heat_demand_kWth", "Q_hp_th_kWth", "Q_wkk_used_kWth", "Q_boiler_th_kWth", "Q_dh_th_kWth", "Q_heat_from_reference_kWth", "Q_heat_unserved_final_kWth"], "Zwaarste warmteweek", "Warmtevermogen [kWth]")
        _pdf_plot_gas_week(axes[2], df)
        _pdf_finish_page(pdf, fig)

        fig, axes = plt.subplots(2, 1, figsize=(11.69, 8.27))
        _pdf_header(fig, "Opslag En Flexibiliteit")
        _pdf_plot_monthly(axes[0], "Opslagstromen per maand", monthly_energy_by_category(df, STORAGE_CATEGORIES))
        if "battery_soc_pct" in df.columns:
            worst_week_idx = find_worst_grid_week(df)
            if len(worst_week_idx) > 0:
                week = df.loc[worst_week_idx]
                axes[1].set_title("Batterijvulling in zwaarste netweek", loc="left", fontsize=10, fontweight="bold")
                axes[1].plot(_pdf_time_index(week.index), week["battery_soc_pct"], linewidth=1.8, color="#0B5FFF")
                axes[1].set_ylabel("Vullingsgraad [%]")
                axes[1].grid(axis="y", alpha=0.25)
            else:
                axes[1].axis("off")
        else:
            axes[1].text(0.02, 0.5, "Geen batterij-SOC beschikbaar.", transform=axes[1].transAxes, fontsize=9)
            axes[1].axis("off")
        _pdf_finish_page(pdf, fig)
    memory.seek(0)
    return memory.getvalue()


def render_model_quality_section(df: pd.DataFrame) -> None:
    checks = df.attrs.get("sanity_checks") or {}
    if not checks:
        st.info("Modelchecks zijn niet beschikbaar voor deze run.")
        return
    ok = bool(checks.get("heat_balance_within_tolerance")) and bool(checks.get("no_non_physical_negatives")) and bool(checks.get("all_capacity_constraints_respected"))
    if ok:
        st.success("Modelchecks: OK")
    else:
        st.warning("Modelchecks: aandacht nodig")
    with st.expander("Details modelchecks", expanded=False):
        render_sanity_checks(df)


def render_results_dashboard(df: pd.DataFrame, contract: float | None, cfg=None) -> None:
    kpis = energy_kpis(df)
    grid_eval = df.attrs.get("grid_evaluation") or {}
    grid_metrics = compute_grid_stress_metrics(df, contract)

    st.markdown("### 1. Beslissingssamenvatting")
    render_grid_stoplight(df, contract, cfg=cfg)
    render_kpi_row(
        [
            ("Jaarlijkse netimport", kpis.get("Jaarlijkse netimport [kWh]"), "kWh", 0),
            ("Ongedekte warmte", kpis.get("Jaarlijkse ongedekte warmte [kWhth]"), "kWhth", 0),
            ("Gas-/brandstofinput", float(df.attrs.get("kpis", {}).get("annual_fuel_input_kWh", 0.0)), "kWh", 0),
            ("Zelfvoorziening", None if grid_metrics.get("self_sufficiency") is None else 100.0 * float(grid_metrics["self_sufficiency"]), "%", 1),
        ]
    )
    stoplight = str(grid_eval.get("stoplight", "unknown"))
    heat_unserved = float(df.attrs.get("kpis", {}).get("annual_heat_unserved_kWhth", 0.0) or 0.0)
    fuel_input = float(df.attrs.get("kpis", {}).get("annual_fuel_input_kWh", 0.0) or 0.0)
    if stoplight == "green":
        st.caption("Netcapaciteit: de berekende netimport blijft binnen de ingestelde beoordelingsgrenzen.")
    elif stoplight in {"orange", "red"}:
        st.caption("Netcapaciteit: er zijn momenten waarop de aansluiting krap is of wordt overschreden; bekijk de netcapaciteitsectie voor oorzaak en duur.")
    else:
        st.caption("Netcapaciteit: stel een contractvermogen in om het stoplicht te beoordelen.")
    if heat_unserved <= 1e-6 and fuel_input <= 1e-6:
        st.caption("Warmte/gasloosheid: de warmtevraag wordt in deze run zonder resterende brandstofinput en zonder ongedekte warmte ingevuld.")
    elif heat_unserved <= 1e-6:
        st.caption("Warmte/gasloosheid: de warmtevraag is gedekt, maar er is nog brandstofinput aanwezig.")
    else:
        st.caption("Warmte/gasloosheid: er blijft ongedekte warmtevraag over; extra warmtecapaciteit of opslag is nodig.")

    st.markdown("### 2. Netcapaciteit")
    render_kpi_row(
        [
            ("Uren > 90%", grid_metrics.get("hours_above_90"), "h", 1),
            ("Uren > 95%", grid_metrics.get("hours_above_95"), "h", 1),
            ("Uren > 100%", grid_metrics.get("hours_above_100"), "h", 1),
            ("Gemiddelde netruimte", grid_metrics.get("avg_headroom_kW"), "kW", 1),
            ("Benuttingsgraad", grid_metrics.get("load_factor"), "", 2),
        ],
        columns=5,
    )
    render_peak_grid_week_interactive(df, contract)
    render_grid_duration_curve(df, contract)

    st.markdown("### 3. Jaarprofiel Verbruik")
    render_daily_stacked_area_chart(
        "Gebruikte energie per dag, uitgesplitst naar gebruikers",
        daily_energy_by_category(df, ELECTRIC_CONSUMPTION_CATEGORIES),
    )

    st.markdown("### 4. Jaarprofiel Opwek")
    render_daily_stacked_area_chart(
        "Opgewekte en beschikbare energie per dag",
        daily_energy_by_category(df, GENERATION_CATEGORIES),
    )

    st.markdown("### 5. Verbruiksmix")
    render_kpi_row(
        [
            ("Jaarverbruik elektriciteit", kpis.get("Jaarverbruik elektriciteit [kWh]"), "kWh", 0),
            ("Elektriciteitsintensiteit", intensity_per_m2(float(kpis.get("Jaarverbruik elektriciteit [kWh]", 0.0))), "kWh/m²", 1),
            ("Piek totaal verbruik", kpis.get("Piek totaal verbruik [kW]"), "kW", 1),
            ("Mobiliteit laden", annual_sum(df, "P_mobility_kW"), "kWh", 0),
        ]
    )
    c_mix1, c_mix2 = st.columns(2)
    with c_mix1:
        render_donut_chart("Jaarmix verbruik", annual_energy_by_category(df, ELECTRIC_CONSUMPTION_CATEGORIES))
    with c_mix2:
        render_monthly_stacked_bar_chart("Maandverbruik", monthly_energy_by_category(df, ELECTRIC_CONSUMPTION_CATEGORIES))

    st.markdown("### 6. Opwek En Load Match")
    pv_year = annual_sum(df, "P_pv_kW")
    pv_capacity = float(st.session_state.get("pv_cap", 0.0) or 0.0)
    render_kpi_row(
        [
            ("Jaaropwek PV", pv_year, "kWh", 0),
            ("Benutte PV", kpis.get("Jaarlijks benutte PV [kWh]"), "kWh", 0),
            ("Afgetopte PV", kpis.get("Jaarlijks afgetopte PV [kWh]"), "kWh", 0),
            ("Jaaropwek WKK", annual_sum(df, "P_wkk_el_kW"), "kWh", 0),
            ("Teruglevering", kpis.get("Jaarlijkse teruglevering [kWh]"), "kWh", 0),
            ("PV-vollasturen", pv_year / pv_capacity if pv_capacity > 0 else None, "h", 0),
        ]
    )
    c_gen1, c_gen2 = st.columns(2)
    with c_gen1:
        render_donut_chart("Herkomst elektriciteit", annual_energy_by_category(df, ELECTRICITY_SUPPLY_CATEGORIES))
    with c_gen2:
        render_monthly_stacked_bar_chart("Herkomst elektriciteit per maand", monthly_energy_by_category(df, ELECTRICITY_SUPPLY_CATEGORIES))
    render_load_match_balance_charts(df)

    st.markdown("### 7. Warmte En Gasloosheid")
    heat_total = float(kpis.get("Jaarlijkse warmtevraag [kWhth]", 0.0) or 0.0)
    gas_heat = annual_sum(df, "Q_boiler_th_kWth") + annual_sum(df, "Q_wkk_used_kWth")
    gasless_share = None if heat_total <= 0 else max(0.0, 100.0 * (1.0 - gas_heat / heat_total))
    render_kpi_row(
        [
            ("Warmtevraag", heat_total, "kWhth", 0),
            ("Ongedekte warmte", kpis.get("Jaarlijkse ongedekte warmte [kWhth]"), "kWhth", 0),
            ("Warmtepomp elektriciteit", kpis.get("Jaarverbruik warmtepomp elektriciteit [kWh]"), "kWh", 0),
            ("Indicatie gasloos geleverd", gasless_share, "%", 1),
        ]
    )
    render_monthly_stacked_bar_chart("Warmtebalans per maand", monthly_energy_by_category(df, HEAT_SUPPLY_CATEGORIES), unit="kWhth")
    render_heat_week_interactive(df)
    render_peak_gas_week_interactive(df)

    st.markdown("### 8. Opslag En Flexibiliteit")
    render_kpi_row(
        [
            ("Piekreductie batterij", kpis.get("Piekverlaging door batterij [kW]"), "kW", 1),
            ("Batterij laden", kpis.get("Jaarlijks laden batterij [kWh]"), "kWh", 0),
            ("Batterij ontladen", kpis.get("Jaarlijks ontladen batterij [kWh]"), "kWh", 0),
            ("Teruglevering", kpis.get("Jaarlijkse teruglevering [kWh]"), "kWh", 0),
        ]
    )
    storage_monthly = monthly_energy_by_category(df, STORAGE_CATEGORIES)
    if not storage_monthly.empty:
        render_monthly_stacked_bar_chart("Opslagstromen per maand", storage_monthly)
    if "battery_soc_pct" in df.columns:
        worst_week_idx = find_worst_grid_week(df)
        if len(worst_week_idx) > 0:
            render_timeseries_plot(df.loc[worst_week_idx], ["battery_soc_pct"], "Batterijvulling in zwaarste netweek", y_title="Vullingsgraad [%]", explanation_key="battery_soc")

    st.markdown("### 9. Modelkwaliteit En Details")
    render_model_quality_section(df)
    with st.expander("Samenvatting voor consultant", expanded=False):
        st.json(consultant_summary(df, contract))
    with st.expander("Resultaatdata bekijken", expanded=False):
        st.dataframe(_format_nl_dataframe(df.head(200)))

    export_zip = build_export_bundle(
        df,
        measurement_metadata=st.session_state.get("last_measurement_metadata"),
        validation_result=st.session_state.get("last_validation_result"),
    )
    c_export1, c_export2, c_export3 = st.columns(3)
    with c_export1:
        st.download_button(
            "Download resultaten als CSV",
            df.to_csv().encode("utf-8"),
            file_name="energy_system_results.csv",
            mime="text/csv",
            help="Wat: downloadt de resultaatreeks. In het model verandert dit niets. Effect: je kunt de berekening buiten de app analyseren.",
        )
    with c_export2:
        st.download_button(
            "Download exportpakket (.zip)",
            export_zip,
            file_name="energy_system_export_bundle.zip",
            mime="application/zip",
            help="Wat: downloadt resultaten en validatie-informatie samen. In het model verandert dit niets. Effect: handig voor rapportage of overdracht.",
        )
    with c_export3:
        st.download_button(
            "Download resultatenrapport",
            build_results_report_pdf(df, contract),
            file_name="resultatenrapport_energieplanner.pdf",
            mime="application/pdf",
            help="Wat: downloadt een PDF-rapportversie van de resultatenpagina. In het model verandert dit niets. Effect: geschikt voor delen, printen of klantbespreking.",
        )



def get_building_overrides():
    if not st.session_state.get("bld_enable", False):
        return None

    out = {
        "t_heat_set_occ_C": float(st.session_state["bld_t_heat_occ"]),
        "t_heat_set_unocc_C": float(st.session_state["bld_t_heat_unocc"]),
        "t_cool_set_occ_C": float(st.session_state["bld_t_cool_occ"]),
        "t_cool_set_unocc_C": float(st.session_state["bld_t_cool_unocc"]),
        "eta_wtw": float(st.session_state["bld_eta_wtw"]),
        "qv10_m3ph_per_m2": float(st.session_state["bld_qv10"]),
        "g_value": float(st.session_state["bld_g_value"]),
        "shading_factor": float(st.session_state["bld_shading_factor"]),
    }

    if st.session_state.get("bld_sched_enable", False):
        out["occupancy_schedule"] = WeeklySchedule(
            days_active=tuple(DAY_TO_INT[d] for d in st.session_state.get("bld_sched_days", ["Mon", "Tue", "Wed", "Thu", "Fri"])),
            start_hour=int(st.session_state.get("bld_sched_start", 8)),
            end_hour=int(st.session_state.get("bld_sched_end", 18)),
        )

    return out


def get_pelektro_overrides():
    if not st.session_state.get("pe_enable", False):
        return None
    return {
        "p_occ_W_per_m2": float(st.session_state["pe_occ"]),
        "p_unocc_W_per_m2": float(st.session_state["pe_unocc"]),
    }


def get_pprocess_overrides():
    if not st.session_state.get("pr_enable", False):
        return None
    return {
        "p_process_kW": float(st.session_state["pr_pp"]),
        "p_idle_kW": float(st.session_state["pr_pi"]),
    }


def get_pmobility_overrides():
    cap = float(st.session_state["mob_site_cap"])
    return {
        "n_cars": int(st.session_state["mob_n_cars"]),
        "p_charger_max_kW": float(st.session_state["mob_p_charger_max"]),
        "duty_cycle": float(st.session_state["mob_duty_cycle"]),
        "p_site_cap_kW": None if cap <= 0 else cap,
        "charging_schedule": WeeklySchedule(
            days_active=(0, 1, 2, 3, 4),
            start_hour=int(st.session_state["mob_arrival_hour"]),
            end_hour=int(st.session_state["mob_departure_hour"]),
        ),
        "battery_capacity_kWh": float(st.session_state["mob_battery_capacity"]),
        "arrival_soc_pct": float(st.session_state["mob_arrival_soc"]),
        "target_departure_soc_pct": float(st.session_state["mob_target_soc"]),
        "cars_present_fraction": float(st.session_state["mob_cars_present"]) / 100.0,
        "charge_mode": str(st.session_state["mob_charge_mode"]),
    }


def get_poverig_overrides():
    if not st.session_state.get("ov_enable", False):
        return None
    return {
        "p_occ_W_per_m2": float(st.session_state["ov_occ"]),
        "p_unocc_W_per_m2": float(st.session_state["ov_unocc"]),
    }


def build_cfg():
    pv_site_cap = None if float(st.session_state["pv_site_cap"]) <= 0 else float(st.session_state["pv_site_cap"])
    pv_direction = st.session_state.get("pv_azimuth", 180.0)
    pv_is_east_west = str(pv_direction) == PV_EAST_WEST_OPTION
    return make_default_load_config(
        building_type=BuildingType(st.session_state["def_building_type"]),
        year_class=YearClass(st.session_state["def_year_class"]),
        orientation=Orientation8(st.session_state["def_orientation"]),
        bvo_m2=float(st.session_state["def_bvo"]),
        floors=int(st.session_state["def_floors"]),
        window_to_wall_ratio=float(st.session_state["def_wwr"]),
        shape_factor=current_shape_factor(),
        building_overrides=get_building_overrides(),
        pelektro_overrides=get_pelektro_overrides(),
        pprocess_overrides=get_pprocess_overrides(),
        pmobility_overrides=get_pmobility_overrides(),
        poverig_overrides=get_poverig_overrides(),
        pv_overrides={
            "enabled": bool(st.session_state["pv_enabled"]),
            "installed_capacity_kWp": float(st.session_state["pv_cap"]),
            "tilt_deg": float(st.session_state["pv_tilt"]),
            "azimuth_deg": 180.0 if pv_is_east_west else float(pv_direction),
            "orientation_mode": "east_west" if pv_is_east_west else "single",
            "export_mode": "no_export" if bool(st.session_state.get("pv_no_export", False)) else "allow_export",
            "east_west_split": 0.5,
            "performance_ratio": float(st.session_state["pv_pr"]),
            "inverter_efficiency": float(st.session_state["pv_inv_eff"]),
            "temp_coeff_per_C": float(st.session_state["pv_temp_coeff"]),
            "site_cap_kW": pv_site_cap,
        },
        wkk_overrides={
            "enabled": bool(st.session_state["wkk_enabled"]),
            "p_rated_el_kW": float(st.session_state["wkk_p_rated"]),
            "min_load_fraction": float(st.session_state["wkk_min_frac"]),
            "electrical_efficiency": float(st.session_state["wkk_el_eff"]),
            "thermal_efficiency": float(st.session_state["wkk_th_eff"]),
            "dispatch_mode": str(st.session_state["wkk_dispatch_mode"]),
        },
        battery_overrides={
            "enabled": bool(st.session_state["bat_enabled"]),
            "capacity_kWh": float(st.session_state["bat_capacity"]),
            "p_charge_max_kW": float(st.session_state["bat_p_charge"]),
            "p_discharge_max_kW": float(st.session_state["bat_p_discharge"]),
            "efficiency_roundtrip": float(st.session_state["bat_eff"]),
            "soc_init_fraction": float(st.session_state["bat_soc_init"]) / 100.0,
            "soc_min_fraction": float(st.session_state["bat_soc_min"]) / 100.0,
            "soc_max_fraction": float(st.session_state["bat_soc_max"]) / 100.0,
            "dispatch_mode": "self_consumption",
            "charge_strategy": str(st.session_state["bat_charge_strategy"]),
        },
        heat_pump_overrides={
            "enabled": bool(st.session_state["hp_enabled"]),
            "capacity_kWth": float(st.session_state["hp_capacity"]),
            "cop_mode": str(st.session_state["hp_cop_mode"]),
            "cop_nominal": float(st.session_state["hp_cop_nominal"]),
            "min_part_load_fraction": float(st.session_state["hp_min_frac"]),
            "site_cap_electric_kW": None if float(st.session_state["hp_site_cap"]) <= 0 else float(st.session_state["hp_site_cap"]),
        },
        boiler_overrides={
            "enabled": bool(st.session_state["boiler_enabled"]),
            "capacity_kWth": float(st.session_state["boiler_capacity"]),
            "thermal_efficiency": float(st.session_state["boiler_eff"]),
            "min_part_load_fraction": float(st.session_state["boiler_min_frac"]),
            "fuel_type": str(st.session_state["boiler_fuel_type"]),
        },
        district_heat_overrides={
            "enabled": bool(st.session_state["dh_enabled"]),
            "capacity_kWth": float(st.session_state["dh_capacity"]),
            "tariff_placeholder": max(float(st.session_state["dh_tariff"]), 0.0),
        },
        heat_system_overrides={
            "heating_dispatch_mode": str(st.session_state["heat_dispatch_mode"]),
            "wkk_dispatch_mode": str(st.session_state["wkk_dispatch_mode"]),
            "thermal_storage_strategy": str(st.session_state["thermal_storage_strategy"]),
            "source_priority_mode": str(st.session_state["heat_source_priority_mode"]),
            "reference_heating_enabled": bool(st.session_state["ref_heat_enabled"]),
            "reference_cop_heat_by_season": {
                "winter": float(st.session_state["ref_cop_winter"]),
                "spring": float(st.session_state["ref_cop_spring"]),
                "summer": float(st.session_state["ref_cop_summer"]),
                "autumn": float(st.session_state["ref_cop_autumn"]),
            },
            "reference_eer_cool_by_season": {
                "winter": float(st.session_state["ref_eer_winter"]),
                "spring": float(st.session_state["ref_eer_spring"]),
                "summer": float(st.session_state["ref_eer_summer"]),
                "autumn": float(st.session_state["ref_eer_autumn"]),
            },
            "shared_grid_contract_cap": True,
        },
        measurement_overrides={
            "enabled": bool(st.session_state["measurement_enabled"]),
            "time_resolution": str(st.session_state["measurement_time_resolution"]),
            "expected_resolution": str(st.session_state["measurement_expected_resolution"]),
            "timezone": str(st.session_state["measurement_timezone"]),
            "power_unit_mode": str(st.session_state["measurement_power_unit_mode"]),
            "resample_policy": str(st.session_state["measurement_resample_policy"]),
            "gap_fill_method": str(st.session_state["measurement_gap_fill_method"]),
            "comparison_mode": str(st.session_state["measurement_comparison_mode"]),
        },
        evaluation_overrides={
            "grid_contract_kW": float(st.session_state["grid_cap_kW"]),
            "peak_percentiles": (
                float(st.session_state["evaluation_peak_p1"]),
                float(st.session_state["evaluation_peak_p2"]),
            ),
            "calibration_metrics_enabled": bool(st.session_state["evaluation_calibration_metrics_enabled"]),
            "max_exceedance_duration_h": float(st.session_state["evaluation_max_exceedance_duration_h"]),
            "max_exceedance_energy_kWh": float(st.session_state["evaluation_max_exceedance_energy_kWh"]),
            "robust_green_margin_fraction": float(st.session_state["evaluation_robust_green_margin_fraction"]),
        },
        thermal_storage_overrides={
            "enabled": bool(st.session_state["th_enabled"]),
            "capacity_kWh_th": float(st.session_state["th_capacity"]),
            "p_charge_max_kW": float(st.session_state["th_p_charge"]),
            "p_discharge_max_kW": float(st.session_state["th_p_discharge"]),
            "loss_factor_per_hour": float(st.session_state["th_loss"]),
            "soc_init_fraction": float(st.session_state["th_soc_init"]) / 100.0,
            "soc_min_fraction": float(st.session_state["th_soc_min"]) / 100.0,
            "soc_max_fraction": float(st.session_state["th_soc_max"]) / 100.0,
            "efficiency_charge": float(st.session_state["th_eff_charge"]),
            "efficiency_discharge": float(st.session_state["th_eff_discharge"]),
        },
        )


MODEL_OVERVIEW_ROWS = [
    ("1", "Weerdata en tijdindex", "Simulatie-index met temperatuur, globale zoninstraling en eventueel wind."),
    ("2", "Gebouwmodel", "Thermische warmtevraag Q_heat_kWth en koelvraag Q_cool_kWth."),
    ("3", "Gebruiksmodellen", "Elektrische basislast, processen, mobiliteitsladen en overig verbruik."),
    ("4", "Lokale opwek", "PV-elektriciteit en WKK-elektriciteit plus WKK-warmte."),
    ("5", "Warmteketen", "Invulling van warmtevraag door WKK, warmteopslag, warmtepomp, ketel, warmtenet en referentievoorziening."),
    ("6", "Opslag", "Warmteopslag voor warmteoverschot/tekort en batterij voor elektrische restvraag of overschot."),
    ("7", "Netbalans", "Netimport, teruglevering, contractoverschrijding en stoplichtbeoordeling."),
    ("8", "Validatie en modelchecks", "Controle op warmtebalans, negatieve fysica, capaciteitsgrenzen en vergelijking met meetdata."),
]


ENERGY_CARRIER_ROWS = [
    (
        "Thermische energie",
        "Warmtevraag en koelvraag worden als thermische vraag berekend.",
        "Warmtepomp, WKK-warmte, ketel, warmtenet, referentieverwarming en warmteopslag vullen deze vraag in.",
    ),
    (
        "Elektrische energie",
        "Elektrisch gebouwverbruik, processen, mobiliteit, koeling, warmtepompen, PV, WKK-elektriciteit, batterij en netimport bepalen samen de elektrische balans.",
        "Hiermee wordt zichtbaar of elektrificatie binnen de aansluiting past.",
    ),
    (
        "Brandstofenergie",
        "Brandstofstromen ontstaan vooral bij ketel en WKK.",
        "Deze worden apart bijgehouden om gasloosheid en resterend brandstofgebruik zichtbaar te maken.",
    ),
]


METHOD_SECTIONS = [
    {
        "title": "3.1 Weerdata en simulatie-index",
        "purpose": "De simulatie draait op de tijdstappen uit de aangeleverde weerdata. Dit voorkomt dat de app ongemerkt kunstmatige of geinterpoleerde weersituaties gebruikt.",
        "code_basis": "run_energy_system_simulation() bepaalt de index uit de weather DataFrame. Het gebouwmodel en PV-model eisen dezelfde DatetimeIndex; ontbrekende of dubbele timestamps worden niet in het model zelf gerepareerd.",
        "motivation": "Voor netpieken en PV-opbrengst is timing bepalend. Strikte indexcontrole is daarom belangrijker dan een schijnbaar vloeiende, maar mogelijk foutief aangevulde tijdreeks.",
        "method": [
            "De index wordt timezone-aware gemaakt als dat nodig is, met standaard Europe/Amsterdam.",
            "Het gebouwmodel vereist t_amb_C en controleert optioneel wind_ms en ghi_Wm2.",
            "PV vereist ghi_Wm2 en gebruikt t_amb_C als die beschikbaar is voor temperatuurcorrectie.",
            "Als index of verplichte kolommen niet exact kloppen, stopt het model met een foutmelding in plaats van stilzwijgend te interpoleren.",
        ],
        "latex": [],
        "outputs": "DatetimeIndex, t_amb_C, ghi_Wm2, wind_ms",
    },
    {
        "title": "3.2 Gebouwmodel: thermische warmtevraag en koelvraag",
        "purpose": "Het gebouwmodel berekent hoeveel warmte of koeling het gebouw thermisch nodig heeft. Het model bepaalt dus de vraag, niet welke installatie die vraag levert.",
        "code_basis": "simulate_thermal_demand() in gebouwmodel.py berekent Q_heat_kWth en Q_cool_kWth uit buitentemperatuur, setpoints, gebouwschil, ventilatie, infiltratie, interne warmte en zonnewinsten.",
        "motivation": "Dit is een transparant eerste-orde gebouwmodel. Het volgt de bouwfysische logica van warmtebalansen, maar vermijdt de complexiteit van een volledig dynamisch zone- of installatiemodel. Dat past bij een consultants-tool waarin invoer snel moet kunnen worden aangepast.",
        "method": [
            "Per tijdstap wordt bepaald of het gebouw in gebruik is op basis van dagen en gebruiksuren.",
            "Tijdens en buiten gebruik kunnen aparte verwarmings- en koelsetpoints gelden.",
            "Een deadband voorkomt tegelijk verwarmen en koelen rond de setpoints.",
            "Transmissieverlies wordt berekend met UA, opgebouwd uit U-waarden en oppervlakken van gevel, dak, vloer en glas.",
            "Ventilatie- en infiltratiestromen worden omgerekend naar voelbare warmtestroom met luchtdebiet, luchtdichtheid en soortelijke warmte.",
            "Interne warmtelast en zoninstraling via glas worden als winsten meegenomen. Bij verwarming verlagen ze de vraag; bij koeling verhogen ze de vraag.",
        ],
        "latex": [
            r"UA = U_{wall}A_{wall}+U_{roof}A_{roof}+U_{ground}A_{ground}+U_{window}A_{window}",
            r"Q_{air} = \rho_{air}c_p\frac{\dot V}{3600}\Delta T",
            r"Q_{solar}=GHI\cdot f_{solar}\cdot f_{orientation}\cdot A_{window}\cdot g\cdot f_{shading}",
            r"Q_{heat}=\max(Q_{trans}+Q_{vent}+Q_{inf}-Q_{internal}-Q_{solar},0)",
            r"Q_{cool}=\max(Q_{internal}+Q_{solar}+Q_{trans}+Q_{vent}+Q_{inf},0)",
        ],
        "outputs": "Q_heat_kWth, Q_cool_kWth, regime_heat, regime_cool",
    },
    {
        "title": "3.3 Elektrisch verbruik, processen en overig gebruik",
        "purpose": "Deze deelmodellen maken het reguliere elektrische gebruik zichtbaar los van warmte, opwek en opslag. Daardoor kan de gebruiker zien welke gebruikers bijdragen aan de basislast en pieken.",
        "code_basis": "pelektro.py, pprocess.py en poverig.py gebruiken eenvoudige weekroosters. Elektrisch en overig gebruik werken met W/m2; processen werken met kW per proces of een standaard proces-/idle-vermogen.",
        "motivation": "Een rooster-gebaseerd model is bewust gekozen omdat consultants vaak wel bedrijfsuren, oppervlak en grove vermogens kennen, maar niet altijd detailmetingen per apparaat hebben. Subloads maken verfijning mogelijk zodra meer informatie beschikbaar is.",
        "method": [
            "Zonder subloads gebruikt het model een bezet/niet-bezet vermogen over het gehele bruto vloeroppervlak.",
            "Met subloads wordt elk elektrisch of procesonderdeel apart berekend en daarna opgeteld.",
            "Processen hebben een actief vermogen en een idle-vermogen.",
            "Alle negatieve vermogens worden geweigerd, omdat passieve verbruikers geen opwek mogen worden.",
        ],
        "latex": [
            r"P_{electric}(t)=\frac{p_{occ/unocc}(t)\cdot BVO}{1000}",
            r"P_{process}(t)=\sum_k P_{process,k}(t)",
            r"P_{base,electric}=P_{ref,heat}+P_{cooling}+P_{elektro}+P_{process}+P_{mobility}+P_{overig}",
        ],
        "outputs": "P_elektro_kW, P_process_kW, P_overig_kW, P_electric_base_load_kW",
    },
    {
        "title": "3.4 Mobiliteit: elektrische voertuigen en slim laden",
        "purpose": "Het mobiliteitsmodel vertaalt het aantal aanwezige elektrische auto's naar een dagelijkse laadenergie en een laadprofiel. Daarmee wordt mobiliteit een expliciete elektriciteitsvraag in plaats van een constante kantoorurenlast.",
        "code_basis": "pmobiliteit.py gebruikt aantal auto's, laadvermogen, accucapaciteit, aankomst-SoC, gewenste vertrek-SoC, aanwezigheid, laadvenster, locatiecap en laadmodus.",
        "motivation": "De keuze voor een deterministisch energiebehoefte-model houdt de invoer begrijpelijk en voorkomt dat mobiliteit onrealistisch als constante last wordt behandeld. Slim laden sluit aan op het doel van de app: functioneren binnen een beperkte netaansluiting.",
        "method": [
            "De benodigde energie per auto is het verschil tussen gewenste vertrek-SoC en aankomst-SoC maal de gemiddelde accucapaciteit.",
            "De dagenergie is energie per auto maal het aantal aanwezige auto's.",
            "Direct laden vult de vraag vanaf aankomst zo snel mogelijk binnen laadvermogen en locatiecap.",
            "Slim laden bepaalt per tijdstap contractruimte als grid_cap - basislast en verdeelt de dagenergie over beschikbare ruimte.",
            "Als er onvoldoende contractruimte is, registreert het model niet-geladen mobiliteitsenergie.",
        ],
        "latex": [
            r"E_{car}=C_{battery}\frac{\max(SoC_{departure}-SoC_{arrival},0)}{100}",
            r"E_{day}=E_{car}\cdot n_{cars}\cdot f_{cars,present}",
            r"P_{smart,allowed}(t)=\min(P_{site,cap}, n_{present}P_{charger}, \max(P_{contract}-P_{base}(t),0))",
        ],
        "outputs": "P_mobility_kW, E_mobility_charged_kWh, E_mobility_unserved_kWh",
    },
    {
        "title": "3.5 Zonnepanelen",
        "purpose": "Het PV-model berekent lokaal elektrisch vermogen uit globale zoninstraling, opgesteld vermogen, orientatie, helling, performance ratio, omvormerrendement en temperatuurcorrectie.",
        "code_basis": "simulate_pv() in pv.py gebruikt ghi_Wm2, optioneel t_amb_C, installed_capacity_kWp, azimuth_deg, tilt_deg, performance_ratio, inverter_efficiency, temp_coeff_per_C en optioneel site_cap_kW.",
        "motivation": "Dit is een vereenvoudigd PV-proxy model, geinspireerd door de PVWatts-benadering waarin instraling, temperatuur en systeemverliezen centraal staan. Het is gekozen omdat het weinig invoer vraagt en het effect van richting en seizoenen begrijpelijk maakt.",
        "method": [
            "Globale horizontale instraling wordt genormaliseerd op 1000 W/m2 en begrensd.",
            "Orientatie wordt als factor tussen 0.6 en 1.0 toegepast, met zuid als referentie.",
            "Helling wordt als eenvoudige factor toegepast, met 35 graden als referentie.",
            "Celtemperatuur wordt benaderd als buitentemperatuur plus 0.03 maal GHI.",
            "Het vermogen wordt begrensd op een eventuele locatiecap en negatieve waarden worden verwijderd.",
        ],
        "latex": [
            r"f_{irr}=\mathrm{clip}(GHI/1000,0,1.5)",
            r"f_{orientation}=\mathrm{clip}(1-0.4\cdot \Delta_{south}/180,0.6,1.0)",
            r"f_{tilt}=\mathrm{clip}(1-|tilt-35|/120,0.75,1.05)",
            r"T_{cell}=T_{amb}+0.03\cdot GHI",
            r"P_{pv}=kWp\cdot f_{irr}\cdot f_{orientation}\cdot f_{tilt}\cdot PR\cdot \eta_{inv}\cdot f_{temp}",
        ],
        "outputs": "P_pv_kW, pv_irr_factor, pv_temp_factor",
    },
    {
        "title": "3.6 WKK: gecombineerde warmte en elektriciteit",
        "purpose": "De WKK levert tegelijk elektriciteit en warmte uit brandstof. Het model laat daardoor zien of WKK netimport kan verlagen, warmtevraag kan dekken of juist onbenutte warmte produceert.",
        "code_basis": "dispatch_wkk() ondersteunt elektriciteitsgestuurd, warmtevraaggestuurd, hybride piekverlaging, warmtevraag met elektrische cap, must-run en uitgeschakeld.",
        "motivation": "WKK is meegenomen omdat het in bestaande gebouwen vaak relevant is als overgangs- of piekoplossing. Door warmte en elektriciteit tegelijk te boeken wordt zichtbaar of een WKK energetisch nuttig is of vooral overschotten veroorzaakt.",
        "method": [
            "Het gekozen dispatchprofiel bepaalt het elektrische doelvermogen.",
            "Bij warmtevraaggestuurde dispatch wordt warmtevraag omgerekend naar het elektrische niveau dat nodig is om die warmte te leveren.",
            "Het vermogen wordt begrensd door nominaal WKK-vermogen en minimale deellast.",
            "Brandstofinput volgt uit elektrisch rendement; warmteproductie volgt uit thermisch rendement.",
            "Warmte wordt gebruikt tot de actuele warmtevraag; overschot wordt als gedumpte WKK-warmte geregistreerd.",
        ],
        "latex": [
            r"P_{required,heat}=Q_{heat,demand}\frac{\eta_{el}}{\eta_{th}}",
            r"F_{wkk}=\frac{P_{wkk,el}}{\eta_{el}}",
            r"Q_{wkk,available}=F_{wkk}\eta_{th}",
            r"Q_{wkk,used}=\min(Q_{wkk,available},Q_{heat,demand})",
            r"Q_{wkk,dumped}=\max(Q_{wkk,available}-Q_{wkk,used},0)",
        ],
        "outputs": "P_wkk_el_kW, Q_wkk_used_kWth, Q_wkk_dumped_kWth, F_wkk_fuel_kW",
    },
    {
        "title": "3.7 Warmteketen: warmtepomp, ketel, warmtenet en referentie",
        "purpose": "De warmteketen vult resterende warmtevraag in nadat WKK-warmte en warmteopslag zijn toegepast. Hiermee wordt expliciet zichtbaar welke warmtebron de vraag dekt en hoeveel elektriciteit of brandstof daarvoor nodig is.",
        "code_basis": "total.py stuurt de volgorde aan. dispatch_heat_pump(), dispatch_boiler() en dispatch_district_heat() leveren elk hun deel van de resterende warmtevraag. Een referentie-elektrische verwarming kan overblijvende vraag via COP invullen.",
        "motivation": "De splitsing tussen gebouwvraag en installatie-invulling voorkomt dubbele COP/EER-logica. Dit is inhoudelijk belangrijk voor gasloosheidsanalyse: een gebouw heeft warmtevraag, maar de gekozen installatie bepaalt of die vraag elektrisch, via brandstof of via warmtenet wordt geleverd.",
        "method": [
            "De warmtepomp levert maximaal de ingestelde thermische capaciteit en gebruikt COP om elektriciteit te berekenen.",
            "COP kan vast, seizoensafhankelijk of weersafhankelijk zijn. De weersafhankelijke COP stijgt bij mildere buitentemperatuur en daalt bij kou.",
            "Als de warmtepomp gedeeld is met het contractvermogen, beperkt de beschikbare netruimte het elektrische warmtepompvermogen.",
            "De ketel dekt resterende warmtevraag binnen thermische capaciteit en rendement; gasinput wordt alleen geboekt bij brandstoftype gas.",
            "Warmtenet dekt resterende warmtevraag binnen capaciteit zonder lokale brandstofinput.",
            "Referentie-elektrische verwarming vult eventueel resterende warmtevraag in via seizoens-COP, zodat scenario's zonder expliciete warmtebron toch sluitend kunnen worden doorgerekend.",
        ],
        "latex": [
            r"COP_{weather}=\max(COP_{nominal}+0.06(T_{amb}-7),1.0)",
            r"P_{hp,el}=\frac{Q_{hp,th}}{COP}",
            r"Q_{hp,th}=\min(Q_{remaining},Q_{hp,capacity},COP\cdot P_{grid,headroom})",
            r"F_{boiler}=\frac{Q_{boiler,th}}{\eta_{boiler}}",
            r"P_{reference,heat,el}=\frac{Q_{unserved,final}}{COP_{reference}}",
        ],
        "outputs": "Q_hp_th_kWth, P_hp_el_kW, Q_boiler_th_kWth, Q_dh_th_kWth, P_heat_ref_el_kW",
    },
    {
        "title": "3.8 Warmteopslag",
        "purpose": "Warmteopslag vangt warmteoverschot op, vooral WKK-warmte die op dat moment niet direct kan worden gebruikt, en levert later warmte aan resterende vraag.",
        "code_basis": "simulate_thermal_storage() gebruikt capaciteit, laad-/ontlaadvermogen, minimale/initiele/maximale SoC, laad-/ontlaadrendement en stilstandsverlies.",
        "motivation": "Een SoC-model is nodig omdat warmteopslag tijdsafhankelijk is: een overschot in de ochtend kan alleen later worden gebruikt als er capaciteit, rendement en voldoende resterende opslagenergie beschikbaar zijn.",
        "method": [
            "Per tijdstap wordt eerst stilstandsverlies van de opgeslagen energie afgehaald.",
            "Daarna laadt de opslag uit thermisch overschot binnen vermogen, rendement en vrije capaciteit.",
            "Vervolgens ontlaadt de opslag naar resterende warmtevraag binnen vermogen, rendement en beschikbare energie boven minimale SoC.",
            "Overschot dat niet kan worden opgeslagen blijft als warmteoverschot zichtbaar; vraag die niet kan worden geleverd blijft ongedekt voor volgende warmtebronnen.",
        ],
        "latex": [
            r"E_{loss}=E_{storage}\cdot f_{loss,hour}\cdot dt",
            r"Q_{charge}=\min(Q_{surplus},P_{charge,max},\frac{free\ capacity}{\eta_{charge}dt})",
            r"Q_{discharge}=\min(Q_{deficit},P_{discharge,max},\frac{available\ energy\cdot \eta_{discharge}}{dt})",
            r"E_{next}=E-E_{loss}+Q_{charge}\eta_{charge}dt-\frac{Q_{discharge}}{\eta_{discharge}}dt",
        ],
        "outputs": "Q_thermal_storage_charge_kWth, Q_thermal_storage_discharge_kWth, E_thermal_storage_kWhth",
    },
    {
        "title": "3.9 Batterij",
        "purpose": "De batterij verschuift elektrische energie in de tijd. In de huidige code is de batterij geen economische optimizer, maar een regelgebaseerd zelfconsumptie- en piekreductiemodel.",
        "code_basis": "simulate_battery() gebruikt P_residual_before_battery_kW, capaciteit, laad-/ontlaadvermogen, SoC-grenzen, roundtrip efficiency en laadstrategie.",
        "motivation": "Regelgebaseerde batterijlogica is transparant en past bij het doel om snel te zien wat opslag doet voor netpieken en lokale benutting. Voor financiele optimalisatie of prijsarbitrage zou later een optimalisatiemodel nodig zijn.",
        "method": [
            "Het model splitst roundtrip efficiency symmetrisch over laden en ontladen via de wortel van het roundtriprendement.",
            "Bij positieve restvraag ontlaadt de batterij om netimport te verlagen, begrensd door ontlaadvermogen en beschikbare energie.",
            "Bij lokaal overschot kan de batterij laden volgens strategie 'alleen lokaal overschot'.",
            "Bij strategie 'laden tot contractruimte' mag de batterij ook uit het net laden zolang netto import onder contractvermogen blijft.",
            "SoC blijft tussen minimale en maximale fractie van de ingestelde capaciteit.",
        ],
        "latex": [
            r"\eta_{charge}=\eta_{discharge}=\sqrt{\eta_{roundtrip}}",
            r"P_{discharge}=\min(P_{residual},P_{discharge,max},\frac{available\ energy\cdot \eta_{discharge}}{dt})",
            r"P_{charge,surplus}=\min(-P_{residual},P_{charge,max},\frac{room}{\eta_{charge}dt})",
            r"P_{charge,headroom}=\min(P_{contract}-P_{residual},P_{charge,max},\frac{room}{\eta_{charge}dt})",
        ],
        "outputs": "P_battery_charge_kW, P_battery_discharge_kW, E_battery_kWh, battery_soc_pct",
    },
    {
        "title": "3.10 Elektrische netbalans en stoplicht",
        "purpose": "De netbalans vertaalt alle vraag, opwek en batterijstromen naar netimport, teruglevering en contractoverschrijding. Dit is het centrale resultaat voor de vraag of het gebouw binnen de netaansluiting past.",
        "code_basis": "total.py berekent de restbalans voor en na batterij. grid.py berekent pieken, jaarimport/export, percentielen, duurcurve, overschrijdingsuren en stoplichtstatus.",
        "motivation": "Piekvermogen, percentielen en duurcurves zijn praktischer voor netcapaciteit dan alleen jaarverbruik. Een korte overschrijding vraagt een andere maatregel dan een structureel tekort aan contractvermogen.",
        "method": [
            "Eerst wordt totale elektrische vraag bepaald inclusief warmtepomp en referentieverwarming.",
            "Daarna worden PV en WKK-elektriciteit afgetrokken.",
            "De batterij mag de restvraag verlagen of overschot opnemen.",
            "Positieve restbalans is netimport; negatieve restbalans is teruglevering.",
            "Het stoplicht vergelijkt piekimport, p99-import en overschrijdingsduur/-energie met het contractvermogen en ingestelde marges.",
        ],
        "latex": [
            r"P_{generation,total}=P_{pv}+P_{wkk,el}",
            r"P_{residual,after\ battery}=P_{residual,before\ battery}+P_{battery,charge}-P_{battery,discharge}",
            r"P_{contract,excess}=\max(P_{grid,import}-P_{contract},0)",
            r"load\ factor=\frac{annual\ grid\ import}{peak\ grid\ import\cdot hours_{year}}",
        ],
        "outputs": "P_grid_import_kW, P_grid_export_kW, P_grid_contract_excess_kW, grid_evaluation",
    },
    {
        "title": "3.11 Modelchecks en meetvalidatie",
        "purpose": "Modelchecks bewaken of de simulatie fysisch en administratief logisch blijft. Meetvalidatie vergelijkt modeluitkomsten met werkelijke data als die beschikbaar zijn.",
        "code_basis": "_compute_balance_checks() controleert warmtebalans, negatieve waarden en capaciteitsgrenzen. calibration.py lijnt meetdata en simulatie uit en berekent RMSE, MAE, MBE, NMBE, CV(RMSE), R2 en Pearson-correlatie.",
        "motivation": "De app is bedoeld voor besluitvorming. Daarom moet niet alleen het scenarioresultaat zichtbaar zijn, maar ook of de berekening intern klopt en hoe goed het model aansluit op eventuele meetdata.",
        "method": [
            "De warmtebalans vergelijkt warmtevraag met geleverde warmte, ongedekte warmte, opslagstromen en warmteoverschot.",
            "Niet-fysische negatieve waarden worden gecontroleerd voor onder andere warmtevraag, brandstofinput en netstromen.",
            "Capaciteitschecks vergelijken berekende vermogens met ingestelde grenzen van warmtepomp, WKK, ketel en warmtenet.",
            "Validatie kan worden uitgevoerd voor netimport, netexport, elektrische load, gas of warmte.",
            "Meetdata en simulatie kunnen naar uur-, dag- of maandniveau worden geaggregeerd.",
        ],
        "latex": [
            r"error=simulated-measured",
            r"RMSE=\sqrt{mean(error^2)}",
            r"NMBE=100\frac{mean(error)}{mean(measured)}",
            r"CV(RMSE)=100\frac{RMSE}{mean(measured)}",
        ],
        "outputs": "sanity_checks, grid_evaluation, validation metrics",
    },
]


ASSUMPTION_ROWS = [
    ("Een gebouw of locatie", "De simulatie kijkt naar een individueel gebouw of gebouwlocatie met een eigen vraag, opwek, opslag en netaansluiting.", "Resultaten zijn niet automatisch geldig voor een gebied, wijknet of collectief energiesysteem."),
    ("Tijdreeksmodel", "Alle energiestromen worden per tijdstap berekend op basis van de aangeleverde weerdata-index.", "Pieken, timing en seizoenen zijn leidend; jaarvolumes alleen zijn onvoldoende om netcapaciteit te beoordelen."),
    ("Deterministische simulatie", "Bij gelijke invoer geeft het model dezelfde uitkomst. Dispatchregels zijn vooraf gekozen.", "De app vindt niet vanzelf de economisch of technisch optimale configuratie."),
    ("Gescheiden energiedragers", "Thermische vraag, elektrische vraag en brandstofinput worden apart bijgehouden.", "Gasloosheid en netbelasting kunnen tegelijk worden beoordeeld zonder COP- of brandstofstromen te vermengen."),
    ("Vereenvoudigde fysica", "Gebouw, PV, warmtepomp, WKK en opslag zijn transparante benaderingen, geen detailmodellen.", "De uitkomst is geschikt voor verkenning en scenariovergelijking, niet als definitieve engineering-berekening."),
]


LIMITATION_ROWS = [
    ("Gebouwmodel", "Het gebouw wordt niet als volledig dynamisch thermisch massa-model gesimuleerd. Er is geen ruimtelijke zonering, geen uurlijkse regeling per ruimte en geen vochtbalans.", "Gebruik resultaten als indicatie van warmtevraag/koelvraag. Voor definitief comfort- of installatieontwerp blijft detailmodellering nodig."),
    ("Weerdata", "De code accepteert geen stille interpolatie binnen het gebouw- en PV-model; ontbrekende of foutieve weerdata blokkeren de simulatie.", "Dat verhoogt betrouwbaarheid, maar betekent dat invoerdata vooraf goed moeten worden opgeschoond."),
    ("Elektrische lasten", "Basislasten, processen en overig gebruik zijn rooster- en vermogen-gebaseerd. Gedragsvariatie, stochastiek en kortdurende startsstromen ontbreken.", "Piekvermogens kunnen onderschat worden als processen of apparaten in werkelijkheid kort en zwaar schakelen."),
    ("Mobiliteit", "Het EV-model gebruikt gemiddelde accucapaciteit, gemiddelde aankomst-/vertrek-SoC en aanwezigheid. Er is geen individueel voertuiggedrag.", "Het model is geschikt voor laadenergie en contractruimte, maar niet voor operationele laadpleinoptimalisatie."),
    ("PV", "Het PV-model gebruikt een vereenvoudigde GHI-proxy met orientatie-, helling-, performance- en temperatuurfactoren. Er is geen schaduw-, horizon- of POA-transpositiemodel.", "PV-opbrengst is bruikbaar voor scenariovergelijking; bij investeringsbesluiten moet een gespecialiseerde PV-studie volgen."),
    ("WKK", "WKK-dispatch volgt regelkeuzes zoals elektriciteitsvraag, warmtevraag of hybride piekverlaging. Start/stopkosten, onderhoud en emissies worden niet geoptimaliseerd.", "Resultaten tonen energetische inzet en overschot, niet automatisch economische haalbaarheid."),
    ("Warmtepomp", "COP is vast, seizoensafhankelijk of lineair weersafhankelijk. Aanvoertemperatuur, bronregime, defrost, deellastcurves en hydrauliek zijn niet expliciet gemodelleerd.", "Elektriciteitsvraag van warmte is indicatief. Voor selectie van een echte warmtepomp is leverancier-/ontwerpdata nodig."),
    ("Ketel en warmtenet", "Ketel en warmtenet leveren binnen capaciteit en rendement/capaciteit; er is geen gedetailleerde regeling, temperatuurtraject of tariefoptimalisatie.", "Deze modules zijn vooral bedoeld om resterende warmtevraag en brandstof-/warmtenetafhankelijkheid zichtbaar te maken."),
    ("Opslag", "Batterij en warmteopslag volgen SoC-, vermogen- en rendementsregels, maar geen marktprijsoptimalisatie of voorspellende regeling.", "Opslagresultaten tonen technische flexibiliteit en piekreductie, niet automatisch de beste businesscase."),
    ("Netbeoordeling", "Het stoplicht beoordeelt de gebouwzijdige netimport ten opzichte van contractvermogen. Netkwaliteit, spanningsval, congestiegebied en aansluitvoorwaarden van de netbeheerder zitten niet in het model.", "Een groen resultaat betekent energetisch passend binnen de ingestelde grens, geen formele netbeheerder-goedkeuring."),
]


INTERPRETATION_ROWS = [
    ("Piek netimport na batterij", "Hoogste elektrische import uit het net na lokale opwek en batterijdispatch.", "Vergelijk direct met contractvermogen. Dit is de belangrijkste netcapaciteits-KPI."),
    ("Piek boven contract", "Maximale overschrijding boven het ingestelde contractvermogen.", "Laat zien hoeveel piekreductie of extra contractruimte nodig is."),
    ("Uren boven contract", "Aantal uren waarin netimport boven contractvermogen ligt.", "Onderscheidt incidentele pieken van structureel tekort."),
    ("Jaarlijkse netimport", "Totale elektriciteit uit het net over het jaar.", "Relevant voor energiegebruik, maar minder bepalend voor aansluitcapaciteit dan de piek."),
    ("Ongedekte warmte", "Warmtevraag die door geen warmtebron of referentievoorziening is geleverd.", "Moet voor een technisch sluitend verwarmingsscenario normaal nul of verklaarbaar zijn."),
    ("Gas-/brandstofinput", "Brandstof die door WKK en ketel wordt gebruikt.", "Bepaalt of een scenario werkelijk gasloos of brandstofarm is."),
]


LOAD_MATCH_ROWS = [
    ("Veel teruglevering midden op de dag", "Lokale opwek valt niet samen met lokale vraag of opslag is te klein/vol.", "Batterij, slim laden, procesverschuiving of andere PV-orientatie onderzoeken."),
    ("Hoge ochtend- of avondpiek", "Vraag ligt buiten PV-productieuren of laadt/processen starten tegelijk.", "Slim laden, starttijden spreiden, batterij ontladen op piekmomenten."),
    ("Hoge wintervraag", "Warmtepomp of referentieverwarming kan netpiek veroorzaken terwijl PV laag is.", "Warmteopslag, grotere warmtebron, lagere warmtevraag of hybride bron onderzoeken."),
    ("Laag eigengebruik van PV", "PV-opwek wordt relatief vaak geexporteerd.", "Opslag of vraagsturing kan waarde toevoegen; extra PV helpt niet altijd tegen netpiek."),
]


MODEL_CHECK_ROWS = [
    ("Warmtebalans", "Controleert of warmtevraag, geleverde warmte, opslag, overschot en ongedekte warmte administratief sluiten.", "Controleer warmtebronnen, opslagstromen en of WKK-overschot verkeerd als residu wordt gelezen."),
    ("Negatieve fysica", "Controleert of niet-negatieve grootheden zoals brandstofinput, netimport en warmtevraag niet onder nul komen.", "Controleer invoerwaarden, projectbestand en eventuele ontbrekende kolommen."),
    ("Vermogensgrenzen", "Controleert of installaties boven ingestelde capaciteit leveren.", "Controleer capaciteit, deellastinstellingen en dispatchvolgorde."),
    ("Validatie met meetdata", "Vergelijkt model en meting met foutmaten zoals RMSE, NMBE en CV(RMSE).", "Kalibreer basislasten, gebruiksuren, processen of warmte-instellingen voordat scenario's worden beoordeeld."),
]


def render_latex_formula_block(formulas: list[str]) -> None:
    for formula in formulas:
        st.latex(formula)


def render_compact_table(rows: list[tuple[str, str, str]], columns: tuple[str, str, str]) -> None:
    st.dataframe(
        pd.DataFrame(rows, columns=list(columns)),
        hide_index=True,
        width="stretch",
    )


def render_methodology_tab() -> None:
    st.markdown("### Methode & Uitleg")
    st.caption(
        "Deze sectie beschrijft de volledige methode van de app. Interne stukken uit het Word-document, zoals het "
        "implementatieplan en open punten, zijn hier weggelaten; de inhoud hieronder gaat alleen over modeldoel, "
        "rekenstructuur, deelmodellen, aannames, beperkingen en interpretatie."
    )

    c_doc, c_scope = st.columns([1, 2])
    with c_doc:
        if METHOD_DOCX_PATH.exists():
            st.download_button(
                "Download methodedocument",
                METHOD_DOCX_PATH.read_bytes(),
                file_name="methode_energieplanner.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                help="Downloadt de volledige wetenschappelijke methodebeschrijving als Word-bestand.",
            )
        else:
            st.info("Methodedocument is nog niet beschikbaar.")
    with c_scope:
        st.write(
            "De methodepagina is bedoeld als inhoudelijke referentie voor consultants. Iemand moet hiermee kunnen volgen "
            "waar vraag ontstaat, hoe installaties die vraag invullen, hoe opslag wordt ingezet en hoe uiteindelijk "
            "netimport, teruglevering, gas-/brandstofinput en modelchecks ontstaan."
        )

    m_goal, m_overview, m_models, m_assumptions, m_interpretation, m_sources = st.tabs(
        ["Doel", "Modeloverzicht", "Deelmodellen", "Aannames", "Interpretatie", "Bronnen"]
    )

    with m_goal:
        st.markdown("#### 1. Doel van het model")
        st.write(
            "De energieplanner heeft als doel om de energiestromen van een individueel gebouw inzichtelijk te maken. "
            "Het model splitst de energievraag en energielevering expliciet op in drie dragers: thermische energie, "
            "elektrische energie en brandstofenergie. Door deze dragers gescheiden te modelleren kan de gebruiker zien "
            "welke vraag uit het gebouw zelf komt, welke vraag elektrisch wordt ingevuld, welke warmtebronnen worden gebruikt "
            "en welk deel uiteindelijk nog via het elektriciteitsnet of via brandstof wordt geleverd."
        )
        st.write(
            "De app is daarmee primair bedoeld als scenariotool voor consultants. Een gebruiker kan instellingen aanpassen "
            "voor gebouwgebruik, elektrische lasten, processen, mobiliteit, zonnepanelen, WKK, warmtepompen, ketels, warmtenet, "
            "batterijen en warmteopslag. Vervolgens laat de simulatie zien hoe deze keuzes doorwerken in de totale energiebalans, "
            "de netbelasting, de warmtevoorziening, teruglevering, opslaggebruik en eventuele ongedekte warmte."
        )

        st.markdown("##### 1.1 Centrale ontwerpvraag")
        st.write(
            "De centrale ontwerpvraag is niet alleen hoeveel energie een gebouw per jaar gebruikt, maar vooral wanneer die energie "
            "nodig is en via welke drager die geleverd wordt. Dat onderscheid is essentieel voor twee praktische vraagstukken:"
        )
        st.markdown("- Kan een gebouw geheel of gedeeltelijk van het gas af zonder dat de warmtevraag ongedekt blijft?")
        st.markdown("- Kan een gebouw functioneren binnen een beperkte netaansluiting, eventueel met lokale opwek, opslag en slim laden?")
        st.write(
            "Daarom rekent het model niet alleen met jaarvolumes, maar met tijdreeksen. Pieken, gelijktijdigheid en seizoenspatronen "
            "zijn minstens zo belangrijk als het jaarlijkse totaal. Een gebouw kan op jaarbasis voldoende lokale opwek hebben, maar "
            "toch een netprobleem houden als vraag en opwek op andere momenten optreden."
        )

        st.markdown("##### 1.2 Energiedragers in het model")
        render_compact_table(ENERGY_CARRIER_ROWS, ("Energiedrager", "Wat wordt berekend", "Rol in de analyse"))

        st.markdown("##### 1.3 Hoe dit aansluit op de code")
        st.write(
            "In de code is deze opzet terug te zien in de totale simulatie. Eerst worden de gebouwgebonden vraag en elektrische lasten "
            "opgebouwd. Daarna worden PV en WKK toegevoegd. Vervolgens wordt de warmtevraag via WKK-warmte, warmteopslag, warmtepomp, "
            "ketel, warmtenet en eventueel referentie-elektrische verwarming afgehandeld. Tot slot wordt de elektrische balans bepaald "
            "met batterijgedrag en netimport/netexport."
        )
        st.markdown("- Gebouw en lasten leveren kolommen zoals warmtevraag, koelvraag, elektrisch basisverbruik, processen, mobiliteit en overig verbruik.")
        st.markdown("- Opwek levert PV-elektriciteit en WKK-elektriciteit; WKK kan daarnaast warmte leveren of onbenutte warmte veroorzaken.")
        st.markdown("- De warmteketen vult resterende warmtevraag stap voor stap in via opslag, warmtepomp, ketel, warmtenet en referentievoorziening.")
        st.markdown("- Opslag en net: batterijgedrag wordt toegepast op de resterende elektrische balans; daarna ontstaan netimport, teruglevering en contractoverschrijding.")
        st.markdown("- Resultaten tonen piek netimport, jaarverbruik, herkomst elektriciteit, warmtebalans, opslagstromen, gas-/brandstofinput en modelchecks.")

        st.markdown("##### 1.4 Bedoelde toepassing")
        st.write(
            "Het model is bedoeld voor verkennende en vergelijkende analyses. De gebruiker kan scenario's naast elkaar zetten en beoordelen "
            "welke maatregelen bijdragen aan minder gasgebruik, lagere netpieken, betere benutting van lokale opwek of minder ongedekte warmte. "
            "Voorbeelden zijn: meer of anders georienteerde zonnepanelen, een grotere warmtepomp, wel of geen WKK, batterijcapaciteit, warmteopslag "
            "of slim laden van elektrische voertuigen."
        )
        st.write(
            "De uitkomst moet worden gelezen als technisch-energetische ondersteuning bij besluitvorming. De app vervangt geen detailontwerp "
            "van installaties, geen kostenoptimalisatie en geen definitieve netstudie, maar helpt wel om vroeg in het proces te zien waar de "
            "belangrijkste knelpunten en oplossingsrichtingen zitten."
        )

        st.markdown("##### 1.5 Eerste afbakening")
        st.markdown("- Schaalniveau: het model kijkt naar een gebouw of gebouwlocatie, niet naar een volledig gebiedsenergiesysteem.")
        st.markdown("- Tijdsdimensie: de app werkt met tijdreeksen, zodat pieken en seizoenseffecten zichtbaar worden.")
        st.markdown("- Optimalisatie: de huidige logica simuleert gekozen instellingen en dispatchregels; het model kiest niet automatisch de economisch optimale configuratie.")
        st.markdown("- Installatiedetail: de app gebruikt vereenvoudigde technische modellen en is niet bedoeld als hydraulisch, bouwfysisch of elektrotechnisch detailontwerp.")
        st.markdown("- Interpretatie: resultaten zijn sterk afhankelijk van invoerkwaliteit, meetdata, weerdata en gekozen scenario-aannames.")

    with m_overview:
        st.markdown("#### 2. Modeloverzicht")
        st.write(
            "Het model bestaat uit een vaste rekenketen. De volgorde is belangrijk: eerst wordt bepaald welke vraag het gebouw en "
            "het gebruik veroorzaken, daarna welke lokale opwek en warmtebronnen beschikbaar zijn, vervolgens hoe opslag wordt "
            "ingezet en pas aan het einde wat er van of naar het elektriciteitsnet gaat. Daardoor blijft zichtbaar of een maatregel "
            "de vraag verlaagt, lokale opwek toevoegt, warmte invult, flexibiliteit levert of alleen de resterende netbalans verandert."
        )
        render_compact_table(MODEL_OVERVIEW_ROWS, ("Stap", "Rekenblok", "Belangrijkste uitkomst"))
        st.latex(r"\text{Vraag} \rightarrow \text{Opwek} \rightarrow \text{Warmteketen} \rightarrow \text{Opslag} \rightarrow \text{Netbalans}")
        render_latex_formula_block(
            [
                r"P_{load,total}=P_{base,electric}+P_{heat,pump,el}+P_{reference,heat,el}",
                r"P_{residual,before\ battery}=P_{load,total}-(P_{pv}+P_{wkk,el})",
                r"P_{grid,import}=\max(P_{residual,before\ battery}+P_{battery,charge}-P_{battery,discharge},0)",
                r"P_{grid,export}=\max(-(P_{residual,before\ battery}+P_{battery,charge}-P_{battery,discharge}),0)",
            ]
        )
        st.write(
            "In woorden: warmte en elektriciteit worden niet op een hoop gegooid. Het gebouw levert eerst thermische vraag; "
            "installaties bepalen daarna welke elektrische of brandstofinput nodig is om die thermische vraag te leveren. "
            "Deze scheiding is essentieel om gasloosheid en netcapaciteit tegelijk te kunnen beoordelen."
        )

    with m_models:
        st.markdown("#### 3. Deelmodellen")
        for section in METHOD_SECTIONS:
            with st.expander(section["title"], expanded=False):
                st.write(section["purpose"])
                c_code, c_reason = st.columns(2)
                with c_code:
                    st.markdown("**Aansluiting op code**")
                    st.write(section["code_basis"])
                    st.caption(f"Code-uitvoer: {section['outputs']}")
                with c_reason:
                    st.markdown("**Motivatie voor deze modellering**")
                    st.write(section["motivation"])
                st.markdown("**Rekenstappen**")
                for item in section["method"]:
                    st.markdown(f"- {item}")
                if section["latex"]:
                    st.markdown("**Rekenwijze in formulevorm**")
                    render_latex_formula_block(section["latex"])

    with m_assumptions:
        st.markdown("#### 4. Aannames en beperkingen")
        st.write(
            "De energieplanner is een technisch-energetisch scenariomodel. Dat betekent dat het model gekozen instellingen doorrekent "
            "en laat zien wat daarvan de gevolgen zijn voor energiestromen, netbelasting, warmtevoorziening en opslag. Het model is dus "
            "geen automatische optimizer, geen kostenmodel en geen definitief installatieontwerp. De onderstaande aannames en beperkingen "
            "zijn belangrijk bij het lezen van resultaten en bij het bespreken van scenario's met klanten."
        )
        st.markdown("##### 4.1 Algemene modelaannames")
        render_compact_table(ASSUMPTION_ROWS, ("Aanname", "Wat dit betekent", "Gevolg voor interpretatie"))
        st.markdown("##### 4.2 Beperkingen per modelonderdeel")
        render_compact_table(LIMITATION_ROWS, ("Onderdeel", "Belangrijkste beperking", "Praktische consequentie"))
        st.markdown("##### 4.3 Datakwaliteit en onzekerheid")
        st.write(
            "De kwaliteit van de uitkomst wordt sterk bepaald door de kwaliteit van de invoer. Vooral gebruiksuren, oppervlaktes, U-waarden, ventilatie, "
            "procesvermogens, laadgedrag, contractvermogen en weerdata hebben grote invloed op pieken en jaarvolumes. Als deze waarden onzeker zijn, "
            "moet het resultaat worden gelezen als bandbreedte. In de praktijk is het verstandig om ten minste een conservatief scenario, een verwacht "
            "scenario en een ambitieus scenario naast elkaar te zetten."
        )
        st.markdown("- Gebruik meetdata waar beschikbaar om basislast, gasverbruik en pieken te controleren.")
        st.markdown("- Controleer of de zwaarste netweek en zwaarste warmteweek logisch passen bij het bedrijfstype.")
        st.markdown("- Behandel ontbrekende technische gegevens expliciet als aannames in klantgesprekken.")
        st.markdown("- Gebruik modelchecks niet als formaliteit: een warmtebalansfout of capaciteitsoverschrijding kan wijzen op verkeerde interpretatie van een scenario.")

    with m_interpretation:
        st.markdown("#### 5. Interpretatie van resultaten")
        st.write(
            "De resultatenpagina moet worden gelezen als een technisch verhaal in vaste volgorde. Eerst: past het scenario binnen de netaansluiting? "
            "Daarna: waardoor ontstaan de pieken? Vervolgens: is de warmtevoorziening dekkend en gasloos? Tot slot: welke maatregel draagt het meest bij "
            "aan lagere netbelasting, minder brandstofgebruik of betere benutting van lokale opwek?"
        )
        st.markdown("##### 5.1 Beslissingssamenvatting en stoplicht")
        st.write(
            "Het stoplicht is een snelle beoordeling van de netbelasting ten opzichte van het ingestelde contractvermogen. Groen betekent dat piek en robuuste "
            "marge binnen de ingestelde grens blijven. Oranje betekent dat het scenario dicht op de grens zit of beperkt overschrijdt. Rood betekent dat de "
            "piekimport boven de toegestane grens komt en dat maatregelen of een andere aansluiting nodig zijn."
        )
        render_compact_table(INTERPRETATION_ROWS, ("KPI", "Wat het zegt", "Hoe te gebruiken"))

        st.markdown("##### 5.2 Netcapaciteit lezen")
        st.write(
            "Netcapaciteit moet altijd met tijdreeksen worden gelezen. Een jaarvolume kan laag zijn terwijl een korte piek toch het contractvermogen overschrijdt. "
            "De zwaarste netweek toont wanneer de hoogste netbelasting ontstaat en welke gebruikers of installaties eraan bijdragen. De duurcurve laat zien "
            "hoe vaak hoge waarden voorkomen."
        )
        st.markdown("- Een enkele korte piek wijst vaak op regelstrategie, slim laden, batterij of processturing.")
        st.markdown("- Veel uren boven contract wijzen eerder op te weinig aansluitvermogen, te veel gelijktijdige elektrificatie of onvoldoende lokale opwek/flexibiliteit.")
        st.markdown("- Een hoge p99-waarde betekent dat de belasting niet alleen door een uitschieter wordt veroorzaakt.")
        st.markdown("- Gemiddelde netruimte is nuttig voor slim laden of batterij laden, maar zegt niet vanzelf dat elke piek oplosbaar is.")

        st.markdown("##### 5.3 Verbruik, opwek en load match")
        st.write(
            "De jaar- en maandprofielen laten zien of vraag en opwek op dezelfde momenten plaatsvinden. Dit is vooral belangrijk bij PV: veel opwek in de zomer "
            "helpt beperkt bij winterse warmtepomppieken. Load match gaat daarom niet alleen over hoeveel PV wordt opgewekt, maar ook over wanneer die opwek "
            "beschikbaar is ten opzichte van gebouwvraag, mobiliteit en processen."
        )
        render_compact_table(LOAD_MATCH_ROWS, ("Resultaat", "Interpretatie", "Typische maatregel"))

        st.markdown("##### 5.4 Warmte en gasloosheid lezen")
        st.write(
            "Een gasloos scenario is pas overtuigend als de warmtevraag door niet-gasbronnen wordt gedekt en de elektrische consequentie daarvan binnen de "
            "netaansluiting past. Alleen brandstofinput verlagen is dus niet genoeg; de warmtepomp kan de gasvraag vervangen door elektrische piekvraag."
        )
        st.markdown("- Warmtevraag is de behoefte van het gebouw; warmtelevering is wat installaties daadwerkelijk invullen.")
        st.markdown("- Warmtepomp-elektriciteit moet worden meegelezen in de netcapaciteit, vooral in koude weken.")
        st.markdown("- Ongedekte warmte betekent dat het scenario technisch niet volledig voorziet in de warmtevraag, tenzij dit bewust is toegestaan.")
        st.markdown("- WKK-warmteoverschot is niet hetzelfde als ongedekte warmte: overschot betekent dat warmte beschikbaar was maar op dat moment niet nuttig kon worden gebruikt.")
        st.markdown("- Gasinput uit WKK of ketel betekent dat het scenario niet volledig gasloos is, ook als de netbelasting gunstig is.")

        st.markdown("##### 5.5 Opslag en flexibiliteit lezen")
        st.write(
            "Opslag moet worden beoordeeld op timing en benutting. Een batterij of warmtebuffer is nuttig wanneer die laadt op momenten met overschot of netruimte "
            "en ontlaadt op momenten met piek of warmtetekort. Alleen een grote capaciteit is geen garantie voor effect als laad- en ontlaadmomenten niet passen."
        )
        st.markdown("- Als de batterij vaak leeg is tijdens pieken, is capaciteit of laadmoment onvoldoende.")
        st.markdown("- Als de batterij vaak vol is terwijl er nog teruglevering optreedt, is vermogen/capaciteit te klein of vraagsturing nodig.")
        st.markdown("- Batterij laden is altijd hoger of gelijk aan nuttige ontlading gedeeld door rendement; verschil tussen laden en ontladen is normaal door verliezen en SoC-eindstand.")
        st.markdown("- Warmteopslag helpt vooral wanneer warmteoverschot en warmtetekort binnen een passende tijdsafstand liggen.")

        st.markdown("##### 5.6 Modelchecks lezen")
        st.write(
            "Modelchecks zijn bedoeld als kwaliteitsfilter. Een waarschuwing betekent niet automatisch dat alle resultaten onbruikbaar zijn, maar wel dat de gebruiker "
            "moet begrijpen wat er aan de hand is voordat conclusies worden getrokken."
        )
        render_compact_table(MODEL_CHECK_ROWS, ("Check", "Betekenis", "Actie bij aandacht nodig"))

    with m_sources:
        st.markdown("#### 6. Bronnen en onderbouwing")
        st.write(
            "De onderstaande bronnen onderbouwen de gekozen modelindicatoren en de vereenvoudigde rekenaanpak. Ze zijn opgenomen als inhoudelijke "
            "onderbouwing voor de methode; de feitelijke implementatie volgt de code in deze app."
        )
        st.markdown("- IEA, Energy End-uses and Efficiency Indicators: onderbouwt het gebruik van eindgebruikcategorieen en energie-intensiteit als kernindicatoren voor gebouwen.")
        st.markdown("- IEA, Buildings en The Future of Heat Pumps: onderbouwt het belang van elektrificatie, warmte/koude als eindgebruik en COP als verhouding tussen geleverde warmte en elektrische input.")
        st.markdown("- EnergyPlus Engineering Reference: bouwfysische achtergrond voor warmtebalansen, interne winsten, ventilatie, infiltratie en zonnewinsten.")
        st.markdown("- NREL/PVPMC PVWatts: onderbouwt een PV-model waarin instraling, systeemverliezen en temperatuurcorrectie bepalend zijn voor PV-productie.")
        st.markdown("- PV-load matching literatuur: onderbouwt indicatoren zoals zelfconsumptie, zelfvoorziening, timing tussen opwek en vraag en de rol van opslag.")
        st.markdown("- NREL REopt en opslagpublicaties: onderbouwen het gebruik van opslag voor piekreductie, zelfconsumptie en dispatchbeslissingen.")
        st.markdown("- ASHRAE Guideline 14 / FEMP-calibratiecriteria: onderbouwt het gebruik van NMBE en CV(RMSE) voor vergelijking tussen model en meetdata.")


st.info(
    f"Weerbron: {WEATHER_PATH.name}. De simulatie gebruikt deze data om zonopwek, warmtevraag en koeling door het jaar te berekenen."
)

load_tab, generation_tab, heat_tab, storage_tab, total_tab, validation_tab, methodology_tab = st.tabs(["Verbruik", "Opwek", "Warmte", "Opslag", "Resultaten", "Validatie", "Methode & uitleg"])


with load_tab:
    t_def, t_bld, t_pe, t_pr, t_mob, t_ov, t_run = st.tabs([
        "Gebouw",
        "Gebouwdetails",
        "Elektrisch verbruik",
        "Processen",
        "Mobiliteit",
        "Overig verbruik",
        "Verbruik berekenen",
    ])

    with t_def:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.selectbox(label_for("def_building_type"), [x.value for x in BuildingType], key="def_building_type", format_func=choice_label, help=help_for("def_building_type"))
        with c2:
            st.selectbox(label_for("def_year_class"), [x.value for x in YearClass], key="def_year_class", format_func=choice_label, help=help_for("def_year_class"))
        with c3:
            st.selectbox(label_for("def_orientation"), [x.value for x in Orientation8], key="def_orientation", format_func=choice_label, help=help_for("def_orientation"))
        with c4:
            st.number_input(label_for("def_bvo"), min_value=50.0, step=50.0, key="def_bvo", help=help_for("def_bvo"))

        c5, c6, c7, c8 = st.columns(4)
        with c5:
            st.number_input(label_for("def_floors"), min_value=1, step=1, key="def_floors", help=help_for("def_floors"))
        with c6:
            st.slider(label_for("def_wwr"), 0.05, 0.80, key="def_wwr", help=help_for("def_wwr"))
        with c7:
            st.selectbox(label_for("def_shape"), [x.value for x in BuildingShape], key="def_shape", format_func=choice_label, help=help_for("def_shape"))
        with c8:
            st.metric(label_for("def_shape_metric"), _fmt_nl_number(SHAPE_FACTOR_BY_SHAPE[BuildingShape(st.session_state["def_shape"])], 2))

        st.checkbox(label_for("def_manual_shape"), key="def_manual_shape", help=help_for("def_manual_shape"))
        if st.session_state["def_manual_shape"]:
            st.slider(label_for("def_shape_manual"), 0.6, 2.0, step=0.05, key="def_shape_manual", help=help_for("def_shape_manual"))

        cfg0 = build_cfg()
        render_input_default_kpis(cfg0)

    with t_bld:
        st.checkbox(label_for("bld_enable"), key="bld_enable", help=help_for("bld_enable"))
        if st.session_state["bld_enable"]:
            st.checkbox(label_for("bld_sched_enable"), key="bld_sched_enable", help=help_for("bld_sched_enable"))
            if st.session_state["bld_sched_enable"]:
                schedule_editor("bld_sched")

            st.subheader("Temperatuurinstellingen")
            heat_occ_max = max(float(st.session_state["bld_t_cool_occ"]) - 0.5, 0.0)
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.number_input(label_for("bld_t_heat_occ"), min_value=0.0, max_value=heat_occ_max, value=float(st.session_state["bld_t_heat_occ"]), step=0.5, key="bld_t_heat_occ", help=help_for("bld_t_heat_occ"))
            with c2:
                st.number_input(label_for("bld_t_heat_unocc"), min_value=0.0, max_value=float(st.session_state["bld_t_heat_occ"]), value=float(st.session_state["bld_t_heat_unocc"]), step=0.5, key="bld_t_heat_unocc", help=help_for("bld_t_heat_unocc"))
            with c3:
                st.number_input(label_for("bld_t_cool_occ"), min_value=float(st.session_state["bld_t_heat_occ"]) + 0.5, value=float(st.session_state["bld_t_cool_occ"]), step=0.5, key="bld_t_cool_occ", help=help_for("bld_t_cool_occ"))
            with c4:
                st.number_input(label_for("bld_t_cool_unocc"), min_value=float(st.session_state["bld_t_cool_occ"]), value=float(st.session_state["bld_t_cool_unocc"]), step=0.5, key="bld_t_cool_unocc", help=help_for("bld_t_cool_unocc"))

            st.subheader("Ventilatie, glas en zon")
            c9, c10, c11, c12 = st.columns(4)
            with c9:
                st.slider(label_for("bld_eta_wtw"), 0.0, 0.95, 0.80, 0.01, key="bld_eta_wtw", help=help_for("bld_eta_wtw"))
            with c10:
                st.number_input(label_for("bld_qv10"), value=0.40, step=0.1, key="bld_qv10", help=help_for("bld_qv10"))
            with c11:
                st.number_input(label_for("bld_g_value"), value=0.50, step=0.01, key="bld_g_value", help=help_for("bld_g_value"))
            with c12:
                st.number_input(label_for("bld_shading_factor"), value=0.80, step=0.01, key="bld_shading_factor", help=help_for("bld_shading_factor"))

        cfg = build_cfg()
        prev_df, _, _, _ = run_load_simulation(cfg, weather=WEATHER_DF.iloc[:24 * 7])
        preview_week_chart(prev_df, ["Q_heat_kWth", "Q_cool_kWth"], "Voorbeeld gebouwvraag", "building")
        render_load_component_kpis(
            prev_df,
            [
                ("Warmtevraag eerste week", "Q_heat_kWth", "kWhth", 0),
                ("Weekintensiteit warmte", "Q_heat_kWth", "kWhth/m²", 1),
                ("Piek warmtevraag", "Q_heat_kWth", "kWth", 1),
                ("Koelvraag eerste week", "Q_cool_kWth", "kWhth", 0),
            ],
        )

    with t_pe:
        st.checkbox(label_for("pe_enable"), key="pe_enable", help=help_for("pe_enable"))
        if st.session_state["pe_enable"]:
            st.number_input(label_for("pe_occ"), value=10.0, step=0.5, key="pe_occ", help=help_for("pe_occ"))
            st.number_input(label_for("pe_unocc"), value=3.0, step=0.5, key="pe_unocc", help=help_for("pe_unocc"))
        edit_occ_subloads("pelektro_subloads", "pe", 5.0, 1.0)

        pe_cfg = build_cfg()
        pe_df, _, _, _ = run_load_simulation(
            pe_cfg,
            weather=WEATHER_DF.iloc[:24 * 7],
            pelektro_subloads=subload_payload("pelektro_subloads", "occ"),
        )
        preview_week_chart(pe_df, ["P_elektro_kW"], "Voorbeeld elektrisch verbruik", "electric")
        render_load_component_kpis(
            pe_df,
            [
                ("Elektrisch verbruik eerste week", "P_elektro_kW", "kWh", 0),
                ("Weekintensiteit elektrisch", "P_elektro_kW", "kWh/m²", 1),
                ("Piek elektrisch vermogen", "P_elektro_kW", "kW", 1),
            ],
        )

    with t_pr:
        st.checkbox(label_for("pr_enable"), key="pr_enable", help=help_for("pr_enable"))
        if st.session_state["pr_enable"]:
            st.number_input(label_for("pr_pp"), value=0.0, step=1.0, key="pr_pp", help=help_for("pr_pp"))
            st.number_input(label_for("pr_pi"), value=0.0, step=1.0, key="pr_pi", help=help_for("pr_pi"))
        edit_process_subloads()

        pr_cfg = build_cfg()
        pr_df, _, _, _ = run_load_simulation(
            pr_cfg,
            weather=WEATHER_DF.iloc[:24 * 7],
            pprocess_subloads=subload_payload("pprocess_subloads", "process"),
        )
        preview_week_chart(pr_df, ["P_process_kW"], "Voorbeeld procesverbruik", "process")
        render_load_component_kpis(
            pr_df,
            [
                ("Procesverbruik eerste week", "P_process_kW", "kWh", 0),
                ("Weekintensiteit proces", "P_process_kW", "kWh/m²", 1),
                ("Piek procesvermogen", "P_process_kW", "kW", 1),
            ],
        )

    with t_mob:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.number_input(label_for("mob_n_cars"), min_value=0, value=int(st.session_state["mob_n_cars"]), step=1, key="mob_n_cars", help=help_for("mob_n_cars"))
            st.number_input(label_for("mob_battery_capacity"), min_value=0.0, value=float(st.session_state["mob_battery_capacity"]), step=5.0, key="mob_battery_capacity", help=help_for("mob_battery_capacity"))
            st.number_input(label_for("mob_arrival_hour"), min_value=0, max_value=23, value=int(st.session_state["mob_arrival_hour"]), step=1, key="mob_arrival_hour", help=help_for("mob_arrival_hour"))
        with c2:
            st.number_input(label_for("mob_p_charger_max"), min_value=1.0, value=float(st.session_state["mob_p_charger_max"]), step=1.0, key="mob_p_charger_max", help=help_for("mob_p_charger_max"))
            st.number_input(label_for("mob_arrival_soc"), min_value=0.0, max_value=100.0, value=float(st.session_state["mob_arrival_soc"]), step=5.0, key="mob_arrival_soc", help=help_for("mob_arrival_soc"))
            st.number_input(label_for("mob_departure_hour"), min_value=int(st.session_state["mob_arrival_hour"]) + 1, max_value=24, value=int(st.session_state["mob_departure_hour"]), step=1, key="mob_departure_hour", help=help_for("mob_departure_hour"))
        with c3:
            st.number_input(label_for("mob_site_cap"), min_value=0.0, value=float(st.session_state["mob_site_cap"]), step=5.0, key="mob_site_cap", help=help_for("mob_site_cap"))
            st.number_input(label_for("mob_target_soc"), min_value=float(st.session_state["mob_arrival_soc"]), max_value=100.0, value=float(st.session_state["mob_target_soc"]), step=5.0, key="mob_target_soc", help=help_for("mob_target_soc"))
            st.slider(label_for("mob_cars_present"), 0.0, 100.0, float(st.session_state["mob_cars_present"]), 5.0, key="mob_cars_present", help=help_for("mob_cars_present"))
        st.selectbox(label_for("mob_charge_mode"), ["smart", "direct"], key="mob_charge_mode", format_func=choice_label, help=help_for("mob_charge_mode"))

        mob_cfg = build_cfg()
        mob_df, _, _, _ = run_load_simulation(
            mob_cfg,
            weather=WEATHER_DF.iloc[:24 * 7],
            grid_cap_kW=safe_contract_value(st.session_state.get("grid_cap_kW")),
        )
        mob_summary = mob_df.attrs.get("mobility_summary", {})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Benodigd per auto", _fmt_kpi(mob_summary.get("energy_per_car_kWh", 0.0), "kWh", 1))
        c2.metric("Totaal nodig", _fmt_kpi(mob_summary.get("energy_required_kWh", 0.0), "kWh", 0))
        c3.metric("Geladen", _fmt_kpi(mob_summary.get("energy_charged_kWh", 0.0), "kWh", 0))
        c4.metric("Laadtekort", _fmt_kpi(mob_summary.get("energy_unserved_kWh", 0.0), "kWh", 0))
        if float(mob_summary.get("energy_unserved_kWh", 0.0)) > 1e-6:
            st.warning("Niet alle gewenste laadenergie past binnen de gekozen laadmodus, aanwezigheidstijd en contractruimte.")
        preview_week_chart(
            mob_df,
            ["P_base_without_mobility_kW", "P_mobility_kW"],
            "Voorbeeld mobiliteit",
            "mobility",
            f"Laadmodus: {choice_label(st.session_state['mob_charge_mode'])}. Contractvermogen: {_fmt_kpi(st.session_state['grid_cap_kW'], 'kW', 1)}.",
        )

    with t_ov:
        st.checkbox(label_for("ov_enable"), key="ov_enable", help=help_for("ov_enable"))
        if st.session_state["ov_enable"]:
            st.number_input(label_for("ov_occ"), value=2.0, step=0.2, key="ov_occ", help=help_for("ov_occ"))
            st.number_input(label_for("ov_unocc"), value=0.5, step=0.2, key="ov_unocc", help=help_for("ov_unocc"))
        edit_occ_subloads("poverig_subloads", "ov", 1.0, 0.2)

        ov_cfg = build_cfg()
        ov_df, _, _, _ = run_load_simulation(
            ov_cfg,
            weather=WEATHER_DF.iloc[:24 * 7],
            poverig_subloads=subload_payload("poverig_subloads", "occ"),
        )
        preview_week_chart(ov_df, ["P_overig_kW"], "Voorbeeld overig verbruik", "other")
        render_load_component_kpis(
            ov_df,
            [
                ("Overig verbruik eerste week", "P_overig_kW", "kWh", 0),
                ("Weekintensiteit overig", "P_overig_kW", "kWh/m²", 1),
                ("Piek overig vermogen", "P_overig_kW", "kW", 1),
            ],
        )

    with t_run:
        if st.button("Bereken verbruik", type="primary", help="Wat: start de verbruiksberekening. In het model worden gebouw, elektrische lasten, processen en mobiliteit samengevoegd. Effect: resultaten worden vernieuwd met de huidige instellingen."):
            cfg = build_cfg()
            df, _fig_heat, _fig_balance, _ = run_energy_system_simulation(
                cfg,
                weather=WEATHER_DF,
                grid_cap_kW=safe_contract_value(st.session_state.get("grid_cap_kW")),
                pelektro_subloads=subload_payload("pelektro_subloads", "occ"),
                pprocess_subloads=subload_payload("pprocess_subloads", "process"),
                poverig_subloads=subload_payload("poverig_subloads", "occ"),
            )
            st.session_state["last_load_df"] = df

        if st.session_state["last_load_df"] is not None:
            render_load_calculation_results(st.session_state["last_load_df"])


with generation_tab:
    g_pv, g_wkk, g_grid, g_run = st.tabs(["Zonnepanelen", "WKK", "Net", "Opwek berekenen"])

    with g_pv:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.checkbox(label_for("pv_enabled"), key="pv_enabled", help=help_for("pv_enabled"))
        with c2:
            st.number_input(label_for("pv_cap"), min_value=0.0, step=10.0, key="pv_cap", help=help_for("pv_cap"))
        with c3:
            st.number_input(label_for("pv_tilt"), min_value=0.0, max_value=90.0, step=1.0, key="pv_tilt", help=help_for("pv_tilt"))
        with c4:
            st.selectbox(label_for("pv_azimuth"), PV_AZIMUTH_OPTIONS, key="pv_azimuth", format_func=choice_label, help=help_for("pv_azimuth"))

        c5, c6, c7, c8, c9 = st.columns(5)
        with c5:
            st.number_input(label_for("pv_pr"), min_value=0.0, max_value=1.2, step=0.01, key="pv_pr", help=help_for("pv_pr"))
        with c6:
            st.number_input(label_for("pv_inv_eff"), min_value=0.0, max_value=1.0, step=0.01, key="pv_inv_eff", help=help_for("pv_inv_eff"))
        with c7:
            st.number_input(label_for("pv_temp_coeff"), step=0.001, key="pv_temp_coeff", help=help_for("pv_temp_coeff"))
        with c8:
            st.number_input(label_for("pv_site_cap"), min_value=0.0, step=10.0, key="pv_site_cap", help=help_for("pv_site_cap"))
        with c9:
            st.checkbox(label_for("pv_no_export"), key="pv_no_export", help=help_for("pv_no_export"))

        cfg = build_cfg()
        pv_df = simulate_pv(WEATHER_DF.index, cfg.pv, WEATHER_DF)
        preview_week_chart(
            pv_df,
            ["P_pv_kW"],
            "Voorbeeld zonnepanelen",
            "pv",
            f"Richting: {choice_label(st.session_state['pv_azimuth'])}. Vermogen: {_fmt_nl_number(float(st.session_state['pv_cap']), 0)} kWp.",
        )
        pv_year = annual_sum(pv_df, "P_pv_kW")
        pv_capacity = float(cfg.pv.installed_capacity_kWp)
        full_load_hours = pv_year / pv_capacity if pv_capacity > 0 else None
        render_kpi_row(
            [
                ("Piekvermogen PV", peak_value(pv_df, "P_pv_kW"), "kW", 1),
                ("Jaaropwek PV", pv_year, "kWh", 0),
                ("Vollasturen", full_load_hours, "h", 0),
            ],
            columns=3,
        )

    with g_wkk:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.checkbox(label_for("wkk_enabled"), key="wkk_enabled", help=help_for("wkk_enabled"))
        with c2:
            st.number_input(label_for("wkk_p_rated"), min_value=0.0, step=10.0, key="wkk_p_rated", help=help_for("wkk_p_rated"))
        with c3:
            st.slider(label_for("wkk_min_frac"), 0.0, 1.0, 0.0, 0.05, key="wkk_min_frac", help=help_for("wkk_min_frac"))

        c4, c5, c6 = st.columns(3)
        with c4:
            st.number_input(label_for("wkk_el_eff"), min_value=0.01, max_value=1.0, step=0.01, key="wkk_el_eff", help=help_for("wkk_el_eff"))
        with c5:
            st.number_input(label_for("wkk_th_eff"), min_value=0.0, max_value=1.0, step=0.01, key="wkk_th_eff", help=help_for("wkk_th_eff"))
        with c6:
            st.selectbox(
                label_for("wkk_dispatch_mode"),
                [
                    "electricity_led",
                    "thermal_led",
                    "heat_led",
                    "hybrid_peak_shaving",
                    "heat_led_with_electric_cap",
                    "must_run",
                    "off",
                ],
                key="wkk_dispatch_mode",
                format_func=choice_label,
                help=help_for("wkk_dispatch_mode"),
            )

        cfg = build_cfg()
        demand_df = pd.DataFrame(
            {"P_residual_before_wkk_kW": float(st.session_state["wkk_p_rated"]) * 0.7, "Q_heat_demand_kWth": float(st.session_state["wkk_p_rated"]) * 0.5},
            index=WEATHER_DF.index,
        )
        wkk_df = dispatch_wkk(WEATHER_DF.index, cfg.wkk, demand_df)
        preview_week_chart(
            wkk_df,
            ["P_wkk_el_kW", "P_wkk_th_kW", "Q_wkk_used_kWth"],
            "Voorbeeld WKK",
            "wkk",
            f"Regeling: {choice_label(st.session_state['wkk_dispatch_mode'])}.",
        )
        render_kpi_row(
            [
                ("Piek WKK elektrisch", peak_value(wkk_df, "P_wkk_el_kW"), "kW", 1),
                ("Piek WKK warmte", peak_value(wkk_df, "P_wkk_th_kW"), "kWth", 1),
                ("Brandstofinput", annual_sum(wkk_df, "F_wkk_fuel_kWh_per_h"), "kWh", 0),
                ("Benutte warmte", annual_sum(wkk_df, "Q_wkk_used_kWth"), "kWhth", 0),
            ]
        )

    with g_grid:
        st.number_input(label_for("grid_cap_kW"), min_value=0.0, step=5.0, key="grid_cap_kW", help=help_for("grid_cap_kW"))
        st.caption("0 = geen expliciete begrenzing in de simulatie.")
        render_kpi_row([("Contractvermogen", safe_contract_value(st.session_state.get("grid_cap_kW")), "kW", 1)], columns=1)

    with g_run:
        cfg = build_cfg()
        gen_df, _, _, _ = run_energy_system_simulation(
            cfg,
            weather=WEATHER_DF,
            grid_cap_kW=(None if float(st.session_state["grid_cap_kW"]) == 0 else float(st.session_state["grid_cap_kW"])),
            pelektro_subloads=subload_payload("pelektro_subloads", "occ"),
            pprocess_subloads=subload_payload("pprocess_subloads", "process"),
            poverig_subloads=subload_payload("poverig_subloads", "occ"),
        )
        st.session_state["last_generation_df"] = gen_df
        render_generation_calculation_results(gen_df)


with heat_tab:
    h_ref, h_hp, h_boiler, h_dh = st.tabs(["Referentie-installatie", "Warmtepomp", "Ketel", "Warmtenet"])

    with h_ref:
        st.checkbox(label_for("ref_heat_enabled"), key="ref_heat_enabled", help=help_for("ref_heat_enabled"))
        st.subheader("Referentie COP verwarming")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.number_input(label_for("ref_cop_winter"), min_value=0.1, value=float(st.session_state["ref_cop_winter"]), step=0.1, key="ref_cop_winter", help=help_for("ref_cop_winter"))
        with c2:
            st.number_input(label_for("ref_cop_spring"), min_value=0.1, value=float(st.session_state["ref_cop_spring"]), step=0.1, key="ref_cop_spring", help=help_for("ref_cop_spring"))
        with c3:
            st.number_input(label_for("ref_cop_summer"), min_value=0.1, value=float(st.session_state["ref_cop_summer"]), step=0.1, key="ref_cop_summer", help=help_for("ref_cop_summer"))
        with c4:
            st.number_input(label_for("ref_cop_autumn"), min_value=0.1, value=float(st.session_state["ref_cop_autumn"]), step=0.1, key="ref_cop_autumn", help=help_for("ref_cop_autumn"))

        st.subheader("Referentie EER koeling")
        c5, c6, c7, c8 = st.columns(4)
        with c5:
            st.number_input(label_for("ref_eer_winter"), min_value=0.1, value=float(st.session_state["ref_eer_winter"]), step=0.1, key="ref_eer_winter", help=help_for("ref_eer_winter"))
        with c6:
            st.number_input(label_for("ref_eer_spring"), min_value=0.1, value=float(st.session_state["ref_eer_spring"]), step=0.1, key="ref_eer_spring", help=help_for("ref_eer_spring"))
        with c7:
            st.number_input(label_for("ref_eer_summer"), min_value=0.1, value=float(st.session_state["ref_eer_summer"]), step=0.1, key="ref_eer_summer", help=help_for("ref_eer_summer"))
        with c8:
            st.number_input(label_for("ref_eer_autumn"), min_value=0.1, value=float(st.session_state["ref_eer_autumn"]), step=0.1, key="ref_eer_autumn", help=help_for("ref_eer_autumn"))

    with h_hp:
        st.checkbox(label_for("hp_enabled"), key="hp_enabled", help=help_for("hp_enabled"))
        c1, c2, c3 = st.columns(3)
        with c1:
            st.number_input(label_for("hp_capacity"), min_value=0.0, step=10.0, key="hp_capacity", help=help_for("hp_capacity"))
        with c2:
            st.selectbox(label_for("hp_cop_mode"), ["fixed", "seasonal", "weather_dependent"], key="hp_cop_mode", format_func=choice_label, help=help_for("hp_cop_mode"))
        with c3:
            st.number_input(label_for("hp_cop_nominal"), min_value=0.1, step=0.1, key="hp_cop_nominal", help=help_for("hp_cop_nominal"))
        c4, c5 = st.columns(2)
        with c4:
            st.slider(label_for("hp_min_frac"), 0.0, 1.0, 0.0, 0.05, key="hp_min_frac", help=help_for("hp_min_frac"))
        with c5:
            st.number_input(label_for("hp_site_cap"), min_value=0.0, step=5.0, key="hp_site_cap", help=help_for("hp_site_cap"))

    with h_boiler:
        st.checkbox(label_for("boiler_enabled"), key="boiler_enabled", help=help_for("boiler_enabled"))
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.number_input(label_for("boiler_capacity"), min_value=0.0, step=10.0, key="boiler_capacity", help=help_for("boiler_capacity"))
        with c2:
            st.number_input(label_for("boiler_eff"), min_value=0.01, max_value=1.0, step=0.01, key="boiler_eff", help=help_for("boiler_eff"))
        with c3:
            st.slider(label_for("boiler_min_frac"), 0.0, 1.0, 0.0, 0.05, key="boiler_min_frac", help=help_for("boiler_min_frac"))
        with c4:
            st.selectbox(label_for("boiler_fuel_type"), ["gas", "biogas", "hydrogen", "generic"], key="boiler_fuel_type", format_func=choice_label, help=help_for("boiler_fuel_type"))

    with h_dh:
        st.checkbox(label_for("dh_enabled"), key="dh_enabled", help=help_for("dh_enabled"))
        c1, c2 = st.columns(2)
        with c1:
            st.number_input(label_for("dh_capacity"), min_value=0.0, step=10.0, key="dh_capacity", help=help_for("dh_capacity"))
        with c2:
            st.number_input(label_for("dh_tariff"), min_value=0.0, step=0.01, key="dh_tariff", help=help_for("dh_tariff"))


with storage_tab:
    s_bat, s_heat = st.tabs(["Batterijen", "Warmteopslag"])

    with s_bat:
        st.checkbox(label_for("bat_enabled"), key="bat_enabled", help=help_for("bat_enabled"))
        c1, c2, c3 = st.columns(3)
        with c1:
            st.number_input(label_for("bat_capacity"), min_value=0.0, step=10.0, key="bat_capacity", help=help_for("bat_capacity"))
            st.number_input(label_for("bat_soc_init"), min_value=0.0, max_value=100.0, step=5.0, key="bat_soc_init", help=help_for("bat_soc_init"))
        with c2:
            st.number_input(label_for("bat_p_charge"), min_value=0.0, step=10.0, key="bat_p_charge", help=help_for("bat_p_charge"))
            st.number_input(label_for("bat_soc_min"), min_value=0.0, max_value=100.0, step=5.0, key="bat_soc_min", help=help_for("bat_soc_min"))
        with c3:
            st.number_input(label_for("bat_p_discharge"), min_value=0.0, step=10.0, key="bat_p_discharge", help=help_for("bat_p_discharge"))
            st.number_input(label_for("bat_soc_max"), min_value=0.0, max_value=100.0, step=5.0, key="bat_soc_max", help=help_for("bat_soc_max"))
        st.number_input(label_for("bat_eff"), min_value=0.0, max_value=1.0, step=0.01, key="bat_eff", help=help_for("bat_eff"))
        st.selectbox(
            label_for("bat_charge_strategy"),
            options=["surplus_only", "grid_headroom"],
            format_func=lambda x: {
                "surplus_only": "Alleen laden met lokaal overschot (PV/WKK)",
                "grid_headroom": "Laden vanuit net tot contractvermogen",
            }[x],
            key="bat_charge_strategy",
            help=help_for("bat_charge_strategy"),
        )
        st.caption("De batterij laadt bij overschot en ontlaadt bij resterende netvraag.")

    with s_heat:
        st.checkbox(label_for("th_enabled"), key="th_enabled", help=help_for("th_enabled"))
        c1, c2, c3 = st.columns(3)
        with c1:
            st.number_input(label_for("th_capacity"), min_value=0.0, step=10.0, key="th_capacity", help=help_for("th_capacity"))
            st.number_input(label_for("th_soc_init"), min_value=0.0, max_value=100.0, step=5.0, key="th_soc_init", help=help_for("th_soc_init"))
        with c2:
            st.number_input(label_for("th_p_charge"), min_value=0.0, step=10.0, key="th_p_charge", help=help_for("th_p_charge"))
            st.number_input(label_for("th_soc_min"), min_value=0.0, max_value=100.0, step=5.0, key="th_soc_min", help=help_for("th_soc_min"))
        with c3:
            st.number_input(label_for("th_p_discharge"), min_value=0.0, step=10.0, key="th_p_discharge", help=help_for("th_p_discharge"))
            st.number_input(label_for("th_soc_max"), min_value=0.0, max_value=100.0, step=5.0, key="th_soc_max", help=help_for("th_soc_max"))
        c4, c5, c6 = st.columns(3)
        with c4:
            st.number_input(label_for("th_loss"), min_value=0.0, max_value=1.0, step=0.01, key="th_loss", help=help_for("th_loss"))
        with c5:
            st.number_input(label_for("th_eff_charge"), min_value=0.01, max_value=1.0, step=0.01, key="th_eff_charge", help=help_for("th_eff_charge"))
        with c6:
            st.number_input(label_for("th_eff_discharge"), min_value=0.01, max_value=1.0, step=0.01, key="th_eff_discharge", help=help_for("th_eff_discharge"))
        st.caption("Thermische opslag is nu onderdeel van de warmteketen in de totale simulatie.")


with total_tab:
    st.write("Bereken het totale energiesysteem en bekijk hoeveel vermogen nog uit het net nodig is.")

    if st.button("Bereken totaal", type="primary", help="Wat: start de totale simulatie. In het model worden verbruik, opwek, warmtebronnen en opslag gecombineerd. Effect: alle resultaatgrafieken en KPI's worden vernieuwd."):
        try:
            cfg = build_cfg()
            df, _fig_heat, _fig_balance, _ = run_energy_system_simulation(
                cfg,
                weather=WEATHER_DF,
                grid_cap_kW=safe_contract_value(st.session_state.get("grid_cap_kW")),
                pelektro_subloads=subload_payload("pelektro_subloads", "occ"),
                pprocess_subloads=subload_payload("pprocess_subloads", "process"),
                poverig_subloads=subload_payload("poverig_subloads", "occ"),
            )
            st.session_state["last_total_df"] = df
        except Exception as exc:
            st.error(f"Totale berekening mislukt: {exc}")

    if st.session_state["last_total_df"] is not None:
        render_results_dashboard(
            st.session_state["last_total_df"],
            safe_contract_value(st.session_state.get("grid_cap_kW")),
            cfg=build_cfg(),
        )

with validation_tab:
    st.write("Upload meetdata en vergelijk die met de laatste totale simulatie.")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.checkbox(label_for("measurement_enabled"), key="measurement_enabled", help=help_for("measurement_enabled"))
        st.selectbox(label_for("measurement_power_unit_mode"), ["kW", "kWh_per_interval"], key="measurement_power_unit_mode", format_func=choice_label, help=help_for("measurement_power_unit_mode"))
    with c2:
        st.selectbox(label_for("measurement_expected_resolution"), ["15min", "30min", "1h"], key="measurement_expected_resolution", help=help_for("measurement_expected_resolution"))
        st.selectbox(label_for("measurement_gap_fill_method"), ["none", "ffill", "bfill", "interpolate_time", "zero"], key="measurement_gap_fill_method", format_func=choice_label, help=help_for("measurement_gap_fill_method"))
    with c3:
        st.selectbox(label_for("measurement_comparison_mode"), ["grid_import", "grid_export", "electric_load", "gas", "heat"], key="measurement_comparison_mode", format_func=choice_label, help=help_for("measurement_comparison_mode"))
        st.selectbox(label_for("measurement_resample_policy"), ["mean_to_hourly", "sum_to_hourly", "mean", "sum", "none"], key="measurement_resample_policy", format_func=choice_label, help=help_for("measurement_resample_policy"))

    uploaded = st.file_uploader(label_for("measurement_upload"), type=["csv", "txt", "xlsx", "xls"], key="measurement_upload", help=help_for("measurement_upload"))

    if uploaded is not None:
        st.session_state["last_measurement_filename"] = uploaded.name

        if st.button("Verwerk meetdata", key="process_measurements", help="Wat: leest het meetbestand in. In het model wordt de meetreeks klaargezet voor vergelijking. Effect: daarna kun je simulatie en meting valideren."):
            suffix = Path(uploaded.name).suffix or ".csv"
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(prefix="energieplanner_measurements_", suffix=suffix, delete=False) as tmp_file:
                    tmp_file.write(uploaded.getbuffer())
                    tmp_path = Path(tmp_file.name)
                bundle, metadata = load_measurement_bundle(
                    tmp_path,
                    timezone=str(st.session_state["measurement_timezone"]),
                    expected_resolution=str(st.session_state["measurement_expected_resolution"]),
                    power_unit_mode=str(st.session_state["measurement_power_unit_mode"]),
                    gap_fill_method=str(st.session_state["measurement_gap_fill_method"]),
                    hourly_resample_policy=str(st.session_state["measurement_resample_policy"]),
                )
                st.session_state["last_measurement_bundle"] = bundle
                st.session_state["last_measurement_metadata"] = metadata
                st.session_state["last_validation_result"] = None
            except Exception as exc:
                st.error(f"Meetdata kon niet worden verwerkt: {exc}")
            finally:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)

    if st.session_state.get("last_measurement_filename"):
        st.caption(f"Laatste meetbestand: {st.session_state['last_measurement_filename']}")

    render_measurement_metadata(st.session_state.get("last_measurement_metadata"))

    measurement_bundle = st.session_state.get("last_measurement_bundle")
    if measurement_bundle is not None:
        st.markdown("**Voorbeeld meetdata**")
        preview_cols = [c for c in ["P_grid_import_kW", "P_grid_export_kW", "P_electric_load_kW", "F_gas_kW", "Q_heat_kWth"] if c in measurement_bundle["measured_15m"].columns]
        if preview_cols:
            render_timeseries_plot(measurement_bundle["measured_15m"], preview_cols, "Voorbeeld meetdata", explanation_key="validation")
        st.dataframe(_format_nl_dataframe(measurement_bundle["measured_15m"].head(100)))

    if st.session_state.get("last_total_df") is None:
        st.info("Bereken eerst de totale simulatie om validatie te kunnen doen.")
    elif measurement_bundle is None:
        st.info("Upload en verwerk eerst meetdata.")
    else:
        if st.button("Vergelijk simulatie met meetdata", type="primary", key="run_validation", help="Wat: vergelijkt modeluitkomsten met echte meetdata. In het model worden de reeksen uitgelijnd. Effect: je ziet hoe goed de simulatie aansluit op de praktijk."):
            try:
                validation = prepare_validation_dataset(
                    st.session_state["last_total_df"],
                    measurement_bundle,
                    comparison_mode=str(st.session_state["measurement_comparison_mode"]),
                    resample_policy=str(st.session_state["measurement_resample_policy"]),
                )
                st.session_state["last_validation_result"] = validation
            except Exception as exc:
                st.error(f"Validatie mislukt: {exc}")

    render_validation_results(st.session_state.get("last_validation_result"))

    if st.session_state.get("last_validation_result") is not None:
        aligned = st.session_state["last_validation_result"].get("aligned")
        if aligned is not None and not aligned.empty:
            st.download_button(
                "Download validatie als CSV",
                aligned.to_csv().encode("utf-8"),
                file_name="validation_aligned_timeseries.csv",
                mime="text/csv",
                help="Wat: downloadt de uitgelijnde simulatie- en meetreeksen. In het model verandert dit niets. Effect: handig voor controle of rapportage.",
            )


with methodology_tab:
    render_methodology_tab()
