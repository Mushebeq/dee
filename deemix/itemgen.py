import logging

from deemix.types.DownloadObjects import Single, Collection
from deezer.utils import map_user_playlist
from deezer.api import APIError
from deezer.gw import GWAPIError, LyricsStatus

logger = logging.getLogger('deemix')

class GenerationError(Exception):
    def __init__(self, link, message, errid=None):
        super().__init__()
        self.link = link
        self.message = message
        self.errid = errid

    def toDict(self):
        return {
            'link': self.link,
            'error': self.message,
            'errid': self.errid
        }

def generateTrackItem(dz, link_id, bitrate, trackAPI=None, albumAPI=None):
    # Check if is an isrc: url
    if str(link_id).startswith("isrc"):
        try:
            trackAPI = dz.api.get_track(link_id)
        except APIError as e:
            raise GenerationError("https://deezer.com/track/"+str(link_id), f"Wrong URL: {e}") from e
        if 'id' in trackAPI and 'title' in trackAPI:
            link_id = trackAPI['id']
        else:
            raise GenerationError("https://deezer.com/track/"+str(link_id), "Track ISRC is not available on deezer", "ISRCnotOnDeezer")

    # Get essential track info
    try:
        trackAPI_gw = dz.gw.get_track_with_fallback(link_id)
    except GWAPIError as e:
        message = "Wrong URL"
        # TODO: FIX
        # if "DATA_ERROR" in e: message += f": {e['DATA_ERROR']}"
        raise GenerationError("https://deezer.com/track/"+str(link_id), message) from e

    title = trackAPI_gw['SNG_TITLE'].strip()
    if trackAPI_gw.get('VERSION') and trackAPI_gw['VERSION'] not in trackAPI_gw['SNG_TITLE']:
        title += f" {trackAPI_gw['VERSION']}".strip()
    explicit = bool(int(trackAPI_gw.get('EXPLICIT_LYRICS', 0)))

    return Single({
        'type': 'track',
        'id': link_id,
        'bitrate': bitrate,
        'title': title,
        'artist': trackAPI_gw['ART_NAME'],
        'cover': f"https://e-cdns-images.dzcdn.net/images/cover/{trackAPI_gw['ALB_PICTURE']}/75x75-000000-80-0-0.jpg",
        'explicit': explicit,
        'single': {
            'trackAPI_gw': trackAPI_gw,
            'trackAPI': trackAPI,
            'albumAPI': albumAPI
        }
    })

def generateAlbumItem(dz, link_id, bitrate, rootArtist=None):
    # Get essential album info
    try:
        albumAPI = dz.api.get_album(link_id)
    except APIError as e:
        raise GenerationError("https://deezer.com/album/"+str(link_id), f"Wrong URL: {e}") from e

    if str(link_id).startswith('upc'): link_id = albumAPI['id']

    # Get extra info about album
    # This saves extra api calls when downloading
    albumAPI_gw = dz.gw.get_album(link_id)
    albumAPI['nb_disk'] = albumAPI_gw['NUMBER_DISK']
    albumAPI['copyright'] = albumAPI_gw['COPYRIGHT']
    albumAPI['root_artist'] = rootArtist

    # If the album is a single download as a track
    if albumAPI['nb_tracks'] == 1:
        return generateTrackItem(dz, albumAPI['tracks']['data'][0]['id'], bitrate, albumAPI=albumAPI)

    tracksArray = dz.gw.get_album_tracks(link_id)

    if albumAPI['cover_small'] is not None:
        cover = albumAPI['cover_small'][:-24] + '/75x75-000000-80-0-0.jpg'
    else:
        cover = f"https://e-cdns-images.dzcdn.net/images/cover/{albumAPI_gw['ALB_PICTURE']}/75x75-000000-80-0-0.jpg"

    totalSize = len(tracksArray)
    albumAPI['nb_tracks'] = totalSize
    collection = []
    for pos, trackAPI in enumerate(tracksArray, start=1):
        trackAPI['POSITION'] = pos
        trackAPI['SIZE'] = totalSize
        collection.append(trackAPI)

    explicit = albumAPI_gw.get('EXPLICIT_ALBUM_CONTENT', {}).get('EXPLICIT_LYRICS_STATUS', LyricsStatus.UNKNOWN) in [LyricsStatus.EXPLICIT, LyricsStatus.PARTIALLY_EXPLICIT]

    return Collection({
        'type': 'album',
        'id': link_id,
        'bitrate': bitrate,
        'title': albumAPI['title'],
        'artist': albumAPI['artist']['name'],
        'cover': cover,
        'explicit': explicit,
        'size': totalSize,
        'collection': {
            'tracks_gw': collection,
            'albumAPI': albumAPI
        }
    })

