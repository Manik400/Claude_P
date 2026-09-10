"""Static configuration: countries, defaults, user agent."""
import os

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

DEFAULT_COUNTRIES = ["DE", "NL", "ES", "FI", "AU", "JP", "TH"]
DEFAULT_DAYS = 30            # ignore postings older than this when the date is known
DEFAULT_MAX_PER_SOURCE = 60  # per source per country
DEFAULT_DETAILS = 40         # how many jobs get their full description fetched
DEFAULT_OUT_ROOT = os.path.join(os.path.expanduser("~"), "Documents", "JobHunt")

# One entry per supported country. Fields:
#   name        display name
#   flag        emoji
#   aliases     things a user may type (lower-case)
#   linkedin    location string for LinkedIn's guest search
#   indeed      Indeed domain (blocked for scripts, used for the direct-search links)
#   glassdoor   Glassdoor search path fragment (direct links only)
#   cities      major cities (used by city-based sources such as The Muse / Xing)
#   muse        The Muse location strings
#   wellfound   Wellfound location slug
#   seek        (domain, siteKey, locale) for the Seek/JobsDB/JobStreet family
#   lang_hints  words that mark local-language "developer/engineer" titles
COUNTRIES = {
    "DE": dict(name="Germany", flag="\U0001F1E9\U0001F1EA", aliases=["germany", "deutschland", "de", "ger"],
               linkedin="Germany", indeed="de.indeed.com", glassdoor="germany-{q}-jobs-SRCH_IL.0,7_IN96_KO8,{n}.htm",
               cities=["Berlin", "Munich", "Hamburg", "Frankfurt", "Stuttgart", "Cologne"],
               muse=["Berlin, Germany", "Munich, Germany", "Hamburg, Germany", "Frankfurt, Germany"],
               wellfound="germany", seek=None,
               lang_hints=["entwickler", "softwareentwickler", "informatiker", "ingenieur"]),
    "NL": dict(name="Netherlands", flag="\U0001F1F3\U0001F1F1", aliases=["netherlands", "nederland", "holland", "nl", "the netherlands"],
               linkedin="Netherlands", indeed="nl.indeed.com", glassdoor="netherlands-{q}-jobs-SRCH_IL.0,11_IN178_KO12,{n}.htm",
               cities=["Amsterdam", "Rotterdam", "Utrecht", "Eindhoven", "The Hague"],
               muse=["Amsterdam, Netherlands", "Rotterdam, Netherlands", "Utrecht, Netherlands", "Eindhoven, Netherlands"],
               wellfound="netherlands", seek=None,
               lang_hints=["ontwikkelaar", "programmeur", "softwareontwikkelaar"]),
    "ES": dict(name="Spain", flag="\U0001F1EA\U0001F1F8", aliases=["spain", "espana", "españa", "es"],
               linkedin="Spain", indeed="es.indeed.com", glassdoor="spain-{q}-jobs-SRCH_IL.0,5_IN219_KO6,{n}.htm",
               cities=["Madrid", "Barcelona", "Valencia", "Malaga", "Seville"],
               muse=["Madrid, Spain", "Barcelona, Spain", "Valencia, Spain"],
               wellfound="spain", seek=None,
               lang_hints=["desarrollador", "desarrollador/a", "programador", "programador/a", "ingeniero", "ingeniero/a"]),
    "FI": dict(name="Finland", flag="\U0001F1EB\U0001F1EE", aliases=["finland", "suomi", "fi"],
               linkedin="Finland", indeed="fi.indeed.com", glassdoor="finland-{q}-jobs-SRCH_IL.0,7_IN76_KO8,{n}.htm",
               cities=["Helsinki", "Espoo", "Tampere", "Oulu", "Turku"],
               muse=["Helsinki, Finland"],
               wellfound="finland", seek=None,
               lang_hints=["kehittäjä", "ohjelmistokehittäjä", "ohjelmoija", "suunnittelija"]),
    "AU": dict(name="Australia", flag="\U0001F1E6\U0001F1FA", aliases=["australia", "au", "aus"],
               linkedin="Australia", indeed="au.indeed.com", glassdoor="australia-{q}-jobs-SRCH_IL.0,9_IN16_KO10,{n}.htm",
               cities=["Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide", "Canberra"],
               muse=["Sydney, Australia", "Melbourne, Australia", "Brisbane, Australia"],
               wellfound="australia", seek=("https://www.seek.com.au", "AU-Main", "en-AU"),
               lang_hints=[]),
    "JP": dict(name="Japan", flag="\U0001F1EF\U0001F1F5", aliases=["japan", "nippon", "jp", "日本"],
               linkedin="Japan", indeed="jp.indeed.com", glassdoor="japan-{q}-jobs-SRCH_IL.0,5_IN123_KO6,{n}.htm",
               cities=["Tokyo", "Osaka", "Kyoto", "Fukuoka", "Nagoya"],
               muse=["Tokyo, Japan", "Osaka, Japan"],
               wellfound="japan", seek=None,
               lang_hints=["エンジニア", "開発", "開発者", "プログラマ", "プログラマー"]),
    "TH": dict(name="Thailand", flag="\U0001F1F9\U0001F1ED", aliases=["thailand", "th", "siam", "ประเทศไทย"],
               linkedin="Thailand", indeed="th.indeed.com", glassdoor="thailand-{q}-jobs-SRCH_IL.0,8_IN229_KO9,{n}.htm",
               cities=["Bangkok", "Chiang Mai", "Phuket"],
               muse=["Bangkok, Thailand"],
               wellfound="thailand", seek=("https://th.jobsdb.com", "TH-Main", "en-TH"),
               lang_hints=["นักพัฒนา", "โปรแกรมเมอร์", "วิศวกร"]),
    # --- extra countries, available on request (not in the default set) ---
    "IN": dict(name="India", flag="\U0001F1EE\U0001F1F3", aliases=["india", "in", "bharat"],
               linkedin="India", indeed="in.indeed.com", glassdoor="india-{q}-jobs-SRCH_IL.0,5_IN115_KO6,{n}.htm",
               cities=["Bangalore", "Hyderabad", "Pune", "Gurgaon", "Noida", "Mumbai", "Chennai"],
               muse=["Bangalore, India", "Hyderabad, India", "Pune, India", "Mumbai, India"],
               wellfound="india", seek=None, lang_hints=[]),
    "SG": dict(name="Singapore", flag="\U0001F1F8\U0001F1EC", aliases=["singapore", "sg"],
               linkedin="Singapore", indeed="sg.indeed.com", glassdoor="singapore-{q}-jobs-SRCH_IL.0,9_IN217_KO10,{n}.htm",
               cities=["Singapore"], muse=["Singapore"], wellfound="singapore",
               seek=("https://www.jobstreet.com.sg", "SG-Main", "en-SG"), lang_hints=[]),
    "MY": dict(name="Malaysia", flag="\U0001F1F2\U0001F1FE", aliases=["malaysia", "my"],
               linkedin="Malaysia", indeed="malaysia.indeed.com", glassdoor="malaysia-{q}-jobs-SRCH_IL.0,8_IN170_KO9,{n}.htm",
               cities=["Kuala Lumpur"], muse=["Kuala Lumpur, Malaysia"], wellfound="malaysia",
               seek=("https://www.jobstreet.com.my", "MY-Main", "en-MY"), lang_hints=[]),
    "HK": dict(name="Hong Kong", flag="\U0001F1ED\U0001F1F0", aliases=["hong kong", "hongkong", "hk"],
               linkedin="Hong Kong SAR", indeed="hk.indeed.com", glassdoor="hong-kong-{q}-jobs-SRCH_IL.0,9_IN106_KO10,{n}.htm",
               cities=["Hong Kong"], muse=["Hong Kong"], wellfound="hong-kong",
               seek=("https://hk.jobsdb.com", "HK-Main", "en-HK"), lang_hints=[]),
    "NZ": dict(name="New Zealand", flag="\U0001F1F3\U0001F1FF", aliases=["new zealand", "nz"],
               linkedin="New Zealand", indeed="nz.indeed.com", glassdoor="new-zealand-{q}-jobs-SRCH_IL.0,11_IN186_KO12,{n}.htm",
               cities=["Auckland", "Wellington", "Christchurch"], muse=["Auckland, New Zealand"], wellfound="new-zealand",
               seek=("https://www.seek.co.nz", "NZ-Main", "en-NZ"), lang_hints=[]),
    "GB": dict(name="United Kingdom", flag="\U0001F1EC\U0001F1E7", aliases=["uk", "united kingdom", "england", "britain", "gb", "great britain"],
               linkedin="United Kingdom", indeed="uk.indeed.com", glassdoor="london-{q}-jobs-SRCH_IL.0,6_IC2671300_KO7,{n}.htm",
               cities=["London", "Manchester", "Edinburgh", "Birmingham"], muse=["London, United Kingdom", "Manchester, United Kingdom"],
               wellfound="united-kingdom", seek=None, lang_hints=[]),
    "IE": dict(name="Ireland", flag="\U0001F1EE\U0001F1EA", aliases=["ireland", "ie", "eire"],
               linkedin="Ireland", indeed="ie.indeed.com", glassdoor="ireland-{q}-jobs-SRCH_IL.0,7_IN70_KO8,{n}.htm",
               cities=["Dublin", "Cork"], muse=["Dublin, Ireland"], wellfound="ireland", seek=None, lang_hints=[]),
    "FR": dict(name="France", flag="\U0001F1EB\U0001F1F7", aliases=["france", "fr"],
               linkedin="France", indeed="fr.indeed.com", glassdoor="france-{q}-jobs-SRCH_IL.0,6_IN86_KO7,{n}.htm",
               cities=["Paris", "Lyon", "Toulouse"], muse=["Paris, France"], wellfound="france", seek=None,
               lang_hints=["développeur", "developpeur", "ingénieur", "ingenieur"]),
    "SE": dict(name="Sweden", flag="\U0001F1F8\U0001F1EA", aliases=["sweden", "sverige", "se"],
               linkedin="Sweden", indeed="se.indeed.com", glassdoor="sweden-{q}-jobs-SRCH_IL.0,6_IN223_KO7,{n}.htm",
               cities=["Stockholm", "Gothenburg", "Malmo"], muse=["Stockholm, Sweden"], wellfound="sweden", seek=None,
               lang_hints=["utvecklare", "systemutvecklare"]),
    "NO": dict(name="Norway", flag="\U0001F1F3\U0001F1F4", aliases=["norway", "norge", "no"],
               linkedin="Norway", indeed="no.indeed.com", glassdoor="norway-{q}-jobs-SRCH_IL.0,6_IN193_KO7,{n}.htm",
               cities=["Oslo", "Bergen"], muse=["Oslo, Norway"], wellfound="norway", seek=None, lang_hints=["utvikler"]),
    "DK": dict(name="Denmark", flag="\U0001F1E9\U0001F1F0", aliases=["denmark", "danmark", "dk"],
               linkedin="Denmark", indeed="dk.indeed.com", glassdoor="denmark-{q}-jobs-SRCH_IL.0,7_IN63_KO8,{n}.htm",
               cities=["Copenhagen", "Aarhus"], muse=["Copenhagen, Denmark"], wellfound="denmark", seek=None, lang_hints=["udvikler"]),
    "CH": dict(name="Switzerland", flag="\U0001F1E8\U0001F1ED", aliases=["switzerland", "schweiz", "suisse", "ch"],
               linkedin="Switzerland", indeed="ch.indeed.com", glassdoor="switzerland-{q}-jobs-SRCH_IL.0,11_IN226_KO12,{n}.htm",
               cities=["Zurich", "Geneva", "Basel"], muse=["Zurich, Switzerland"], wellfound="switzerland", seek=None,
               lang_hints=["entwickler", "développeur"]),
    "AT": dict(name="Austria", flag="\U0001F1E6\U0001F1F9", aliases=["austria", "österreich", "oesterreich", "at"],
               linkedin="Austria", indeed="at.indeed.com", glassdoor="austria-{q}-jobs-SRCH_IL.0,7_IN18_KO8,{n}.htm",
               cities=["Vienna", "Graz", "Linz"], muse=["Vienna, Austria"], wellfound="austria", seek=None, lang_hints=["entwickler"]),
    "PT": dict(name="Portugal", flag="\U0001F1F5\U0001F1F9", aliases=["portugal", "pt"],
               linkedin="Portugal", indeed="pt.indeed.com", glassdoor="portugal-{q}-jobs-SRCH_IL.0,8_IN195_KO9,{n}.htm",
               cities=["Lisbon", "Porto"], muse=["Lisbon, Portugal"], wellfound="portugal", seek=None,
               lang_hints=["desenvolvedor", "programador", "engenheiro"]),
    "IT": dict(name="Italy", flag="\U0001F1EE\U0001F1F9", aliases=["italy", "italia", "it"],
               linkedin="Italy", indeed="it.indeed.com", glassdoor="italy-{q}-jobs-SRCH_IL.0,5_IN120_KO6,{n}.htm",
               cities=["Milan", "Rome", "Turin"], muse=["Milan, Italy", "Rome, Italy"], wellfound="italy", seek=None,
               lang_hints=["sviluppatore", "programmatore", "ingegnere"]),
    "PL": dict(name="Poland", flag="\U0001F1F5\U0001F1F1", aliases=["poland", "polska", "pl"],
               linkedin="Poland", indeed="pl.indeed.com", glassdoor="poland-{q}-jobs-SRCH_IL.0,6_IN193_KO7,{n}.htm",
               cities=["Warsaw", "Krakow", "Wroclaw"], muse=["Warsaw, Poland"], wellfound="poland", seek=None,
               lang_hints=["programista", "inżynier", "developer"]),
    "BE": dict(name="Belgium", flag="\U0001F1E7\U0001F1EA", aliases=["belgium", "belgie", "belgique", "be"],
               linkedin="Belgium", indeed="be.indeed.com", glassdoor="belgium-{q}-jobs-SRCH_IL.0,7_IN25_KO8,{n}.htm",
               cities=["Brussels", "Antwerp", "Ghent"], muse=["Brussels, Belgium"], wellfound="belgium", seek=None,
               lang_hints=["ontwikkelaar", "développeur"]),
    "AE": dict(name="United Arab Emirates", flag="\U0001F1E6\U0001F1EA", aliases=["uae", "dubai", "united arab emirates", "ae", "abu dhabi"],
               linkedin="United Arab Emirates", indeed="ae.indeed.com", glassdoor="dubai-{q}-jobs-SRCH_IL.0,5_IC2204305_KO6,{n}.htm",
               cities=["Dubai", "Abu Dhabi"], muse=["Dubai, United Arab Emirates"], wellfound="dubai", seek=None, lang_hints=[]),
    "CA": dict(name="Canada", flag="\U0001F1E8\U0001F1E6", aliases=["canada", "ca"],
               linkedin="Canada", indeed="ca.indeed.com", glassdoor="canada-{q}-jobs-SRCH_IL.0,6_IN3_KO7,{n}.htm",
               cities=["Toronto", "Vancouver", "Montreal"], muse=["Toronto, Canada", "Vancouver, Canada"], wellfound="canada", seek=None,
               lang_hints=["développeur"]),
    "US": dict(name="United States", flag="\U0001F1FA\U0001F1F8", aliases=["usa", "us", "united states", "america"],
               linkedin="United States", indeed="www.indeed.com", glassdoor="united-states-{q}-jobs-SRCH_IL.0,13_IN1_KO14,{n}.htm",
               cities=["New York", "San Francisco", "Seattle", "Austin"], muse=["New York, NY", "San Francisco, CA", "Seattle, WA"],
               wellfound="united-states", seek=None, lang_hints=[]),
    "KR": dict(name="South Korea", flag="\U0001F1F0\U0001F1F7", aliases=["korea", "south korea", "kr"],
               linkedin="South Korea", indeed="kr.indeed.com", glassdoor="south-korea-{q}-jobs-SRCH_IL.0,11_IN135_KO12,{n}.htm",
               cities=["Seoul"], muse=["Seoul, South Korea"], wellfound="south-korea", seek=None, lang_hints=["개발자", "엔지니어"]),
}

