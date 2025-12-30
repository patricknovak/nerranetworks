"""
Shared pronunciation dictionary for all podcasts.
This module provides pronunciation fixes for acronyms, names, and terms
that TTS engines commonly mispronounce.
"""

import re
from typing import Dict


# ========================== SHARED PRONUNCIATION DICTIONARIES ==========================

# Common acronyms that should be spelled letter-by-letter
COMMON_ACRONYMS: Dict[str, str] = {
    # AI and ML
    "AI": "A I",
    "ML": "M L",
    "OpenAI": "Open A.I.",
    "GenAI": "Gen A.I.",
    # Space agencies and missions
    "NASA": "N A S A",
    "ESA": "E S A",
    "JAXA": "J A X A",
    "ISS": "I S S",
    "JWST": "J W S T",
    "HST": "H S T",
    "SLS": "S L S",
    "FAA": "F A A",
    "ULA": "U L A",
    "SpaceX": "Space X",
    "LRO": "L R O",
    "OSIRIS-REx": "O S I R I S R E X",
    "DART": "D A R T",
    "PSYCHE": "P S Y C H E",
    # Biology and health
    "DNA": "D N A",
    "RNA": "R N A",
    "CRISPR": "C R I S P R",
    "CRISPR-Cas9": "C R I S P R Cas 9",
    "mRNA": "m R N A",
    "FDA": "F D A",
    "NIH": "N I H",
    "WHO": "W H O",
    # Hockey leagues
    "NHL": "N H L",
    "NHLPA": "N H L P A",
    "AHL": "A H L",
    "WHL": "W H L",
    "OHL": "O H L",
    "QMJHL": "Q M J H L",
    "ECHL": "E C H L",
    "USHL": "U S H L",
    "NCAA": "N C A A",
    # Tesla and EVs
    "TSLA": "T S L A",
    "FSD": "F S D",
    "HW3": "H W 3",
    "HW4": "H W 4",
    "AI5": "A I 5",
    "4680": "4 6 8 0",
    "EV": "E V",
    "EVs": "E V s",  # Fixed: spell out "s" separately to prevent "E.V.S" pronunciation
    "BEV": "B E V",
    "PHEV": "P H E V",
    "ICE": "I C E",
    "NHTSA": "N H T S A",
    "OTA": "O T A",
    "LFP": "L F P",
}

# Hockey-specific terms (for Lube Change)
HOCKEY_TERMS: Dict[str, str] = {
    "PP": "power play",
    "PK": "penalty kill",
    "SHG": "short-handed goal",
    "PPG": "power play goal",
    "ENG": "empty net goal",
    "OT": "overtime",
    "3v3": "three on three",
    "5v5": "five on five",
    "4v4": "four on four",
    "GAA": "goals against average",
    "SV%": "save percentage",
    "SV": "save percentage",
    "PIM": "penalty minutes",
    "TOI": "time on ice",
    "CF%": "Corsi for percentage",
    "xGF": "expected goals for",
    "xGA": "expected goals against",
    "HDCF": "high danger chances for",
    "HDCA": "high danger chances against",
    "PDO": "P D O",
    "GF": "goals for",
    "GA": "goals against",
    "GF%": "goals for percentage",
    "LW": "left wing",
    "RW": "right wing",
    "OTL": "overtime loss",
    "PTS": "points",
    "GP": "games played",
    "+/-": "plus minus",
    "S%": "shooting percentage",
    "FO%": "faceoff percentage",
    "HIT": "hits",
    "BLK": "blocks",
    "TK": "takeaways",
    "GV": "giveaways",
}

