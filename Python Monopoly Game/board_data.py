"""The Monopoly board: one canonical rules dataset plus three name themes.

How this file is organised
--------------------------
- Every Monopoly board -- US, UK, or anything else -- has the *same* 40 spaces
  in the *same* order with the *same* prices and rents. Only the names change.
- So `BOARD_TEMPLATE` stores the rules data once (kind, price, rent, ...), and
  `THEMES` stores just the 40 display names for each theme.
- `build_board(theme)` stitches the two together into a list of `Space`
  objects the rest of the game uses.

Beginner note:
- `rent` for a street is a tuple of six numbers: rent with 0/1/2/3/4 houses and
  then with a hotel. The "0 houses" entry is the *base* rent; when a player owns
  the whole colour group but has not built yet, the engine doubles that base
  rent itself -- the doubling is a rule, not stored data.
"""

from __future__ import annotations

from dataclasses import dataclass


# --------------------------------------------------------------------------
# Space data model
# --------------------------------------------------------------------------
@dataclass
class Space:
    """One of the 40 fixed spaces on the board.

    The fields that do not apply to a space simply stay at their defaults
    (for example a tax space has no `rent` and a street has no `tax`).
    """

    position: int            # 0-39, clockwise from GO
    kind: str                # see KINDS below
    name: str                # themed display name
    group: str = ""          # colour group name, streets only
    price: int = 0           # purchase price (street / railroad / utility)
    rent: tuple = ()         # streets only: (base, 1h, 2h, 3h, 4h, hotel)
    house_cost: int = 0      # cost of one house/hotel, streets only
    mortgage: int = 0        # cash raised by mortgaging (ownable spaces)
    tax: int = 0             # amount due, tax spaces only

    @property
    def is_ownable(self) -> bool:
        """True for spaces a player can buy: streets, railroads, utilities."""
        return self.kind in ("street", "railroad", "utility")


# The ten kinds of space, for reference.
KINDS = (
    "go", "street", "railroad", "utility", "tax",
    "chance", "chest", "jail", "free_parking", "go_to_jail",
)

# Railroads and utilities share fixed prices, so they are named once here.
RAILROAD_PRICE, RAILROAD_MORTGAGE = 200, 100
UTILITY_PRICE, UTILITY_MORTGAGE = 150, 75


# --------------------------------------------------------------------------
# Small builders -- keep the big board list below readable
# --------------------------------------------------------------------------
def _street(group, price, rent, house_cost, mortgage):
    """Build the rules data for one street (colour-group) space."""
    return dict(kind="street", group=group, price=price, rent=tuple(rent),
                house_cost=house_cost, mortgage=mortgage)


def _rail():
    """Build the rules data for one railroad space."""
    return dict(kind="railroad", price=RAILROAD_PRICE, mortgage=RAILROAD_MORTGAGE)


def _util():
    """Build the rules data for one utility space."""
    return dict(kind="utility", price=UTILITY_PRICE, mortgage=UTILITY_MORTGAGE)


