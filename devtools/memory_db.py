"""In-memory stand-in for the Motor collections main.py uses — LOCAL
DEVELOPMENT ONLY.

Implements exactly the async surface main.py calls (find / find_one /
insert_one / find_one_and_update / update_many / delete_one / create_index)
and the query/update operators it uses ($in, $exists, $set, $unset, dotted
keys, array-contains equality). Nothing here opens a network connection, so
a process wired to these collections cannot read or write any real database.
"""
import copy
from types import SimpleNamespace

from bson import ObjectId

_MISSING = object()


def _get_path(doc, dotted):
    value = doc
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _value_matches(value, condition):
    if isinstance(condition, dict) and any(str(k).startswith("$") for k in condition):
        for op, arg in condition.items():
            if op == "$in":
                candidates = value if isinstance(value, list) else [value]
                if not any(c in arg for c in candidates if c is not _MISSING):
                    return False
            elif op == "$exists":
                if (value is not _MISSING) != bool(arg):
                    return False
            elif op == "$ne":
                if value == arg:
                    return False
            else:
                raise NotImplementedError(f"memory_db: unsupported operator {op}")
        return True
    if value is _MISSING:
        return condition is None
    if isinstance(value, list) and not isinstance(condition, list):
        return condition in value
    return value == condition


def matches(doc, query):
    return all(_value_matches(_get_path(doc, key), cond) for key, cond in (query or {}).items())


def _project(doc, projection):
    if not projection:
        return copy.deepcopy(doc)
    include = {k for k, v in projection.items() if v}
    out = {k: copy.deepcopy(v) for k, v in doc.items() if k in include}
    if projection.get("_id", 1) and "_id" in doc:
        out["_id"] = doc["_id"]
    return out


def _set_path(doc, dotted, value):
    parts = dotted.split(".")
    target = doc
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = copy.deepcopy(value)


def _apply_update(doc, update):
    for key, value in (update.get("$set") or {}).items():
        _set_path(doc, key, value)
    for key in (update.get("$unset") or {}):
        parts = key.split(".")
        target = doc
        for part in parts[:-1]:
            target = target.get(part, {})
        target.pop(parts[-1], None)


class MemoryCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction=1):
        if isinstance(key, list):
            for field, dirn in reversed(key):
                self._docs.sort(key=lambda d: str(d.get(field) or ""), reverse=dirn < 0)
        else:
            self._docs.sort(key=lambda d: str(d.get(key) or ""), reverse=direction < 0)
        return self

    def __aiter__(self):
        self._iter = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration

    async def to_list(self, length=None):
        return list(self._docs if length is None else self._docs[:length])


class MemoryCollection:
    def __init__(self, docs=None):
        self.docs = [copy.deepcopy(d) for d in (docs or [])]
        for doc in self.docs:
            doc.setdefault("_id", ObjectId())

    async def create_index(self, *args, **kwargs):
        return "memory-index"

    def find(self, query=None, projection=None):
        return MemoryCursor([_project(d, projection) for d in self.docs if matches(d, query)])

    async def find_one(self, query=None, projection=None):
        for doc in self.docs:
            if matches(doc, query):
                return _project(doc, projection)
        return None

    async def insert_one(self, doc):
        stored = copy.deepcopy(doc)
        stored.setdefault("_id", ObjectId())
        doc["_id"] = stored["_id"]
        self.docs.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])

    async def find_one_and_update(self, query, update, return_document=False, **kwargs):
        for doc in self.docs:
            if matches(doc, query):
                before = copy.deepcopy(doc)
                _apply_update(doc, update)
                return copy.deepcopy(doc) if return_document else before
        return None

    async def update_many(self, query, update):
        count = 0
        for doc in self.docs:
            if matches(doc, query):
                _apply_update(doc, update)
                count += 1
        return SimpleNamespace(matched_count=count, modified_count=count)

    async def delete_one(self, query):
        for i, doc in enumerate(self.docs):
            if matches(doc, query):
                del self.docs[i]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)


class MemoryDatabase:
    def __init__(self):
        self._collections = {}

    def __getitem__(self, name):
        return self._collections.setdefault(name, MemoryCollection())


class NoPhotoBucket:
    """Synthetic data carries no photographs; any photo request is a clean
    not-found / rejection rather than a call to real storage."""

    async def upload_from_stream(self, *args, **kwargs):
        raise RuntimeError("Photo upload is disabled in the local synthetic environment")

    async def open_download_stream(self, *args, **kwargs):
        raise FileNotFoundError("No photos in the local synthetic environment")