# Common player names and pronunciations (Oilers-specific)
OILERS_PLAYER_NAMES: Dict[str, str] = {
    # Current players
    "Connor McDavid": "Connor Mc David",
    "McDavid": "Mc David",
    "Leon Draisaitl": "Lee on Dry sight el",
    "Draisaitl": "Dry sight el",
    "Ryan Nugent-Hopkins": "Ryan Nugent Hopkins",
    "Nugent-Hopkins": "Nugent Hopkins",
    "Nugent Hopkins": "Nugent Hopkins",
    "Zach Hyman": "Zach High man",
    "Hyman": "High man",
    "Evander Kane": "Ee van der Kane",
    "Kane": "Kane",
    "Warren Foegele": "Warren Foe glee",
    "Foegele": "Foe glee",
    "Ryan McLeod": "Ryan Mc Leod",
    "McLeod": "Mc Leod",
    "Derek Ryan": "Derek Ryan",
    "Mattias Janmark": "Mat tee as Jan mark",
    "Janmark": "Jan mark",
    "Connor Brown": "Connor Brown",
    "Adam Henrique": "Adam Hen reek",
    "Henrique": "Hen reek",
    "Corey Perry": "Corey Perry",
    "Sam Carrick": "Sam Car rick",
    "Carrick": "Car rick",
    "Sam Gagner": "Sam Gag ner",
    "Gagner": "Gag ner",
    "Dylan Holloway": "Dylan Hol low way",
    "Holloway": "Hol low way",
    "Darnell Nurse": "Dar nell Nurse",
    "Nurse": "Nurse",
    "Evan Bouchard": "Ee van Boo shard",
    "Bouchard": "Boo shard",
    "Mattias Ekholm": "Mat tee as Ek holm",
    "Ekholm": "Ek holm",
    "Cody Ceci": "Cody See see",
    "Ceci": "See see",
    "Brett Kulak": "Brett Koo lak",
    "Kulak": "Koo lak",
    "Vincent Desharnais": "Vin cent Desh ar nay",
    "Desharnais": "Desh ar nay",
    "Philip Broberg": "Philip Bro berg",
    "Broberg": "Bro berg",
    "Troy Stecher": "Troy Stech er",
    "Stecher": "Stech er",
    "Stuart Skinner": "Stu art Skin ner",
    "Skinner": "Skin ner",
    "Calvin Pickard": "Cal vin Pick ard",
    "Pickard": "Pick ard",
    "Jack Campbell": "Jack Camp bell",
    "Campbell": "Camp bell",
    # Coaches and Management
    "Kris Knoblauch": "Kris Nob lock",
    "Knoblauch": "Nob lock",
    "Jay Woodcroft": "Jay Wood croft",
    "Woodcroft": "Wood croft",
    "Ken Holland": "Ken Hol land",
    "Holland": "Hol land",
    "Jeff Jackson": "Jeff Jack son",
    "Jackson": "Jack son",
    "Glen Gulutzan": "Glen Gu lut zan",
    "Gulutzan": "Gu lut zan",
    "Mark Stuart": "Mark Stu art",
    "Stuart": "Stu art",
    "Paul Coffey": "Paul Cof fee",
    "Coffey": "Cof fee",
    # Historical players
    "Wayne Gretzky": "Wayne Gretz key",
    "Gretzky": "Gretz key",
    "Mark Messier": "Mark Mess ee ay",
    "Messier": "Mess ee ay",
    "Jari Kurri": "Jar ee Kur ee",
    "Kurri": "Kur ee",
    "Grant Fuhr": "Grant Fur",
    "Fuhr": "Fur",
    "Glenn Anderson": "Glen An der son",
    "Anderson": "An der son",
    "Kevin Lowe": "Kevin Low",
    "Lowe": "Low",
    "Esa Tikkanen": "Ee sa Tik ka nen",
    "Tikkanen": "Tik ka nen",
    "Craig MacTavish": "Craig Mac Tav ish",
    "MacTavish": "Mac Tav ish",
    "Charlie Huddy": "Charlie Hud dy",
    "Huddy": "Hud dy",
    "Randy Gregg": "Randy Gregg",
    "Gregg": "Gregg",
    "Dave Semenko": "Dave Se men ko",
    "Semenko": "Se men ko",
    "Dave Hunter": "Dave Hunt er",
    "Hunter": "Hunt er",
    "Pat Hughes": "Pat Hughes",
    "Hughes": "Hughes",
    "Jaroslav Pouzar": "Jar o slav Pou zar",
    "Pouzar": "Pou zar",
    "Mike Krushelnyski": "Mike Kru shel nis ki",
    "Krushelnyski": "Kru shel nis ki",
    "Steve Smith": "Steve Smith",
    "Smith": "Smith",
    "Jeff Beukeboom": "Jeff Boo ke boom",
    "Beukeboom": "Boo ke boom",
    "Bill Ranford": "Bill Ran ford",
    "Ranford": "Ran ford",
    "Andy Moog": "Andy Moog",
    "Moog": "Moog",
    "Ryan Smyth": "Ryan Smyth",
    "Smyth": "Smyth",
    "Doug Weight": "Doug Weight",
    "Weight": "Weight",
    "Jason Arnott": "Jason Ar nott",
    "Arnott": "Ar nott",
    "Curtis Joseph": "Curtis Jo seph",
    "Joseph": "Jo seph",
    "Tommy Salo": "Tommy Sa lo",
    "Salo": "Sa lo",
    "Ales Hemsky": "A les Hem ski",
    "Hemsky": "Hem ski",
    "Shawn Horcoff": "Shawn Hor coff",
    "Horcoff": "Hor coff",
    "Fernando Pisani": "Fer nan do Pi sa ni",
    "Pisani": "Pi sa ni",
    "Dwayne Roloson": "Dwayne Ro lo son",
    "Roloson": "Ro lo son",
}

