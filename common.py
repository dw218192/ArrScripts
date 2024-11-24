from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any

def hms_to_secs(str_time : str):
    parts = list(map(float, str_time.split(':')))
    return (parts[0] * 3600 + parts[1] * 60 + parts[2])

def sec_to_hms(seconds : int | float):
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"

def iso8601_to_secs(datetime_string : str):
    dt_object = datetime.fromisoformat(datetime_string.replace("Z", "+00:00"))
    return dt_object.timestamp()

class TimeStamp:
    @classmethod
    def now(cls):
        return TimeStamp()
    
    @classmethod
    def create(cls,
               hh_mm_ss : Optional[str] = None,
               iso8601 : Optional[str] = None,
               time_stamp : Optional[int | float] = None):
        ret = TimeStamp()
        if hh_mm_ss is not None:
            ret.time = hms_to_secs(hh_mm_ss)
        elif iso8601 is not None:
            ret.time = iso8601_to_secs(iso8601)
        elif time_stamp is not None:
            ret.time = time_stamp
        return ret        

    @classmethod
    def _get_time(cls, other : Any):
        if isinstance(other, TimeStamp):
            t = other.time
        elif isinstance(other, (int, float)):
            t = other
        else:
            return NotImplemented
        return t

    def __init__(self, hh_mm_ss : Optional[str] = None):
        if hh_mm_ss is not None:
            self.time = hms_to_secs(hh_mm_ss)
        else:
            self.time = datetime.now().timestamp()

    def __str__(self):
        return sec_to_hms(self.time)

    def __eq__(self, other : Any):
        t = TimeStamp._get_time(other)
        if isinstance(t, type(NotImplemented)):
            return t
        return self.time == t
    def __lt__(self, other : Any):
        t = TimeStamp._get_time(other)
        if isinstance(t, type(NotImplemented)):
            return t
        return self.time < t
    def __le__(self, other : Any):
        return self < other or self == other
    def __gt__(self, other : Any):
        return not self <= other
    def __ge__(self, other : Any):
        return not self < other
    def __add__(self, other : Any):
        t = TimeStamp._get_time(other)
        if isinstance(t, type(NotImplemented)):
            return t
        return self.time + t
    def __sub__(self, other : Any):
        t = TimeStamp._get_time(other)
        if isinstance(t, type(NotImplemented)):
            return t
        return self.time - t
    def __hash__(self):
        return hash(self.time)

# https://radarr.video/docs/api/#/Queue/get_api_v3_queue
# https://sonarr.tv/docs/api/#/Queue/get_api_v3_queue

# indexer service
# https://prowlarr.com/docs/api/

@dataclass
class MovieResource:
    id : int
    title : Optional[str]

@dataclass
class SeriesResource:
    id : int
    title : Optional[str]


class Source:
    UNKNOWN = "unknown"
    CAM = "cam"
    TELESYNC = "telesync"
    TELECINE = "telecine"
    WORKPRINT = "workprint"
    DVD = "dvd"
    TV = "tv"
    WEBDL = "webdl"
    WEBRIP = "webrip"
    BLURAY = "bluray"

@dataclass
class Language:
    id : int
    name : Optional[str]

@dataclass
class Quality:
    id : int
    resolution : int
    source : str # Source
    name : Optional[str] = None

@dataclass
class QualityModel:
    quality : Quality

@dataclass
class QueueResource:
    id : int
#    quality : QualityModel
    size : float = 0
    languages : List[Language] = field(default_factory=list)
    timeleft : Optional[str] = None #TimeStamp
    errorMessage : Optional[str] = None
    title : Optional[str] = None
    added : Optional[str] = None #TimeStamp

    # radarr
    movie : Optional[MovieResource] = None

    # sonarr
    series : Optional[SeriesResource] = None


    def get_title_or_id(self):
        return self.title if self.title is not None else str(self.id)

    def get_media(self):
        return self.movie if self.movie is not None else self.series

@dataclass
class QueueResourcePagingResource:
    records : List[QueueResource]


@dataclass
class ReleaseResource:
    quality : QualityModel
    indexerId : int
    seeders : Optional[int]
    leechers : Optional[int]
    languages : List[Language] = field(default_factory=list)
    rejections : List[str] = field(default_factory=list)
    guid : Optional[str] = None

# Data used by the monitor
@dataclass
class MovieRecord:
    title : str
    id : int
    timeleft : str #TimeStamp
    errorTime : Optional[str] = None #TimeStamp
    firstFailedAt : Optional[str] = None #TimeStamp

@dataclass
class Record:
    lastRun : str #TimeStamp
    movies : List[MovieRecord] = field(default_factory=list)