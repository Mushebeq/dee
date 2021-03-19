import requests
from requests import get

from concurrent.futures import ThreadPoolExecutor
from time import sleep

from os.path import sep as pathSep
from pathlib import Path
from shlex import quote
import re
import errno

from ssl import SSLError
from urllib3.exceptions import SSLError as u3SSLError
from os import makedirs

from deemix.types.DownloadObjects import Single, Collection
from deemix.types.Track import Track, AlbumDoesntExists
from deemix.utils.pathtemplates import generateFilename, generateFilepath, settingsRegexAlbum, settingsRegexArtist, settingsRegexPlaylistFile
from deezer import TrackFormats
from deemix import USER_AGENT_HEADER
from deemix.taggers import tagID3, tagFLAC
from deemix.decryption import generateUnencryptedStreamURL, streamUnencryptedTrack
from deemix.settings import OverwriteOption

from mutagen.flac import FLACNoHeaderError, error as FLACError

import logging
logger = logging.getLogger('deemix')

from tempfile import gettempdir

TEMPDIR = Path(gettempdir()) / 'deemix-imgs'
if not TEMPDIR.is_dir(): makedirs(TEMPDIR)

extensions = {
    TrackFormats.FLAC:    '.flac',
    TrackFormats.LOCAL:   '.mp3',
    TrackFormats.MP3_320: '.mp3',
    TrackFormats.MP3_128: '.mp3',
    TrackFormats.DEFAULT: '.mp3',
    TrackFormats.MP4_RA3: '.mp4',
    TrackFormats.MP4_RA2: '.mp4',
    TrackFormats.MP4_RA1: '.mp4'
}

errorMessages = {
    'notOnDeezer': "Track not available on Deezer!",
    'notEncoded': "Track not yet encoded!",
    'notEncodedNoAlternative': "Track not yet encoded and no alternative found!",
    'wrongBitrate': "Track not found at desired bitrate.",
    'wrongBitrateNoAlternative': "Track not found at desired bitrate and no alternative found!",
    'no360RA': "Track is not available in Reality Audio 360.",
    'notAvailable': "Track not available on deezer's servers!",
    'notAvailableNoAlternative': "Track not available on deezer's servers and no alternative found!",
    'noSpaceLeft': "No space left on target drive, clean up some space for the tracks",
    'albumDoesntExists': "Track's album does not exsist, failed to gather info"
}

def downloadImage(url, path, overwrite=OverwriteOption.DONT_OVERWRITE):
    if not path.is_file() or overwrite in [OverwriteOption.OVERWRITE, OverwriteOption.ONLY_TAGS, OverwriteOption.KEEP_BOTH]:
        try:
            image = get(url, headers={'User-Agent': USER_AGENT_HEADER}, timeout=30)
            image.raise_for_status()
            with open(path, 'wb') as f:
                f.write(image.content)
            return path
        except requests.exceptions.HTTPError:
            if 'cdns-images.dzcdn.net' in url:
                urlBase = url[:url.rfind("/")+1]
                pictureUrl = url[len(urlBase):]
                pictureSize = int(pictureUrl[:pictureUrl.find("x")])
                if pictureSize > 1200:
                    logger.warn("Couldn't download "+str(pictureSize)+"x"+str(pictureSize)+" image, falling back to 1200x1200")
                    sleep(1)
                    return downloadImage(urlBase+pictureUrl.replace(str(pictureSize)+"x"+str(pictureSize), '1200x1200'), path, overwrite)
            logger.error("Image not found: "+url)
        except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError, u3SSLError) as e:
            logger.error("Couldn't download Image, retrying in 5 seconds...: "+url+"\n")
            sleep(5)
            return downloadImage(url, path, overwrite)
        except OSError as e:
            if e.errno == errno.ENOSPC: raise DownloadFailed("noSpaceLeft")
            else: logger.exception(f"Error while downloading an image, you should report this to the developers: {str(e)}")
        except Exception as e:
            logger.exception(f"Error while downloading an image, you should report this to the developers: {str(e)}")
        if path.is_file(): path.unlink()
        return None
    else:
        return path