# Common player names and pronunciations (generic - can be extended)
PLAYER_NAMES: Dict[str, str] = {
    # Can be extended with other player names as needed
}

# Common word pronunciations
WORD_PRONUNCIATIONS: Dict[str, str] = {
    "Planetterrian": "Planet terry an",
    "planetterrian": "planet terry an",
    "shootout": "shoot out",
    "shoot-out": "shoot out",
    "shoot out": "shoot out",
    "Robotaxis": "Robotaxi s",
    "Robotaxi": "Robotaxi",
    # Protect common words from being misread as acronyms
    # TTS engines sometimes read "who" as "W.H.O." - protect it
    "who": "who",
    "Who": "Who",
}


def apply_pronunciation_fixes(
    text: str,
    acronyms: Dict[str, str] = None,
    hockey_terms: Dict[str, str] = None,
    player_names: Dict[str, str] = None,
    oilers_player_names: Dict[str, str] = None,
    word_pronunciations: Dict[str, str] = None,
    use_zwj: bool = False,
) -> str:
    """
    Apply pronunciation fixes to text.
    
    Args:
        text: Input text to fix
        acronyms: Dictionary of acronyms to spell out (defaults to COMMON_ACRONYMS)
        hockey_terms: Dictionary of hockey terms (defaults to HOCKEY_TERMS)
        player_names: Dictionary of player name pronunciations (defaults to PLAYER_NAMES)
        word_pronunciations: Dictionary of word pronunciations (defaults to WORD_PRONUNCIATIONS)
        use_zwj: If True, use zero-width joiner; if False, use spaces (better for most TTS)
    
    Returns:
        Text with pronunciation fixes applied
    """
    if acronyms is None:
        acronyms = COMMON_ACRONYMS
    if hockey_terms is None:
        hockey_terms = HOCKEY_TERMS
    if player_names is None:
        player_names = PLAYER_NAMES
    if oilers_player_names is None:
        oilers_player_names = OILERS_PLAYER_NAMES
    if word_pronunciations is None:
        word_pronunciations = WORD_PRONUNCIATIONS
    
    # Merge Oilers player names with generic player names (Oilers take precedence)
    all_player_names = {**player_names, **oilers_player_names}
    
    # Zero-width joiner (only used if use_zwj=True)
    ZWJ = "\u2060" if use_zwj else " "
    
    # Fix acronyms (must be whole words)
    for acronym, spelled in acronyms.items():
        # Special handling for "WHO" - only match uppercase to avoid matching "who" (the word)
        if acronym == "WHO":
            pattern = rf'(?<!\w){re.escape(acronym)}(?!\w)'  # Case-sensitive for WHO
            flags = 0  # No case-insensitive flag
        else:
            pattern = rf'(?<!\w){re.escape(acronym)}(?!\w)'
            flags = re.IGNORECASE
        
        if ' ' in spelled:
            replacement = spelled
        elif use_zwj:
            replacement = ZWJ.join(list(spelled))
        else:
            replacement = " ".join(list(spelled))
        text = re.sub(pattern, replacement, text, flags=flags)
    
    # Fix hockey terms (phrases)
    for term, phrase in hockey_terms.items():
        pattern = rf'(?<!\w){re.escape(term)}(?!\w)'
        text = re.sub(pattern, phrase, text, flags=re.IGNORECASE)
    
    # Fix player names (Oilers + generic)
    for name, pronunciation in all_player_names.items():
        pattern = rf'(?<!\w){re.escape(name)}(?!\w)'
        text = re.sub(pattern, pronunciation, text, flags=re.IGNORECASE)
    
    # Fix word pronunciations
    for word, pronunciation in word_pronunciations.items():
        pattern = rf'(?<!\w){re.escape(word)}(?!\w)'
        text = re.sub(pattern, pronunciation, text, flags=re.IGNORECASE)
    
    return text