# --------------------------------------------------------------------------
# The canonical board -- 40 spaces of rules data, positions 0-39
# --------------------------------------------------------------------------
BOARD_TEMPLATE = [
    dict(kind="go"),                                                       # 0
    _street("brown", 60, [2, 10, 30, 90, 160, 250], 50, 30),               # 1
    dict(kind="chest"),                                                    # 2
    _street("brown", 60, [4, 20, 60, 180, 320, 450], 50, 30),              # 3
    dict(kind="tax", tax=200),                                             # 4  Income Tax
    _rail(),                                                               # 5
    _street("light_blue", 100, [6, 30, 90, 270, 400, 550], 50, 50),        # 6
    dict(kind="chance"),                                                   # 7
    _street("light_blue", 100, [6, 30, 90, 270, 400, 550], 50, 50),        # 8
    _street("light_blue", 120, [8, 40, 100, 300, 450, 600], 50, 60),       # 9
    dict(kind="jail"),                                                     # 10
    _street("pink", 140, [10, 50, 150, 450, 625, 750], 100, 70),           # 11
    _util(),                                                               # 12
    _street("pink", 140, [10, 50, 150, 450, 625, 750], 100, 70),           # 13
    _street("pink", 160, [12, 60, 180, 500, 700, 900], 100, 80),           # 14
    _rail(),                                                               # 15
    _street("orange", 180, [14, 70, 200, 550, 750, 950], 100, 90),         # 16
    dict(kind="chest"),                                                    # 17
    _street("orange", 180, [14, 70, 200, 550, 750, 950], 100, 90),         # 18
    _street("orange", 200, [16, 80, 220, 600, 800, 1000], 100, 100),       # 19
    dict(kind="free_parking"),                                             # 20
    _street("red", 220, [18, 90, 250, 700, 875, 1050], 150, 110),          # 21
    dict(kind="chance"),                                                   # 22
    _street("red", 220, [18, 90, 250, 700, 875, 1050], 150, 110),          # 23
    _street("red", 240, [20, 100, 300, 750, 925, 1100], 150, 120),         # 24
    _rail(),                                                               # 25
    _street("yellow", 260, [22, 110, 330, 800, 975, 1150], 150, 130),      # 26
    _street("yellow", 260, [22, 110, 330, 800, 975, 1150], 150, 130),      # 27
    _util(),                                                               # 28
    _street("yellow", 280, [24, 120, 360, 850, 1025, 1200], 150, 140),     # 29
    dict(kind="go_to_jail"),                                               # 30
    _street("green", 300, [26, 130, 390, 900, 1100, 1275], 200, 150),      # 31
    _street("green", 300, [26, 130, 390, 900, 1100, 1275], 200, 150),      # 32
    dict(kind="chest"),                                                    # 33
    _street("green", 320, [28, 150, 450, 1000, 1200, 1400], 200, 160),     # 34
    _rail(),                                                               # 35
    dict(kind="chance"),                                                   # 36
    _street("dark_blue", 350, [35, 175, 500, 1100, 1300, 1500], 200, 175), # 37
    dict(kind="tax", tax=100),                                             # 38  Luxury Tax
    _street("dark_blue", 400, [50, 200, 600, 1400, 1700, 2000], 200, 200), # 39
]

# The eight colour groups, smallest to largest rent, with their member spaces.
COLOR_GROUPS = {
    "brown": (1, 3),
    "light_blue": (6, 8, 9),
    "pink": (11, 13, 14),
    "orange": (16, 18, 19),
    "red": (21, 23, 24),
    "yellow": (26, 27, 29),
    "green": (31, 32, 34),
    "dark_blue": (37, 39),
}
RAILROAD_POSITIONS = (5, 15, 25, 35)
UTILITY_POSITIONS = (12, 28)