def getPreferredBitrate(track, preferredBitrate, shouldFallback, downloadObjectUUID=None, interface=None):
    if track.localTrack: return TrackFormats.LOCAL

    falledBack = False

    formats_non_360 = {
        TrackFormats.FLAC: "FLAC",
        TrackFormats.MP3_320: "MP3_320",
        TrackFormats.MP3_128: "MP3_128",
    }
    formats_360 = {
        TrackFormats.MP4_RA3: "MP4_RA3",
        TrackFormats.MP4_RA2: "MP4_RA2",
        TrackFormats.MP4_RA1: "MP4_RA1",
    }

    is360format = int(preferredBitrate) in formats_360

    if not shouldFallback:
        formats = formats_360
        formats.update(formats_non_360)
    elif is360format:
        formats = formats_360
    else:
        formats = formats_non_360

    for formatNumber, formatName in formats.items():
        if formatNumber <= int(preferredBitrate):
            if f"FILESIZE_{formatName}" in track.filesizes:
                if int(track.filesizes[f"FILESIZE_{formatName}"]) != 0: return formatNumber
                if not track.filesizes[f"FILESIZE_{formatName}_TESTED"]:
                    request = requests.head(
                        generateUnencryptedStreamURL(track.id, track.MD5, track.mediaVersion, formatNumber),
                        headers={'User-Agent': USER_AGENT_HEADER},
                        timeout=30
                    )
                    try:
                        request.raise_for_status()
                        return formatNumber
                    except requests.exceptions.HTTPError: # if the format is not available, Deezer returns a 403 error
                        pass
            if not shouldFallback:
                raise PreferredBitrateNotFound
            else:
                if not falledBack:
                    falledBack = True
                    logger.info(f"[{track.mainArtist.name} - {track.title}] Fallback to lower bitrate")
                    if interface and downloadObjectUUID:
                        interface.send('queueUpdate', {
                            'uuid': downloadObjectUUID,
                            'bitrateFallback': True,
                            'data': {
                                'id': track.id,
                                'title': track.title,
                                'artist': track.mainArtist.name
                            },
                        })
    if is360format: raise TrackNot360
    return TrackFormats.DEFAULT