REMOTE = "REMOTE"
REMOTE_META = dict(name="Remote / Worldwide", flag="\U0001F310")

# Words that identify a country inside free-text locations (remote job boards).
COUNTRY_WORDS = {
    "DE": ["germany", "deutschland", "berlin", "munich", "münchen", "hamburg", "frankfurt", "stuttgart", "cologne", "köln", "dach"],
    "NL": ["netherlands", "nederland", "holland", "amsterdam", "rotterdam", "utrecht", "eindhoven", "the hague", "den haag", "benelux"],
    "ES": ["spain", "españa", "espana", "madrid", "barcelona", "valencia", "malaga", "málaga", "sevilla", "seville", "bilbao"],
    "FI": ["finland", "suomi", "helsinki", "espoo", "tampere", "oulu", "turku", "nordics", "nordic"],
    "AU": ["australia", "sydney", "melbourne", "brisbane", "perth", "adelaide", "canberra", "anz"],
    "JP": ["japan", "tokyo", "osaka", "kyoto", "fukuoka", "nagoya", "日本", "東京"],
    "TH": ["thailand", "bangkok", "chiang mai", "phuket", "กรุงเทพ"],
    "IN": ["india", "bangalore", "bengaluru", "hyderabad", "pune", "gurgaon", "gurugram", "noida", "mumbai", "chennai", "delhi", "kolkata"],
    "SG": ["singapore"], "MY": ["malaysia", "kuala lumpur"], "HK": ["hong kong"], "NZ": ["new zealand", "auckland", "wellington"],
    "GB": ["united kingdom", "london", "manchester", "edinburgh", " uk", "uk,", "uk ", "england", "scotland"],
    "IE": ["ireland", "dublin"], "FR": ["france", "paris", "lyon"], "SE": ["sweden", "stockholm", "gothenburg"],
    "NO": ["norway", "oslo"], "DK": ["denmark", "copenhagen"], "CH": ["switzerland", "zurich", "zürich", "geneva"],
    "AT": ["austria", "vienna", "wien"], "PT": ["portugal", "lisbon", "lisboa", "porto"], "IT": ["italy", "milan", "milano", "rome", "roma"],
    "PL": ["poland", "warsaw", "krakow", "kraków", "wroclaw"], "BE": ["belgium", "brussels", "antwerp"],
    "AE": ["united arab emirates", "dubai", "abu dhabi", "uae"], "CA": ["canada", "toronto", "vancouver", "montreal"],
    "US": ["united states", "usa", "u.s.", "new york", "san francisco", "seattle", "austin", "california"],
    "KR": ["korea", "seoul"],
}

