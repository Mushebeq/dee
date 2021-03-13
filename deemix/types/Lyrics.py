class Lyrics:
    def __init__(self, id="0"):
        self.id = id
        self.sync = ""
        self.unsync = ""
        self.syncID3 = []

    def parseLyrics(self, lyricsAPI):
        self.unsync = lyricsAPI.get("LYRICS_TEXT")
        if "LYRICS_SYNC_JSON" in lyricsAPI:
            syncLyricsJson = lyricsAPI["LYRICS_SYNC_JSON"]
            timestamp = ""
            milliseconds = 0
            for line in range(len(syncLyricsJson)):
                if syncLyricsJson[line]["line"] != "":
                    timestamp = syncLyricsJson[line]["lrc_timestamp"]
                    milliseconds = int(syncLyricsJson[line]["milliseconds"])
                    self.syncID3.append((syncLyricsJson[line]["line"], milliseconds))
                else:
                    notEmptyLine = line + 1
                    while syncLyricsJson[notEmptyLine]["line"] == "":
                        notEmptyLine = notEmptyLine + 1
                    timestamp = syncLyricsJson[notEmptyLine]["lrc_timestamp"]
                self.sync += timestamp + syncLyricsJson[line]["line"] + "\r\n"