class Downloader:
    def __init__(self, dz, downloadObject, settings, interface=None):
        self.dz = dz
        self.downloadObject = downloadObject
        self.settings = settings
        self.bitrate = downloadObject.bitrate
        self.interface = interface
        self.extrasPath = None
        self.playlistCoverName = None
        self.playlistURLs = []

    def start(self):
        if isinstance(self.downloadObject, Single):
            result = self.downloadWrapper(self.downloadObject.single['trackAPI_gw'], self.downloadObject.single['trackAPI'], self.downloadObject.single['albumAPI'])
            if result: self.singleAfterDownload(result)
        elif isinstance(self.downloadObject, Collection):
            tracks = [None] * len(self.downloadObject.collection['tracks_gw'])
            with ThreadPoolExecutor(self.settings['queueConcurrency']) as executor:
                for pos, track in enumerate(self.downloadObject.collection['tracks_gw'], start=0):
                    tracks[pos] = executor.submit(self.downloadWrapper, track, None, self.downloadObject.collection['albumAPI'], self.downloadObject.collection['playlistAPI'])
            self.collectionAfterDownload(tracks)
        if self.interface:
            self.interface.send("finishDownload", self.downloadObject.uuid)
        return self.extrasPath

    def download(self, trackAPI_gw, trackAPI=None, albumAPI=None, playlistAPI=None, track=None):
        result = {}
        if trackAPI_gw['SNG_ID'] == "0": raise DownloadFailed("notOnDeezer")

        # Create Track object
        if not track:
            logger.info(f"[{trackAPI_gw['ART_NAME']} - {trackAPI_gw['SNG_TITLE']}] Getting the tags")
            try:
                track = Track().parseData(
                    dz=self.dz,
                    trackAPI_gw=trackAPI_gw,
                    trackAPI=trackAPI,
                    albumAPI=albumAPI,
                    playlistAPI=playlistAPI
                )
            except AlbumDoesntExists:
                raise DownloadError('albumDoesntExists')

        # Check if track not yet encoded
        if track.MD5 == '': raise DownloadFailed("notEncoded", track)

        # Choose the target bitrate
        try:
            selectedFormat = getPreferredBitrate(
                track,
                self.bitrate,
                self.settings['fallbackBitrate'],
                self.downloadObject.uuid, self.interface
            )
        except PreferredBitrateNotFound:
            raise DownloadFailed("wrongBitrate", track)
        except TrackNot360:
            raise DownloadFailed("no360RA")
        track.selectedFormat = selectedFormat
        track.album.bitrate = selectedFormat

        # Generate covers URLs
        embeddedImageFormat = f'jpg-{self.settings["jpegImageQuality"]}'
        if self.settings['embeddedArtworkPNG']: imageFormat = 'png'

        track.applySettings(self.settings, TEMPDIR, embeddedImageFormat)

        # Generate filename and filepath from metadata
        filename = generateFilename(track, self.settings, "%artist% - %title%")
        (filepath, artistPath, coverPath, extrasPath) = generateFilepath(track, self.settings)
        # Remove subfolders from filename and add it to filepath
        if pathSep in filename:
            tempPath = filename[:filename.rfind(pathSep)]
            filepath = filepath / tempPath
            filename = filename[filename.rfind(pathSep) + len(pathSep):]
        # Make sure the filepath exists
        makedirs(filepath, exist_ok=True)
        writepath = filepath / f"{filename}{extensions[track.selectedFormat]}"
        # Save extrasPath
        if extrasPath:
            if not self.extrasPath: self.extrasPath = extrasPath
            result['filename'] = str(writepath)[len(str(extrasPath))+ len(pathSep):]

        # Download and cache coverart
        logger.info(f"[{track.mainArtist.name} - {track.title}] Getting the album cover")
        track.album.embeddedCoverPath = downloadImage(track.album.embeddedCoverURL, track.album.embeddedCoverPath)

        # Save local album art
        if coverPath:
            result['albumURLs'] = []
            for format in self.settings['localArtworkFormat'].split(","):
                if format in ["png","jpg"]:
                    extendedFormat = format
                    if extendedFormat == "jpg": extendedFormat += f"-{self.settings['jpegImageQuality']}"
                    url = track.album.pic.generatePictureURL(self.settings['localArtworkSize'], extendedFormat)
                    if self.settings['tags']['savePlaylistAsCompilation'] \
                        and track.playlist \
                        and track.playlist.pic.staticUrl \
                        and not format.startswith("jpg"):
                            continue
                    result['albumURLs'].append({'url': url, 'ext': format})
            result['albumPath'] = coverPath
            result['albumFilename'] = f"{settingsRegexAlbum(self.settings['coverImageTemplate'], track.album, self.settings, track.playlist)}"

        # Save artist art
        if artistPath:
            result['artistURLs'] = []
            for format in self.settings['localArtworkFormat'].split(","):
                if format in ["png","jpg"]:
                    extendedFormat = format
                    if extendedFormat == "jpg": extendedFormat += f"-{self.settings['jpegImageQuality']}"
                    url = track.album.mainArtist.pic.generatePictureURL(self.settings['localArtworkSize'], extendedFormat)
                    if track.album.mainArtist.pic.md5 == "" and not format.startswith("jpg"): continue
                    result['artistURLs'].append({'url': url, 'ext': format})
            result['artistPath'] = artistPath
            result['artistFilename'] = f"{settingsRegexArtist(self.settings['artistImageTemplate'], track.album.mainArtist, self.settings, rootArtist=track.album.rootArtist)}"

        # Save playlist art
        if track.playlist:
            if not len(self.playlistURLs):
                for format in self.settings['localArtworkFormat'].split(","):
                    if format in ["png","jpg"]:
                        extendedFormat = format
                        if extendedFormat == "jpg": extendedFormat += f"-{self.settings['jpegImageQuality']}"
                        url = track.playlist.pic.generatePictureURL(self.settings['localArtworkSize'], extendedFormat)
                        if track.playlist.pic.staticUrl and not format.startswith("jpg"): continue
                        self.playlistURLs.append({'url': url, 'ext': format})
            if not self.playlistCoverName:
                track.playlist.bitrate = selectedFormat
                track.playlist.dateString = track.playlist.date.format(self.settings['dateFormat'])
                self.playlistCoverName = f"{settingsRegexAlbum(self.settings['coverImageTemplate'], track.playlist, self.settings, track.playlist)}"

        # Save lyrics in lrc file
        if self.settings['syncedLyrics'] and track.lyrics.sync:
            if not (filepath / f"{filename}.lrc").is_file() or self.settings['overwriteFile'] in [OverwriteOption.OVERWRITE, OverwriteOption.ONLY_TAGS]:
                with open(filepath / f"{filename}.lrc", 'wb') as f:
                    f.write(track.lyrics.sync.encode('utf-8'))

        # Check for overwrite settings
        trackAlreadyDownloaded = writepath.is_file()

        # Don't overwrite and don't mind extension
        if not trackAlreadyDownloaded and self.settings['overwriteFile'] == OverwriteOption.DONT_CHECK_EXT:
            exts = ['.mp3', '.flac', '.opus', '.m4a']
            baseFilename = str(filepath / filename)
            for ext in exts:
                trackAlreadyDownloaded = Path(baseFilename+ext).is_file()
                if trackAlreadyDownloaded: break
        # Don't overwrite and keep both files
        if trackAlreadyDownloaded and self.settings['overwriteFile'] == OverwriteOption.KEEP_BOTH:
            baseFilename = str(filepath / filename)
            i = 1
            currentFilename = baseFilename+' ('+str(i)+')'+ extensions[track.selectedFormat]
            while Path(currentFilename).is_file():
                i += 1
                currentFilename = baseFilename+' ('+str(i)+')'+ extensions[track.selectedFormat]
            trackAlreadyDownloaded = False
            writepath = Path(currentFilename)

        if not trackAlreadyDownloaded or self.settings['overwriteFile'] == OverwriteOption.OVERWRITE:
            logger.info(f"[{track.mainArtist.name} - {track.title}] Downloading the track")
            track.downloadUrl = generateUnencryptedStreamURL(track.id, track.MD5, track.mediaVersion, track.selectedFormat)

            def downloadMusic(track, trackAPI_gw):
                try:
                    with open(writepath, 'wb') as stream:
                        streamUnencryptedTrack(stream, track, downloadObject=self.downloadObject, interface=self.interface)
                except DownloadCancelled:
                    if writepath.is_file(): writepath.unlink()
                    raise DownloadCancelled
                except (requests.exceptions.HTTPError, DownloadEmpty):
                    if writepath.is_file(): writepath.unlink()
                    if track.fallbackId != "0":
                        logger.warn(f"[{track.mainArtist.name} - {track.title}] Track not available, using fallback id")
                        newTrack = self.dz.gw.get_track_with_fallback(track.fallbackId)
                        track.parseEssentialData(newTrack)
                        track.retriveFilesizes(self.dz)
                        return False
                    elif not track.searched and self.settings['fallbackSearch']:
                        logger.warn(f"[{track.mainArtist.name} - {track.title}] Track not available, searching for alternative")
                        searchedId = self.dz.api.get_track_id_from_metadata(track.mainArtist.name, track.title, track.album.title)
                        if searchedId != "0":
                            newTrack = self.dz.gw.get_track_with_fallback(searchedId)
                            track.parseEssentialData(newTrack)
                            track.retriveFilesizes(self.dz)
                            track.searched = True
                            if self.interface:
                                self.interface.send('queueUpdate', {
                                    'uuid': self.downloadObject.uuid,
                                    'searchFallback': True,
                                    'data': {
                                        'id': track.id,
                                        'title': track.title,
                                        'artist': track.mainArtist.name
                                    },
                                })
                            return False
                        else:
                            raise DownloadFailed("notAvailableNoAlternative")
                    else:
                        raise DownloadFailed("notAvailable")
                except (requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
                    if writepath.is_file(): writepath.unlink()
                    logger.warn(f"[{track.mainArtist.name} - {track.title}] Error while downloading the track, trying again in 5s...")
                    sleep(5)
                    return downloadMusic(track, trackAPI_gw)
                except OSError as e:
                    if e.errno == errno.ENOSPC:
                        raise DownloadFailed("noSpaceLeft")
                    else:
                        if writepath.is_file(): writepath.unlink()
                        logger.exception(f"[{track.mainArtist.name} - {track.title}] Error while downloading the track, you should report this to the developers: {str(e)}")
                        raise e
                except Exception as e:
                    if writepath.is_file(): writepath.unlink()
                    logger.exception(f"[{track.mainArtist.name} - {track.title}] Error while downloading the track, you should report this to the developers: {str(e)}")
                    raise e
                return True

            try:
                trackDownloaded = downloadMusic(track, trackAPI_gw)
            except Exception as e:
                raise e

            if not trackDownloaded: return self.download(trackAPI_gw, track=track)
        else:
            logger.info(f"[{track.mainArtist.name} - {track.title}] Skipping track as it's already downloaded")
            self.downloadObject.completeTrackProgress(self.interface)

        # Adding tags
        if (not trackAlreadyDownloaded or self.settings['overwriteFile'] in [OverwriteOption.ONLY_TAGS, OverwriteOption.OVERWRITE]) and not track.localTrack:
            logger.info(f"[{track.mainArtist.name} - {track.title}] Applying tags to the track")
            if track.selectedFormat in [TrackFormats.MP3_320, TrackFormats.MP3_128, TrackFormats.DEFAULT]:
                tagID3(writepath, track, self.settings['tags'])
            elif track.selectedFormat ==  TrackFormats.FLAC:
                try:
                    tagFLAC(writepath, track, self.settings['tags'])
                except (FLACNoHeaderError, FLACError):
                    if writepath.is_file(): writepath.unlink()
                    logger.warn(f"[{track.mainArtist.name} - {track.title}] Track not available in FLAC, falling back if necessary")
                    self.downloadObject.removeTrackProgress(self.interface)
                    track.filesizes['FILESIZE_FLAC'] = "0"
                    track.filesizes['FILESIZE_FLAC_TESTED'] = True
                    return self.download(trackAPI_gw, track=track)

        if track.searched: result['searched'] = f"{track.mainArtist.name} - {track.title}"
        logger.info(f"[{track.mainArtist.name} - {track.title}] Track download completed\n{str(writepath)}")
        self.downloadObject.downloaded += 1
        self.downloadObject.files.append(str(writepath))
        self.downloadObject.extrasPath = str(self.extrasPath)
        if self.interface:
            self.interface.send("updateQueue", {'uuid': self.downloadObject.uuid, 'downloaded': True, 'downloadPath': str(writepath), 'extrasPath': str(self.extrasPath)})
        return result

    def downloadWrapper(self, trackAPI_gw, trackAPI=None, albumAPI=None, playlistAPI=None, track=None):
        # Temp metadata to generate logs
        tempTrack = {
            'id': trackAPI_gw['SNG_ID'],
            'title': trackAPI_gw['SNG_TITLE'].strip(),
            'artist': trackAPI_gw['ART_NAME']
        }
        if trackAPI_gw.get('VERSION') and trackAPI_gw['VERSION'] not in trackAPI_gw['SNG_TITLE']:
            tempTrack['title'] += f" {trackAPI_gw['VERSION']}".strip()

        try:
            result = self.download(trackAPI_gw, trackAPI, albumAPI, playlistAPI, track)
        except DownloadFailed as error:
            if error.track:
                track = error.track
                if track.fallbackId != "0":
                    logger.warn(f"[{track.mainArtist.name} - {track.title}] {error.message} Using fallback id")
                    newTrack = self.dz.gw.get_track_with_fallback(track.fallbackId)
                    track.parseEssentialData(newTrack)
                    track.retriveFilesizes(self.dz)
                    return self.downloadWrapper(trackAPI_gw, trackAPI, albumAPI, playlistAPI, track)
                elif not track.searched and self.settings['fallbackSearch']:
                    logger.warn(f"[{track.mainArtist.name} - {track.title}] {error.message} Searching for alternative")
                    searchedId = self.dz.api.get_track_id_from_metadata(track.mainArtist.name, track.title, track.album.title)
                    if searchedId != "0":
                        newTrack = self.dz.gw.get_track_with_fallback(searchedId)
                        track.parseEssentialData(newTrack)
                        track.retriveFilesizes(self.dz)
                        track.searched = True
                        if self.interface:
                            self.interface.send('queueUpdate', {
                                'uuid': self.queueItem.uuid,
                                'searchFallback': True,
                                'data': {
                                    'id': track.id,
                                    'title': track.title,
                                    'artist': track.mainArtist.name
                                },
                            })
                        return self.downloadWrapper(trackAPI_gw, trackAPI, albumAPI, playlistAPI, track)
                    else:
                        error.errid += "NoAlternative"
                        error.message = errorMessages[error.errid]
            logger.error(f"[{tempTrack['artist']} - {tempTrack['title']}] {error.message}")
            result = {'error': {
                        'message': error.message,
                        'errid': error.errid,
                        'data': tempTrack
                    }}
        except Exception as e:
            logger.exception(f"[{tempTrack['artist']} - {tempTrack['title']}] {str(e)}")
            result = {'error': {
                        'message': str(e),
                        'data': tempTrack
                    }}

        if 'error' in result:
            self.downloadObject.completeTrackProgress(self.interface)
            self.downloadObject.failed += 1
            self.downloadObject.errors.append(result['error'])
            if self.interface:
                error = result['error']
                self.interface.send("updateQueue", {
                    'uuid': self.downloadObject.uuid,
                    'failed': True,
                    'data': error['data'],
                    'error': error['message'],
                    'errid': error['errid'] if 'errid' in error else None
                })
        return result

    def singleAfterDownload(self, result):
        if not self.extrasPath: self.extrasPath = Path(self.settings['downloadLocation'])

        # Save Album Cover
        if self.settings['saveArtwork'] and 'albumPath' in result:
            for image in result['albumURLs']:
                downloadImage(image['url'], result['albumPath'] / f"{result['albumFilename']}.{image['ext']}", self.settings['overwriteFile'])

        # Save Artist Artwork
        if self.settings['saveArtworkArtist'] and 'artistPath' in result:
            for image in result['artistURLs']:
                downloadImage(image['url'], result['artistPath'] / f"{result['artistFilename']}.{image['ext']}", self.settings['overwriteFile'])

        # Create searched logfile
        if self.settings['logSearched'] and 'searched' in result:
            with open(self.extrasPath / 'searched.txt', 'wb+') as f:
                orig = f.read().decode('utf-8')
                if not result['searched'] in orig:
                    if orig != "": orig += "\r\n"
                    orig += result['searched'] + "\r\n"
                f.write(orig.encode('utf-8'))
        # Execute command after download
        if self.settings['executeCommand'] != "":
            execute(self.settings['executeCommand'].replace("%folder%", quote(str(self.extrasPath))).replace("%filename%", quote(result['filename'])), shell=True)

    def collectionAfterDownload(self, tracks):
        if not self.extrasPath: self.extrasPath = Path(self.settings['downloadLocation'])
        playlist = [None] * len(tracks)
        errors = ""
        searched = ""

        for i in range(len(tracks)):
            result = tracks[i].result()
            if not result: return None # Check if item is cancelled

            # Log errors to file
            if result.get('error'):
                if not result['error'].get('data'): result['error']['data'] = {'id': "0", 'title': 'Unknown', 'artist': 'Unknown'}
                errors += f"{result['error']['data']['id']} | {result['error']['data']['artist']} - {result['error']['data']['title']} | {result['error']['message']}\r\n"

            # Log searched to file
            if 'searched' in result: searched += result['searched'] + "\r\n"

            # Save Album Cover
            if self.settings['saveArtwork'] and 'albumPath' in result:
                for image in result['albumURLs']:
                    downloadImage(image['url'], result['albumPath'] / f"{result['albumFilename']}.{image['ext']}", self.settings['overwriteFile'])

            # Save Artist Artwork
            if self.settings['saveArtworkArtist'] and 'artistPath' in result:
                for image in result['artistURLs']:
                    downloadImage(image['url'], result['artistPath'] / f"{result['artistFilename']}.{image['ext']}", self.settings['overwriteFile'])

            # Save filename for playlist file
            playlist[i] = result.get('filename', "")

        # Create errors logfile
        if self.settings['logErrors'] and errors != "":
            with open(self.extrasPath / 'errors.txt', 'wb') as f:
                f.write(errors.encode('utf-8'))

        # Create searched logfile
        if self.settings['logSearched'] and searched != "":
            with open(self.extrasPath / 'searched.txt', 'wb') as f:
                f.write(searched.encode('utf-8'))

        # Save Playlist Artwork
        if self.settings['saveArtwork'] and self.playlistCoverName and not self.settings['tags']['savePlaylistAsCompilation']:
            for image in self.playlistURLs:
                downloadImage(image['url'], self.extrasPath / f"{self.playlistCoverName}.{image['ext']}", self.settings['overwriteFile'])

        # Create M3U8 File
        if self.settings['createM3U8File']:
            filename = settingsRegexPlaylistFile(self.settings['playlistFilenameTemplate'], self.downloadObject, self.settings) or "playlist"
            with open(self.extrasPath / f'{filename}.m3u8', 'wb') as f:
                for line in playlist:
                    f.write((line + "\n").encode('utf-8'))

        # Execute command after download
        if self.settings['executeCommand'] != "":
            execute(self.settings['executeCommand'].replace("%folder%", quote(str(self.extrasPath))), shell=True)

class DownloadError(Exception):
    """Base class for exceptions in this module."""
    pass

class DownloadFailed(DownloadError):
    def __init__(self, errid, track=None):
        self.errid = errid
        self.message = errorMessages[self.errid]
        self.track = track

class DownloadCancelled(DownloadError):
    pass

class PreferredBitrateNotFound(DownloadError):
    pass

class TrackNot360(DownloadError):
    pass
