import json
from pathlib import Path
from os import makedirs
from deezer import TrackFormats
import deemix.utils.localpaths as localpaths

"""Should the lib overwrite files?"""
class OverwriteOption():
    OVERWRITE = 'y' # Yes, overwrite the file
    DONT_OVERWRITE = 'n' # No, don't overwrite the file
    DONT_CHECK_EXT = 'e' # No, and don't check for extensions
    KEEP_BOTH = 'b' # No, and keep both files
    ONLY_TAGS = 't' # Overwrite only the tags

"""What should I do with featured artists?"""
class FeaturesOption():
    NO_CHANGE = "0" # Do nothing
    REMOVE_TITLE = "1" # Remove from track title
    REMOVE_TITLE_ALBUM = "3" # Remove from track title and album title
    MOVE_TITLE = "2" # Move to track title

DEFAULTS = {
  "downloadLocation": "",
  "tracknameTemplate": "%artist% - %title%",
  "albumTracknameTemplate": "%tracknumber% - %title%",
  "playlistTracknameTemplate": "%position% - %artist% - %title%",
  "createPlaylistFolder": True,
  "playlistNameTemplate": "%playlist%",
  "createArtistFolder": False,
  "artistNameTemplate": "%artist%",
  "createAlbumFolder": True,
  "albumNameTemplate": "%artist% - %album%",
  "createCDFolder": True,
  "createStructurePlaylist": False,
  "createSingleFolder": False,
  "padTracks": True,
  "paddingSize": "0",
  "illegalCharacterReplacer": "_",
  "queueConcurrency": 3,
  "maxBitrate": str(TrackFormats.MP3_320),
  "fallbackBitrate": True,
  "fallbackSearch": False,
  "logErrors": True,
  "logSearched": False,
  "saveDownloadQueue": False,
  "overwriteFile": OverwriteOption.DONT_OVERWRITE,
  "createM3U8File": False,
  "playlistFilenameTemplate": "playlist",
  "syncedLyrics": False,
  "embeddedArtworkSize": 800,
  "embeddedArtworkPNG": False,
  "localArtworkSize": 1400,
  "localArtworkFormat": "jpg",
  "saveArtwork": True,
  "coverImageTemplate": "cover",
  "saveArtworkArtist": False,
  "artistImageTemplate": "folder",
  "jpegImageQuality": 80,
  "dateFormat": "Y-M-D",
  "albumVariousArtists": True,
  "removeAlbumVersion": False,
  "removeDuplicateArtists": False,
  "tagsLanguage": "",
  "featuredToTitle": FeaturesOption.NO_CHANGE,
  "titleCasing": "nothing",
  "artistCasing": "nothing",
  "executeCommand": "",
  "tags": {
    "title": True,
    "artist": True,
    "album": True,
    "cover": True,
    "trackNumber": True,
    "trackTotal": False,
    "discNumber": True,
    "discTotal": False,
    "albumArtist": True,
    "genre": True,
    "year": True,
    "date": True,
    "explicit": False,
    "isrc": True,
    "length": True,
    "barcode": True,
    "bpm": True,
    "replayGain": False,
    "label": True,
    "lyrics": False,
    "syncedLyrics": False,
    "copyright": False,
    "composer": False,
    "involvedPeople": False,
    "source": False,
    "savePlaylistAsCompilation": False,
    "useNullSeparator": False,
    "saveID3v1": True,
    "multiArtistSeparator": "default",
    "singleAlbumArtist": False,
    "coverDescriptionUTF8": False
  }
}

def saveSettings(settings, configFolder=None):
    configFolder = Path(configFolder or localpaths.getConfigFolder())
    makedirs(configFolder, exist_ok=True) # Create config folder if it doesn't exsist

    with open(configFolder / 'config.json', 'w') as configFile:
        json.dump(settings, configFile, indent=2)

def loadSettings(configFolder=None):
    configFolder = Path(configFolder or localpaths.getConfigFolder())
    makedirs(configFolder, exist_ok=True) # Create config folder if it doesn't exsist
    if not (configFolder / 'config.json').is_file(): saveSettings(DEFAULTS, configFolder) # Create config file if it doesn't exsist

    # Read config file
    with open(configFolder / 'config.json', 'r') as configFile:
        settings = json.load(configFile)

    if checkSettings(settings) > 0: saveSettings(settings) # Check the settings and save them if something changed
    return settings

def checkSettings(settings):
    changes = 0
    for set in DEFAULTS:
        if not set in settings or type(settings[set]) != type(DEFAULTS[set]):
            settings[set] = DEFAULTS[set]
            changes += 1
    for set in DEFAULTS['tags']:
        if not set in settings['tags'] or type(settings['tags'][set]) != type(DEFAULTS['tags'][set]):
            settings['tags'][set] = DEFAULTS['tags'][set]
            changes += 1
    if settings['downloadLocation'] == "":
        settings['downloadLocation'] = DEFAULTS['downloadLocation']
        changes += 1
    for template in ['tracknameTemplate', 'albumTracknameTemplate', 'playlistTracknameTemplate', 'playlistNameTemplate', 'artistNameTemplate', 'albumNameTemplate', 'playlistFilenameTemplate', 'coverImageTemplate', 'artistImageTemplate', 'paddingSize']:
        if settings[template] == "":
            settings[template] = DEFAULTS[template]
            changes += 1
    return changes
