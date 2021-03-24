from deemix.types.DownloadObjects import Single, Collection
from deezer.api import APIError
from deezer.gw import GWAPIError, LyricsStatus

class GenerationError(Exception):
    def __init__(self, link, message, errid=None):
        self.link = link
        self.message = message
        self.errid = errid

    def toDict(self):
        return {
            'link': self.link,
            'error': self.message,
            'errid': self.errid
        }

def generateTrackItem(dz, id, bitrate, trackAPI=None, albumAPI=None):
    # Check if is an isrc: url
    if str(id).startswith("isrc"):
        try:
            trackAPI = dz.api.get_track(id)
        except APIError as e:
            e = str(e)
            raise GenerationError("https://deezer.com/track/"+str(id), f"Wrong URL: {e}")
        if 'id' in trackAPI and 'title' in trackAPI:
            id = trackAPI['id']
        else:
            raise GenerationError("https://deezer.com/track/"+str(id), "Track ISRC is not available on deezer", "ISRCnotOnDeezer")

    # Get essential track info
    try:
        trackAPI_gw = dz.gw.get_track_with_fallback(id)
    except GWAPIError as e:
        e = str(e)
        message = "Wrong URL"
        if "DATA_ERROR" in e: message += f": {e['DATA_ERROR']}"
        raise GenerationError("https://deezer.com/track/"+str(id), message)

    title = trackAPI_gw['SNG_TITLE'].strip()
    if trackAPI_gw.get('VERSION') and trackAPI_gw['VERSION'] not in trackAPI_gw['SNG_TITLE']:
        title += f" {trackAPI_gw['VERSION']}".strip()
    explicit = bool(int(trackAPI_gw.get('EXPLICIT_LYRICS', 0)))

    return Single({
        'type': 'track',
        'id': id,
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

def generateAlbumItem(dz, id, bitrate, rootArtist=None):
    # Get essential album info
    try:
        albumAPI = dz.api.get_album(id)
    except APIError as e:
        e = str(e)
        raise GenerationError("https://deezer.com/album/"+str(id), f"Wrong URL: {e}")

    if str(id).startswith('upc'): id = albumAPI['id']

    # Get extra info about album
    # This saves extra api calls when downloading
    albumAPI_gw = dz.gw.get_album(id)
    albumAPI['nb_disk'] = albumAPI_gw['NUMBER_DISK']
    albumAPI['copyright'] = albumAPI_gw['COPYRIGHT']
    albumAPI['root_artist'] = rootArtist

    # If the album is a single download as a track
    if albumAPI['nb_tracks'] == 1:
        return generateTrackItem(dz, albumAPI['tracks']['data'][0]['id'], bitrate, albumAPI=albumAPI)

    tracksArray = dz.gw.get_album_tracks(id)

    if albumAPI['cover_small'] != None:
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
        'id': id,
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

def generatePlaylistItem(dz, id, bitrate, playlistAPI=None, playlistTracksAPI=None):
    if not playlistAPI:
        # Get essential playlist info
        try:
            playlistAPI = dz.api.get_playlist(id)
        except:
            playlistAPI = None
        # Fallback to gw api if the playlist is private
        if not playlistAPI:
            try:
                userPlaylist = dz.gw.get_playlist_page(id)
                playlistAPI = map_user_playlist(userPlaylist['DATA'])
            except GWAPIError as e:
                e = str(e)
                message = "Wrong URL"
                if "DATA_ERROR" in e:
                    message += f": {e['DATA_ERROR']}"
                raise GenerationError("https://deezer.com/playlist/"+str(id), message)

        # Check if private playlist and owner
        if not playlistAPI.get('public', False) and playlistAPI['creator']['id'] != str(dz.current_user['id']):
            logger.warning("You can't download others private playlists.")
            raise GenerationError("https://deezer.com/playlist/"+str(id), "You can't download others private playlists.", "notYourPrivatePlaylist")

    if not playlistTracksAPI:
        playlistTracksAPI = dz.gw.get_playlist_tracks(id)
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

    if not 'explicit' in playlistAPI: playlistAPI['explicit'] = False

    return Collection({
        'type': 'playlist',
        'id': id,
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

def generateArtistItem(dz, id, bitrate, interface=None):
    # Get essential artist info
    try:
        artistAPI = dz.api.get_artist(id)
    except APIError as e:
        e = str(e)
        raise GenerationError("https://deezer.com/artist/"+str(id), f"Wrong URL: {e}")

    if interface: interface.send("startAddingArtist", {'name': artistAPI['name'], 'id': artistAPI['id']})
    rootArtist = {
        'id': artistAPI['id'],
        'name': artistAPI['name']
    }

    artistDiscographyAPI = dz.gw.get_artist_discography_tabs(id, 100)
    allReleases = artistDiscographyAPI.pop('all', [])
    albumList = []
    for album in allReleases:
        albumList.append(generateAlbumItem(dz, album['id'], bitrate, rootArtist=rootArtist))

    if interface: interface.send("finishAddingArtist", {'name': artistAPI['name'], 'id': artistAPI['id']})
    return albumList

def generateArtistDiscographyItem(dz, id, bitrate, interface=None):
    # Get essential artist info
    try:
        artistAPI = dz.api.get_artist(id)
    except APIError as e:
        e = str(e)
        raise GenerationError("https://deezer.com/artist/"+str(id)+"/discography", f"Wrong URL: {e}")

    if interface: interface.send("startAddingArtist", {'name': artistAPI['name'], 'id': artistAPI['id']})
    rootArtist = {
        'id': artistAPI['id'],
        'name': artistAPI['name']
    }

    artistDiscographyAPI = dz.gw.get_artist_discography_tabs(id, 100)
    artistDiscographyAPI.pop('all', None) # all contains albums and singles, so its all duplicates. This removes them
    albumList = []
    for type in artistDiscographyAPI:
        for album in artistDiscographyAPI[type]:
            albumList.append(generateAlbumItem(dz, album['id'], bitrate, rootArtist=rootArtist))

    if interface: interface.send("finishAddingArtist", {'name': artistAPI['name'], 'id': artistAPI['id']})
    return albumList

def generateArtistTopItem(dz, id, bitrate, interface=None):
    # Get essential artist info
    try:
        artistAPI = dz.api.get_artist(id)
    except APIError as e:
        e = str(e)
        raise GenerationError("https://deezer.com/artist/"+str(id)+"/top_track", f"Wrong URL: {e}")

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

    artistTopTracksAPI_gw = dz.gw.get_artist_toptracks(id)
    return generatePlaylistItem(dz, playlistAPI['id'], bitrate, playlistAPI=playlistAPI, playlistTracksAPI=artistTopTracksAPI_gw)