# Regions named by remote boards -> countries they cover (only used to attach remote jobs to the user's countries)
REGION_WORDS = {
    "europe": ["DE", "NL", "ES", "FI", "GB", "IE", "FR", "SE", "NO", "DK", "CH", "AT", "PT", "IT", "PL", "BE"],
    "eu": ["DE", "NL", "ES", "FI", "IE", "FR", "SE", "DK", "AT", "PT", "IT", "PL", "BE"],
    "emea": ["DE", "NL", "ES", "FI", "GB", "IE", "FR", "SE", "NO", "DK", "CH", "AT", "PT", "IT", "PL", "BE", "AE"],
    "european": ["DE", "NL", "ES", "FI", "GB", "IE", "FR", "SE", "NO", "DK", "CH", "AT", "PT", "IT", "PL", "BE"],
    "cet": ["DE", "NL", "ES", "FR", "SE", "NO", "DK", "CH", "AT", "IT", "PL", "BE"],
    "apac": ["AU", "JP", "TH", "SG", "MY", "HK", "NZ", "IN", "KR"],
    "asia": ["JP", "TH", "SG", "MY", "HK", "IN", "KR"],
    "asia pacific": ["AU", "JP", "TH", "SG", "MY", "HK", "NZ", "IN", "KR"],
    "oceania": ["AU", "NZ"],
    "nordics": ["FI", "SE", "NO", "DK"],
    "benelux": ["NL", "BE"],
    "dach": ["DE", "AT", "CH"],
}


