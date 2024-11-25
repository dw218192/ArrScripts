import pathlib
import asyncio
import logging
import logging.handlers
import tomlkit
import json
import httpx
from dataclasses import asdict
from dacite import from_dict
from common import *


@dataclass(frozen=True)
class MonitorConfig:
    log_file_path: str  # Path to the log file
    record_file_path: str  # Path to the record file
    api_endpoint: str  # URL to the API endpoint
    api_key: str  # API key for the endpoint
    run_interval_secs: float  # How often to run the monitor
    max_log_size_bytes: int  # Maximum size of the log file
    max_media_size_bytes: int  # Maximum allowed size of media files
    max_download_time_secs: float  # Maximum allowed download time; if exceeded, the download is considered failed
    max_err_time_secs: float  # Maximum allowed error time; if exceeded, the download is considered failed
    reap_interval_secs: (
        float  # Interval to check for failed downloads and attempt to re-download them
    )
    hopeless_threshold: float  # Percentage of timeleft samples that exceed max_download_time_secs for a download is considered hopeless
    warmup_time_secs: (
        float  # Time to wait before starting to check for hopeless downloads
    )


class BaseMonitor:
    config: MonitorConfig

    def __init__(self, config: MonitorConfig):
        self.config = config
        assert not self.config.api_endpoint.endswith("/")

        # Delete previous log file, mode='w' doesn't truncate the file for some reason
        log_file_path = pathlib.Path(self.config.log_file_path)
        for log_file in log_file_path.parent.glob(f"{log_file_path.name}*"):
            log_file.unlink()

        # Set up logging
        self.logger = logging.getLogger(self.config.api_key)
        formatter = logging.Formatter("%(asctime)s:%(levelname)s:%(message)s")
        handler = logging.handlers.RotatingFileHandler(
            filename=self.config.log_file_path,
            mode="w",
            maxBytes=self.config.max_log_size_bytes,
            backupCount=2,
            encoding="utf-8",
            delay=False,
        )
        handler.setLevel(logging.INFO)
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)

    async def run(self):
        try:
            i = 0
            while True:
                await self._run(i)
                await asyncio.sleep(self.config.run_interval_secs)
                i += 1
        except asyncio.CancelledError:
            self.logger.info("Monitor stopped")
        finally:
            await self._cleanup()

    async def _cleanup(self): ...
    async def _run(self, cur_iter: int): ...
    async def _send(self, func, relative_url, *args, **kwargs):
        url = f"{self.config.api_endpoint}/{relative_url}"
        try:
            resp: httpx.Response = func(
                url, *args, **kwargs, headers={"X-Api-Key": self.config.api_key}
            )
            if not resp.is_success:
                self.logger.error(
                    f"request {url} failed with status code {resp.status_code}"
                )
                if resp.text:
                    self.logger.error(resp.text)
                return None
            return resp
        except Exception as e:
            self.logger.error(
                f"exception occurred while sending request to {url}:\n{e}"
            )
            return None


