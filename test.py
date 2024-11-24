import requests
from dataclasses import dataclass, is_dataclass
from dacite import from_dict
from typing import List, Dict, Any, Type, get_type_hints
from common import *

resp = requests.get("http://24.4.109.88:7878/api/v3/wanted/missing?monitored=true&apikey=fcf04858f1ae485e9edafc4c35082740")
res = from_dict(QueueResourcePagingResource, resp.json())
for mov in res.records:
    print(f"{TimeStamp(hh_mm_ss="72:00:00").time} -- {TimeStamp.now() - TimeStamp.create(iso8601=mov.added)}")
