import requests
from typing import Any

base_url = "http://24.4.109.88:9696/api/v1"
header = {
    "X-Api-Key" : "e622e192673a4eecb752b41ebc20c603",
    "Origin": "http://24.4.109.88:9696",
    "Authorization": "Basic QWRtaW5pc3RyYXRvcjpCYWRsdWNrMTIzIQ==",
    "Pragma": "no-cache"
}


class Dummy:
    def __getitem__(self, _):
        return Dummy()
    def __eq__(self, _) -> bool:
        return False
    def __iter__(self):
        return self
    def __next__(self):
        raise StopIteration
    def __contains__(self):
        return False
    def lower(self) -> str:
        return ''

def safe_get(d : Any, k : Any):
    return d[k] if k in d else Dummy()

indexers = requests.get(f"{base_url}/indexer/schema", headers=header).json()
for indexer in indexers:
    if safe_get(indexer, 'privacy') == 'public':
        indexer['appProfileId'] = 1
        resp = requests.post(f"{base_url}/indexer?", headers=header, json=indexer)
        if not resp.ok:
            print(f"failed to add {safe_get(indexer, 'definitionName')}:\n{resp.text}")
        else:
            print(f"added {safe_get(indexer, 'definitionName')}")
        # for c in safe_get(safe_get(indexer, 'capabilities'), 'categories'):
        #     category_name = safe_get(c, 'name')
        #     category_name = category_name.lower()
        #     if 'TV' in category_name or 'Movie' in category_name:
        #         is_valid = True