class RadarrSonarrMonitor(BaseMonitor):
    # Data used by the RadarrSonarrMonitor
    @dataclass
    class MovieRecord:
        title: str
        id: int
        error_time: Optional[str] = None  # TimeStamp
        num_timeleft_samples: int = 0
        num_timeleft_samples_exceeding_max: int = 0

    @dataclass
    class Record:
        lastRun: str  # TimeStamp
        curIter: int = 0
        movies: List["RadarrSonarrMonitor.MovieRecord"] = field(default_factory=list)

        def get_record_from_id(self, movie_id: int):
            for movie in self.movies:
                if movie.id == movie_id:
                    return movie
            return None

    class RecordScope:
        """
        This class is meant to be used as a context manager to manage the record file
        It is meant to be instantiated with a `with` statement
        """
        def _sync_record(self, queue: QueueResourcePagingResource):
            # update the record with the current queue
            for rec in queue.records:
                # newly added movies -- in queue but not in record
                if self.record.get_record_from_id(rec.id) is None:
                    if rec.timeleft is not None:
                        self.record.movies.append(
                            RadarrSonarrMonitor.MovieRecord(
                                title=rec.get_title_or_id(),
                                id=rec.id
                            )
                        )
            # stale movies -- in record but not in queue
            for movie in self.record.movies:
                if queue.get_record_from_id(movie.id) is None:
                    self.record.movies.remove(movie)

        def __init__(
            self, monitor: "RadarrSonarrMonitor", queue: QueueResourcePagingResource, cur_iter: int
        ):
            self.monitor = monitor
            self.queue = queue
            self.record_path = pathlib.Path(monitor.config.record_file_path)

            if self.record_path.exists():
                self.record = from_dict(
                    RadarrSonarrMonitor.Record,
                    json.loads(self.record_path.read_text()),
                )
            else:
                self.record = RadarrSonarrMonitor.Record(lastRun=str(TimeStamp.now()), curIter=cur_iter)
            self.cur_iter = cur_iter
            self.tasks = []
            self._sync_record(queue)

        async def __aenter__(self):
            return self

        def __iter__(self):
            for movie in self.record.movies:
                queue_record = self.queue.get_record_from_id(movie.id)
                yield movie, queue_record

        async def __aexit__(self, exc_t, exc_v, exc_tb):
            await asyncio.gather(*self.tasks)
            self.record.lastRun = str(TimeStamp.now())
            self.record.curIter = self.cur_iter
            self.record_path.write_text(
                json.dumps(asdict(self.record), indent=1), encoding="utf-8"
            )

        def add_task(self, task):
            self.tasks.append(task)

    async def _list_media(self) -> QueueResourcePagingResource:
        resp = await self._send(
            httpx.get,
            f"queue?includeUnknownMovieItems=true&includeMovie=true",
        )
        if not resp:
            return QueueResourcePagingResource([])
        return from_dict(QueueResourcePagingResource, resp.json())

    async def _remove_media_from_queue(
        self,
        movie_id: int,
        redownload: bool = False,
        remove_from_client: bool = True,
        blocklist: bool = True,
        change_category: bool = False,
    ):
        await self._send(
            httpx.delete,
            (
                f"queue/{movie_id}?removeFromClient={remove_from_client}&"
                f"blocklist={blocklist}&skipRedownload={not redownload}&"
                f"changeCategory={change_category}"
            ),
        )

    async def _clear_blocklist(self, movie_id: int | None = None):
        if movie_id is not None:
            await self._send(httpx.post, f"blocklist/{movie_id}")
        else:
            await self._send(
                httpx.post,
                "command",
                json={
                    "name": "clearBlocklist",
                },
            )

    async def _cleanup(self):
        self.logger.info("Shutting down monitor")

    async def _reap_media(self, movie: MovieRecord, queue_rec: QueueResource):
        """
        Attempting to relax the download restrictions for media requests that are not fulfilled for too long
        """
        await self._clear_blocklist(movie_id=queue_rec.movieId)
        await self.search_movie_manually(queue_rec)

    async def search_movie_manually(self, queue_rec: QueueResource):
        """
        Searches the available torrents with relaxed standards
        """

        class Break(Exception):
            pass

        async def search(guid: str, indexer_id: int):
            return await self._send(
                httpx.post,
                "release",
                json={"guid": guid, "indexerId": indexer_id},
                timeout=httpx.Timeout(30.0),
            )

        resp = await self._send(
            httpx.get,
            f"release?movieId={queue_rec.movieId}",
            timeout=httpx.Timeout(30.0),
        )
        if not resp:
            return

        self.logger.info(f"searching for {queue_rec.get_title_or_id()} manually")

        best_candidate: Optional[ReleaseResource] = None

        def comp(r1: ReleaseResource, r2: ReleaseResource) -> bool:
            return (r1.seeders, r1.quality.quality.resolution) < (
                r2.seeders,
                r2.quality.quality.resolution,
            )

        for res_json in resp.json():
            res = from_dict(ReleaseResource, res_json)
            if res.guid is None or not res.seeders:
                continue

            try:
                for rej in res.rejections:
                    if "blocklisted" in rej or "Unknown Movie" in rej:
                        self.logger.info(f"release {res.guid} is rejected, skipping")
                        self.logger.info(f"rejections: {res.rejections}")
                        raise Break()
                has_valid_lang = False
                for lang in res.languages:
                    # either unknown or is the original language
                    if lang.id == 0 or lang in queue_rec.languages:
                        has_valid_lang = True
                        break

                if not has_valid_lang:
                    self.logger.info(
                        f"release {res.guid} has invalid language, skipping"
                    )
                    raise Break()
                if not best_candidate or comp(best_candidate, res):
                    best_candidate = res
            except Break:
                pass

        if best_candidate and best_candidate.guid:
            self.logger.info(
                f"attempt downloading {queue_rec.get_title_or_id()} with {best_candidate.guid}"
            )
            await search(best_candidate.guid, best_candidate.indexerId)
        else:
            self.logger.warning(
                f"movie {queue_rec.get_title_or_id()} has no viable candidate"
            )

    async def _run(self, cur_iter: int):
        self.logger.debug(f"===== Running monitor iteration {cur_iter} =====")
        media_list = await self._list_media()

        async with self.RecordScope(self, media_list, cur_iter) as record_scope:
            for movie, queue_rec in record_scope:
                if queue_rec is None:
                    self.logger.error(
                        f"Queue record for {movie.title} not found in queue"
                    )
                    continue
                if queue_rec.has_error():
                    # the record has an error
                    if movie.error_time is not None:
                        if (
                            TimeStamp.now() - TimeStamp(movie.error_time)
                            > self.config.max_err_time_secs
                        ):
                            self.logger.info(
                                f"{queue_rec.get_title_or_id()} has error [ {queue_rec.errorMessage} ] for too long, blocklisting..."
                            )
                            record_scope.add_task(
                                self._remove_media_from_queue(
                                    queue_rec.id, blocklist=True, redownload=True
                                )
                            )
                    else:
                        movie.error_time = str(TimeStamp.now())
                    continue

                if queue_rec.is_finished() and queue_rec.failed_to_import():
                    # probably a bug in Radarr/Sonarr
                    # finished but failed to import, remove from queue
                    # and don't re-download
                    self.logger.info(
                        f"{queue_rec.get_title_or_id()} is finished but failed to import, removing from queue..."
                    )
                    record_scope.add_task(
                        self._remove_media_from_queue(
                            queue_rec.id, blocklist=False, redownload=False
                        )
                    )
                    continue

                if queue_rec.timeleft is None:
                    # download may not have started yet
                    # do nothing
                    continue

                if queue_rec.size > self.config.max_media_size_bytes:
                    # too large, blocklist
                    self.logger.info(
                        f"{queue_rec.get_title_or_id()} is too large ({queue_rec.size} bytes), blocklisting..."
                    )
                    record_scope.add_task(
                        self._remove_media_from_queue(
                            queue_rec.id, blocklist=True, redownload=True
                        )
                    )
                    continue

                # check for hopeless downloads
                if TimeStamp(queue_rec.timeleft) > self.config.max_download_time_secs:
                    movie.num_timeleft_samples_exceeding_max += 1
                else:
                    movie.num_timeleft_samples += 1

                if (
                    movie.num_timeleft_samples
                    >= self.config.warmup_time_secs // self.config.run_interval_secs
                ):
                    if (
                        movie.num_timeleft_samples_exceeding_max
                        / movie.num_timeleft_samples
                        > self.config.hopeless_threshold
                    ):
                        self.logger.info(
                            f"{queue_rec.get_title_or_id()} is hopeless (num_timeleft_samples_exceeding_max={movie.num_timeleft_samples_exceeding_max}, num_timeleft_samples={movie.num_timeleft_samples}), blocklisting..."
                        )
                        record_scope.add_task(
                            self._remove_media_from_queue(
                                queue_rec.id, blocklist=True, redownload=True
                            )
                        )

                # reap downloads that have been hopeless for too long
                if (
                    TimeStamp.now() - TimeStamp.create(iso8601=queue_rec.added)
                    > self.config.reap_interval_secs
                ):
                    self.logger.info(
                        f"{queue_rec.get_title_or_id()} has been hopeless for too long, reaping..."
                    )
                    record_scope.add_task(self._reap_media(movie, queue_rec))


if __name__ == "__main__":
    monitors: List[BaseMonitor] = []
    config_path = pathlib.Path("config.toml")
    toml_doc = tomlkit.loads(config_path.read_text())
    for raw_dict in toml_doc["monitors"]:  # type: ignore
        monitors.append(RadarrSonarrMonitor(from_dict(MonitorConfig, raw_dict)))

    async def _run():
        tasks = asyncio.gather(
            *(monitor.run() for monitor in monitors), return_exceptions=True
        )
        res = await tasks
        if isinstance(res, list):
            for exc in res:
                if exc:
                    raise exc

    asyncio.run(_run())