# --------------------------------------------------------------------------
# Themes -- each is 40 display names lined up with the positions above
# --------------------------------------------------------------------------
# The corner / card / tax spaces keep their standard labels in every theme;
# only the 28 ownable spaces really change.
THEMES = {
    "classic": {
        "name": "Classic US",
        "names": [
            "GO", "Mediterranean Avenue", "Community Chest", "Baltic Avenue",
            "Income Tax", "Reading Railroad", "Oriental Avenue", "Chance",
            "Vermont Avenue", "Connecticut Avenue", "Jail", "St. Charles Place",
            "Electric Company", "States Avenue", "Virginia Avenue",
            "Pennsylvania Railroad", "St. James Place", "Community Chest",
            "Tennessee Avenue", "New York Avenue", "Free Parking",
            "Kentucky Avenue", "Chance", "Indiana Avenue", "Illinois Avenue",
            "B. & O. Railroad", "Atlantic Avenue", "Ventnor Avenue",
            "Water Works", "Marvin Gardens", "Go To Jail", "Pacific Avenue",
            "North Carolina Avenue", "Community Chest", "Pennsylvania Avenue",
            "Short Line Railroad", "Chance", "Park Place", "Luxury Tax",
            "Boardwalk",
        ],
    },
    "london": {
        "name": "London",
        "names": [
            "GO", "Old Kent Road", "Community Chest", "Whitechapel Road",
            "Income Tax", "King's Cross Station", "The Angel Islington",
            "Chance", "Euston Road", "Pentonville Road", "Jail", "Pall Mall",
            "Electric Company", "Whitehall", "Northumberland Avenue",
            "Marylebone Station", "Bow Street", "Community Chest",
            "Marlborough Street", "Vine Street", "Free Parking", "Strand",
            "Chance", "Fleet Street", "Trafalgar Square", "Fenchurch St. Station",
            "Leicester Square", "Coventry Street", "Water Works", "Piccadilly",
            "Go To Jail", "Regent Street", "Oxford Street", "Community Chest",
            "Bond Street", "Liverpool St. Station", "Chance", "Park Lane",
            "Luxury Tax", "Mayfair",
        ],
    },
    "landmarks": {
        "name": "World Landmarks",
        "names": [
            "GO", "Hadrian's Wall", "Community Chest", "Loch Ness", "Income Tax",
            "Heathrow Airport", "Brandenburg Gate", "Chance", "Edinburgh Castle",
            "Table Mountain", "Jail", "Chichen Itza", "Hoover Dam", "Mount Fuji",
            "The Acropolis", "JFK Airport", "Petra", "Community Chest",
            "Angkor Wat", "The Alhambra", "Free Parking", "Sydney Opera House",
            "Chance", "Stonehenge", "Sagrada Familia", "Changi Airport",
            "Golden Gate Bridge", "Christ the Redeemer", "Niagara Falls",
            "Statue of Liberty", "Go To Jail", "The Colosseum", "Machu Picchu",
            "Community Chest", "Great Wall of China", "Dubai Airport", "Chance",
            "Taj Mahal", "Luxury Tax", "Eiffel Tower",
        ],
    },
    "delhi_ncr": {
        "name": "Delhi-NCR",
        "names": [
            "GO", "Najafgarh", "Community Chest", "Bawana", "Income Tax",
            "New Delhi Station", "Mehrauli", "Chance", "Burari",
            "Yamuna Vihar", "Jail", "Rohini", "BSES Power", "Pitampura",
            "Dwarka", "Old Delhi Junction", "Lajpat Nagar", "Community Chest",
            "Karol Bagh", "Sarojini Nagar", "Free Parking", "Khan Market",
            "Chance", "Hauz Khas", "Connaught Place", "Hazrat Nizamuddin",
            "Cyber Hub Gurgaon", "Sector 18 Noida", "Delhi Jal Board",
            "Greater Kailash", "Go To Jail", "Vasant Vihar", "Chanakyapuri",
            "Community Chest", "Sundar Nagar", "Anand Vihar Terminal",
            "Chance", "Golf Links", "Luxury Tax", "Lutyens' Delhi",
        ],
    },
    "mumbai": {
        "name": "Mumbai",
        "names": [
            "GO", "Mankhurd", "Community Chest", "Govandi", "Income Tax",
            "CST Mumbai", "Bhandup", "Chance", "Mulund", "Vikhroli",
            "Jail", "Goregaon", "Adani Electricity", "Malad", "Kandivali",
            "Bandra Terminus", "Dadar", "Community Chest", "Mahim",
            "Matunga", "Free Parking", "Andheri West", "Chance", "Vile Parle",
            "Santacruz", "Borivali Station", "Powai", "Worli",
            "BMC Water Works", "Lower Parel", "Go To Jail", "Bandra West",
            "Juhu", "Community Chest", "Pali Hill", "Lokmanya Tilak Terminus",
            "Chance", "Malabar Hill", "Luxury Tax", "Altamount Road",
        ],
    },
    "chennai": {
        "name": "Chennai",
        "names": [
            "GO", "Pulianthope", "Community Chest", "Vyasarpadi", "Income Tax",
            "Chennai Central", "Perambur", "Chance", "Royapuram", "Tondiarpet",
            "Jail", "Triplicane", "TANGEDCO", "Egmore", "Chetpet",
            "Chennai Egmore", "T. Nagar", "Community Chest", "West Mambalam",
            "Saidapet", "Free Parking", "Nungambakkam", "Chance", "Anna Nagar",
            "Mylapore", "Tambaram Junction", "Adyar", "Velachery",
            "Chennai Metro Water", "Besant Nagar", "Go To Jail", "Alwarpet",
            "RA Puram", "Community Chest", "Kilpauk", "Park Town", "Chance",
            "Boat Club Road", "Luxury Tax", "Poes Garden",
        ],
    },
    "kolkata": {
        "name": "Kolkata",
        "names": [
            "GO", "Topsia", "Community Chest", "Tangra", "Income Tax",
            "Howrah Junction", "Beleghata", "Chance", "Picnic Garden",
            "Tiljala", "Jail", "Jadavpur", "CESC Power", "Garia", "Dum Dum",
            "Sealdah", "Gariahat", "Community Chest", "Hatibagan", "New Market",
            "Free Parking", "Park Street", "Chance", "Camac Street",
            "Esplanade", "Kolkata Terminus", "Salt Lake", "Ballygunge",
            "KMC Water", "Tollygunge", "Go To Jail", "Bhawanipur",
            "Lake Gardens", "Community Chest", "Lansdowne", "Shalimar",
            "Chance", "Alipore", "Luxury Tax", "Belvedere Estate",
        ],
    },
    "chandigarh": {
        "name": "Chandigarh Tricity",
        "names": [
            "GO", "Industrial Area Phase I", "Community Chest", "Mauli Jagran",
            "Income Tax", "Chandigarh Junction", "Maloya", "Chance", "Dhanas",
            "Daddumajra", "Jail", "Manimajra", "UT Electricity",
            "Mohali Phase 5", "Panchkula Sector 20", "Mohali Station",
            "Sector 22 Market", "Community Chest", "Sector 35 Market",
            "Sector 15", "Free Parking", "Sector 17 Plaza", "Chance",
            "Elante Mall", "Sector 9", "Panchkula Junction", "Sector 8",
            "Sector 18", "Tricity Water Board", "Panchkula Sector 9",
            "Go To Jail", "Sector 5", "Sector 11", "Community Chest",
            "Mohali Phase 7", "S.A.S Nagar Halt", "Chance", "Sector 2",
            "Luxury Tax", "Sector 4",
        ],
    },
    "bengaluru": {
        "name": "Bengaluru",
        "names": [
            "GO", "Yeshwanthpur", "Community Chest", "Madiwala", "Income Tax",
            "KSR Bengaluru Junction", "Bommanahalli", "Chance", "Banashankari",
            "Marathahalli", "Jail", "HSR Layout", "BESCOM", "Electronic City",
            "Hennur", "Yesvantpur Junction", "Jayanagar", "Community Chest",
            "JP Nagar", "BTM Layout", "Free Parking", "Indiranagar", "Chance",
            "Koramangala", "MG Road", "Bengaluru Cantonment", "Whitefield",
            "Domlur", "BWSSB", "Frazer Town", "Go To Jail", "Brigade Road",
            "Ulsoor", "Community Chest", "Cunningham Road", "Whitefield Station",
            "Chance", "Sadashivnagar", "Luxury Tax", "Lavelle Road",
        ],
    },
    "hyderabad": {
        "name": "Hyderabad",
        "names": [
            "GO", "Old City Charminar", "Community Chest", "Falaknuma",
            "Income Tax", "Secunderabad Junction", "LB Nagar", "Chance",
            "Uppal", "Dilsukhnagar", "Jail", "Kukatpally", "TSSPDCL",
            "Miyapur", "ECIL", "Hyderabad Deccan", "Ameerpet",
            "Community Chest", "SR Nagar", "Punjagutta", "Free Parking",
            "Hitec City", "Chance", "Madhapur", "Begumpet", "Kacheguda",
            "Gachibowli", "Kondapur", "HMWSSB", "Manikonda", "Go To Jail",
            "Somajiguda", "Film Nagar", "Community Chest", "Khairatabad",
            "Lingampally", "Chance", "Banjara Hills", "Luxury Tax",
            "Jubilee Hills",
        ],
    },
    "pune": {
        "name": "Pune",
        "names": [
            "GO", "Yerwada", "Community Chest", "Vishrantwadi", "Income Tax",
            "Pune Junction", "Hadapsar", "Chance", "Magarpatta", "Kharadi",
            "Jail", "Kothrud", "MSEDCL Power", "Karve Nagar", "Warje",
            "Khadki Station", "Camp", "Community Chest", "Deccan Gymkhana",
            "MG Road Pune", "Free Parking", "JM Road", "Chance", "FC Road",
            "SB Road", "Shivajinagar", "Koregaon Park", "Aundh", "PCMC Water",
            "Baner", "Go To Jail", "Kalyani Nagar", "Viman Nagar",
            "Community Chest", "Wadgaon Sheri", "Hadapsar Station", "Chance",
            "Boat Club Road Pune", "Luxury Tax", "Prabhat Road",
        ],
    },
    "lucknow": {
        "name": "Lucknow",
        "names": [
            "GO", "Daliganj", "Community Chest", "Telibagh", "Income Tax",
            "Charbagh", "Chinhat", "Chance", "Mahanagar", "Indira Nagar",
            "Jail", "Aliganj", "MVVNL Power", "Aishbagh", "Rajajipuram",
            "Lucknow Junction", "Aminabad", "Community Chest", "Chowk",
            "Bhul Bhulaiya", "Free Parking", "Hazratganj", "Chance",
            "Sapru Marg", "Janpath Market", "Gomti Nagar Station",
            "Vibhuti Khand", "Vipul Khand", "Jal Sansthan", "Vinay Khand",
            "Go To Jail", "Mall Avenue", "Cantt Road", "Community Chest",
            "Sushant Golf City", "Aishbagh Junction", "Chance",
            "Butler Palace Colony", "Luxury Tax", "Gulistan Colony",
        ],
    },
    "goa": {
        "name": "Goa",
        "names": [
            "GO", "Vasco", "Community Chest", "Sanvordem", "Income Tax",
            "Madgaon Junction", "Mapusa", "Chance", "Ponda", "Pernem", "Jail",
            "Margao", "Goa Electricity Dept", "Bicholim", "Curchorem",
            "Karmali", "Anjuna", "Community Chest", "Baga", "Vagator",
            "Free Parking", "Old Goa", "Chance", "Fontainhas", "Panjim",
            "Vasco da Gama", "Dona Paula", "Sinquerim", "PWD Water Goa",
            "Morjim", "Go To Jail", "Ashvem", "Mandrem", "Community Chest",
            "Arambol", "Thivim", "Chance", "Cabo de Rama", "Luxury Tax",
            "Fort Aguada",
        ],
    },
}

# A stable order for showing themes in the setup menu.
THEME_ORDER = (
    "classic", "london", "landmarks",
    "delhi_ncr", "mumbai", "chennai", "kolkata", "chandigarh",
    "bengaluru", "hyderabad", "pune", "lucknow", "goa",
)


def build_board(theme_key: str) -> list[Space]:
    """Combine the rules template with a theme's names into 40 `Space` objects.

    `theme_key` must be one of `THEME_ORDER`. Any unknown key falls back to the
    classic board so a corrupt save can never crash the game.
    """
    theme = THEMES.get(theme_key, THEMES["classic"])
    names = theme["names"]
    board: list[Space] = []
    for position, template in enumerate(BOARD_TEMPLATE):
        # `template` holds the rules data; `**template` spreads it into Space.
        board.append(Space(position=position, name=names[position], **template))
    return board