def resolve_country(text):
    """Map a user-typed country name/code to an ISO2 key, or None."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if t.upper() in COUNTRIES:
        return t.upper()
    if t in ("remote", "worldwide", "anywhere"):
        return REMOTE
    for code, meta in COUNTRIES.items():
        if t == meta["name"].lower() or t in meta["aliases"]:
            return code
    return None


def country_name(code):
    if code == REMOTE:
        return REMOTE_META["name"]
    return COUNTRIES.get(code, {}).get("name", code)


def country_flag(code):
    if code == REMOTE:
        return REMOTE_META["flag"]
    return COUNTRIES.get(code, {}).get("flag", "")


def countries_in_text(text, candidates=None):
    """Return the ISO2 codes whose city/country words appear in `text`."""
    t = " " + (text or "").lower() + " "
    hits = []
    for code, words in COUNTRY_WORDS.items():
        if candidates and code not in candidates:
            continue
        for w in words:
            if w in t:
                hits.append(code)
                break
    return hits


def regions_in_text(text, candidates=None):
    t = (text or "").lower()
    out = []
    for region, codes in REGION_WORDS.items():
        if region in t.split() or (" " in region and region in t) or t.strip() == region:
            for c in codes:
                if (not candidates or c in candidates) and c not in out:
                    out.append(c)
    if any(w in t for w in ("worldwide", "anywhere", "global", "remote (worldwide)", "world wide")):
        for c in (candidates or []):
            if c not in out:
                out.append(c)
    return out