def generatePlaylistItem(dz, link_id, bitrate, playlistAPI=None, playlistTracksAPI=None):
    if not playlistAPI:
        # Get essential playlist info
        try:
            playlistAPI = dz.api.get_playlist(link_id)
        except APIError:
            playlistAPI = None
        # Fallback to gw api if the playlist is private
        if not playlistAPI:
            try:
                userPlaylist = dz.gw.get_playlist_page(link_id)
                playlistAPI = map_user_playlist(userPlaylist['DATA'])
            except GWAPIError as e:
                message = "Wrong URL"
                # TODO: FIX
                # if "DATA_ERROR" in e: message += f": {e['DATA_ERROR']}"
                raise GenerationError("https://deezer.com/playlist/"+str(link_id), message) from e

        # Check if private playlist and owner
        if not playlistAPI.get('public', False) and playlistAPI['creator']['id'] != str(dz.current_user['id']):
            logger.warning("You can't download others private playlists.")
            raise GenerationError("https://deezer.com/playlist/"+str(link_id), "You can't download others private playlists.", "notYourPrivatePlaylist")

    if not playlistTracksAPI:
        playlistTracksAPI = dz.gw.get_playlist_tracks(link_id)
    playlistAPI['various_artist'] = dz.api.get_artist(5080) # Useful for save as compilation

    totalSize = len(playlistTracksAPI)
    playlistAPI['nb_tracks'] = totalSize
    collection = []
    for pos, trackAPI in enumerate(playlistTracksAPI, start=1):
        if trackAPI.get('EXPLICIT_TRACK_CONTENT', {}).get('EXPLICIT_LYRICS_STATUS', LyricsStatus.UNKNOWN) in [LyricsStatus.EXPLICIT, LyricsStatus.PARTIALLY_EXPLICIT]:
            playlistAPI['explicit'] = True
        trackAPI['POSITION'] = pos
        trackAPI['SIZE'] = totalSize
        collection.append(trackAPI)

    if 'explicit' not in playlistAPI: playlistAPI['explicit'] = False

    return Collection({
        'type': 'playlist',
        'id': link_id,
        'bitrate': bitrate,
        'title': playlistAPI['title'],
        'artist': playlistAPI['creator']['name'],
        'cover': playlistAPI['picture_small'][:-24] + '/75x75-000000-80-0-0.jpg',
        'explicit': playlistAPI['explicit'],
        'size': totalSize,
        'collection': {
            'tracks_gw': collection,
            'playlistAPI': playlistAPI
        }
    })

def generateArtistItem(dz, link_id, bitrate, interface=None):
    # Get essential artist info
    try:
        artistAPI = dz.api.get_artist(link_id)
    except APIError as e:
        raise GenerationError("https://deezer.com/artist/"+str(link_id), f"Wrong URL: {e}") from e

    rootArtist = {
        'id': artistAPI['id'],
        'name': artistAPI['name']
    }
    if interface: interface.send("startAddingArtist", rootArtist)

    artistDiscographyAPI = dz.gw.get_artist_discography_tabs(link_id, 100)
    allReleases = artistDiscographyAPI.pop('all', [])
    albumList = []
    for album in allReleases:
        albumList.append(generateAlbumItem(dz, album['id'], bitrate, rootArtist=rootArtist))

    if interface: interface.send("finishAddingArtist", rootArtist)
    return albumList

def generateArtistDiscographyItem(dz, link_id, bitrate, interface=None):
    # Get essential artist info
    try:
        artistAPI = dz.api.get_artist(link_id)
    except APIError as e:
        e = str(e)
        raise GenerationError("https://deezer.com/artist/"+str(link_id)+"/discography", f"Wrong URL: {e}")

    rootArtist = {
        'id': artistAPI['id'],
        'name': artistAPI['name']
    }
    if interface: interface.send("startAddingArtist", rootArtist)

    artistDiscographyAPI = dz.gw.get_artist_discography_tabs(link_id, 100)
    artistDiscographyAPI.pop('all', None) # all contains albums and singles, so its all duplicates. This removes them
    albumList = []
    for releaseType in artistDiscographyAPI:
        for album in artistDiscographyAPI[releaseType]:
            albumList.append(generateAlbumItem(dz, album['id'], bitrate, rootArtist=rootArtist))

    if interface: interface.send("finishAddingArtist", rootArtist)
    return albumList

def generateArtistTopItem(dz, link_id, bitrate, interface=None):
    # Get essential artist info
    try:
        artistAPI = dz.api.get_artist(link_id)
    except APIError as e:
        e = str(e)
        raise GenerationError("https://deezer.com/artist/"+str(link_id)+"/top_track", f"Wrong URL: {e}")

    # Emulate the creation of a playlist
    # Can't use generatePlaylistItem directly as this is not a real playlist
    playlistAPI = {
        'id': str(artistAPI['id'])+"_top_track",
        'title': artistAPI['name']+" - Top Tracks",
        'description': "Top Tracks for "+artistAPI['name'],
        'duration': 0,
        'public': True,
        'is_loved_track': False,
        'collaborative': False,
        'nb_tracks': 0,
        'fans': artistAPI['nb_fan'],
        'link': "https://www.deezer.com/artist/"+str(artistAPI['id'])+"/top_track",
        'share': None,
        'picture': artistAPI['picture'],
        'picture_small': artistAPI['picture_small'],
        'picture_medium': artistAPI['picture_medium'],
        'picture_big': artistAPI['picture_big'],
        'picture_xl': artistAPI['picture_xl'],
        'checksum': None,
        'tracklist': "https://api.deezer.com/artist/"+str(artistAPI['id'])+"/top",
        'creation_date': "XXXX-00-00",
        'creator': {
            'id': "art_"+str(artistAPI['id']),
            'name': artistAPI['name'],
            'type': "user"
        },
        'type': "playlist"
    }

    artistTopTracksAPI_gw = dz.gw.get_artist_toptracks(link_id)
    return generatePlaylistItem(dz, playlistAPI['id'], bitrate, playlistAPI=playlistAPI, playlistTracksAPI=artistTopTracksAPI_gw)
