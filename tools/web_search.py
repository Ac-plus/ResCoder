import json
import os
import time
import hashlib
from typing import Any, Dict, List, Optional
import requests

from config.api_keys import BING_API_KEY, BOCHA_API_KEY


# 1) TinyLFU (simplified W-TinyLFU)

class _CountMinSketch(object):
    def __init__(self, width=2048, depth=4, sample_size=10000):
        self.width = int(width)
        self.depth = int(depth)
        self.sample_size = int(sample_size)
        self._n = 0
        self.table = [[0] * self.width for _ in range(self.depth)]

    def _hash_i(self, key, i):
        # stable hash: sha1(key + "#" + i) -> bucket
        s = (str(key) + "#" + str(i)).encode("utf-8", errors="ignore")
        h = hashlib.sha1(s).digest()
        x = int.from_bytes(h[:8], byteorder="little", signed=False)
        return x % self.width

    def increment(self, key, count=1):
        c = int(count)
        for i in range(self.depth):
            j = self._hash_i(key, i)
            v = self.table[i][j] + c
            # cap to avoid huge ints in long runs
            if v > 2147483647:
                v = 2147483647
            self.table[i][j] = v

        self._n += 1
        if self._n >= self.sample_size:
            self._age()
            self._n = 0

    def estimate(self, key):
        mins = None
        for i in range(self.depth):
            j = self._hash_i(key, i)
            v = self.table[i][j]
            mins = v if mins is None else (v if v < mins else mins)
        return 0 if mins is None else int(mins)

    def _age(self):
        # halve all counters (aging)
        for i in range(self.depth):
            row = self.table[i]
            for j in range(self.width):
                row[j] >>= 1


class _LRUWithTTL(object):
    def __init__(self, capacity, default_ttl_sec):
        from collections import OrderedDict
        self.capacity = int(capacity)
        self.default_ttl_sec = int(default_ttl_sec)
        self._od = OrderedDict()  # key -> (expire_ts, value)

    def _now(self):
        return time.time()

    def _expired(self, expire_ts):
        return self._now() > expire_ts

    def get(self, key):
        item = self._od.get(key)
        if not item:
            return None
        expire_ts, value = item
        if self._expired(expire_ts):
            try:
                del self._od[key]
            except Exception:
                pass
            return None
        # mark as recently used
        try:
            self._od.move_to_end(key, last=True)
        except Exception:
            pass
        return value

    def set(self, key, value, ttl_sec=None):
        ttl = self.default_ttl_sec if ttl_sec is None else int(ttl_sec)
        expire_ts = self._now() + ttl

        if key in self._od:
            self._od[key] = (expire_ts, value)
            try:
                self._od.move_to_end(key, last=True)
            except Exception:
                pass
            return

        self._od[key] = (expire_ts, value)
        try:
            self._od.move_to_end(key, last=True)
        except Exception:
            pass

        # NOTE: do NOT evict here; TinyLFU controls eviction.
        # This class provides primitives for TinyLFU.

    def delete(self, key):
        try:
            del self._od[key]
        except Exception:
            pass

    def pop_lru(self):
        if not self._od:
            return None
        # pop least recently used
        k, (expire_ts, v) = self._od.popitem(last=False)
        return k, expire_ts, v

    def peek_lru_key(self):
        if not self._od:
            return None
        return next(iter(self._od.keys()))

    def __len__(self):
        return len(self._od)

    def items_count(self):
        return len(self._od)


class _TinyLFU(object):
    def __init__(self, ttl_seconds=900, max_items=256, window_ratio=0.10,
                 cms_width=2048, cms_depth=4, cms_sample_size=10000, doorkeeper_max=200000):
        self.ttl_seconds = int(ttl_seconds)
        self.max_items = int(max_items)

        # capacity split
        wcap = int(max(1, int(self.max_items * float(window_ratio))))
        mcap = int(max(1, self.max_items - wcap))
        self._wcap = wcap
        self._mcap = mcap

        self.window = _LRUWithTTL(capacity=wcap, default_ttl_sec=self.ttl_seconds)
        self.main = _LRUWithTTL(capacity=mcap, default_ttl_sec=self.ttl_seconds)

        self.sketch = _CountMinSketch(width=cms_width, depth=cms_depth, sample_size=cms_sample_size)
        self.doorkeeper = set()
        self.doorkeeper_max = int(doorkeeper_max)

    def _touch(self, key):
        # record every access attempt to build frequency
        self.sketch.increment(key)

    def get(self, key):
        self._touch(key)

        v = self.window.get(key)
        if v is not None:
            return v

        v = self.main.get(key)
        if v is not None:
            return v

        return None

    def set(self, key, value):
        self._touch(key)

        # update in place if exists
        if self.window.get(key) is not None:
            self.window.set(key, value, ttl_sec=self.ttl_seconds)
            return
        if self.main.get(key) is not None:
            self.main.set(key, value, ttl_sec=self.ttl_seconds)
            return

        # insert into window
        self.window.set(key, value, ttl_sec=self.ttl_seconds)

        # enforce total capacity by controlling window overflow & main admission
        self._rebalance_after_window_insert()

    def _rebalance_after_window_insert(self):
        # If window exceeds capacity, move LRU candidates out (one by one).
        # We check by len(window) because window.set doesn't evict.
        while len(self.window) > self._wcap:
            popped = self.window.pop_lru()
            if popped is None:
                break
            cand_key, cand_expire_ts, cand_val = popped

            # if candidate already expired at pop time, skip
            if time.time() > cand_expire_ts:
                continue

            self._admit_to_main(cand_key, cand_val)

        # If main exceeds capacity (shouldn't unless config changes), trim LRU
        while len(self.main) > self._mcap:
            victim = self.main.pop_lru()
            if victim is None:
                break

    def _doorkeeper_add(self, key):
        if len(self.doorkeeper) >= self.doorkeeper_max:
            # demo-grade reset
            self.doorkeeper.clear()
        self.doorkeeper.add(key)

    def _admit_to_main(self, cand_key, cand_val):
        # doorkeeper: require at least 2 touches to compete for main
        if cand_key not in self.doorkeeper:
            self._doorkeeper_add(cand_key)
            return

        # main not full -> admit directly
        if len(self.main) < self._mcap:
            self.main.set(cand_key, cand_val, ttl_sec=self.ttl_seconds)
            return

        # main full -> compare with victim (main LRU)
        victim_key = self.main.peek_lru_key()
        if victim_key is None:
            self.main.set(cand_key, cand_val, ttl_sec=self.ttl_seconds)
            return

        fc = self.sketch.estimate(cand_key)
        fv = self.sketch.estimate(victim_key)

        # admit only if candidate is more frequent
        if fc > fv:
            self.main.delete(victim_key)
            self.main.set(cand_key, cand_val, ttl_sec=self.ttl_seconds)
        else:
            pass


class SimpleTTLCache(object):
    def __init__(self, ttl_seconds: int = 900, max_items: int = 128):
        self.ttl_seconds = int(ttl_seconds)
        self.max_items = int(max_items)
        # TinyLFU: tuned for demo; you can adjust window_ratio / cms_sample_size via constants if needed
        # IMPORTANT: ttl is handled per-entry, and strict matching is preserved by key itself.
        self._impl = _TinyLFU(
            ttl_seconds=self.ttl_seconds,
            max_items=self.max_items,
            window_ratio=0.10,
            cms_width=2048,
            cms_depth=4,
            cms_sample_size=10000,
            doorkeeper_max=200000,
        )

    def get(self, key: str) -> Optional[Any]:
        return self._impl.get(key)

    def set(self, key: str, value: Any) -> None:
        self._impl.set(key, value)


_CACHE = SimpleTTLCache(ttl_seconds=900, max_items=256)


def _make_cache_key(payload: Dict[str, Any]) -> str:
    s = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

# 2) 统一后端接口

class SearchBackend(object):
    def search(
        self,
        query: str,
        top_k: int,
        recency_days: Optional[int],
        domains: Optional[List[str]],
        timeout: float,
        max_retries: int,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

# 3) Bocha Web Search 后端

class BochaBackend(SearchBackend):
    def __init__(self):
        self.api_key = BOCHA_API_KEY # os.getenv("BOCHA_API_KEY") or os.getenv("BOCHA_SEARCH_API_KEY")
        self.endpoint = os.getenv("BOCHA_ENDPOINT", "https://api.bochaai.com/v1/web-search")
        if not self.api_key:
            raise ValueError("Missing BOCHA_API_KEY (or BOCHA_SEARCH_API_KEY) in environment variables.")

    @staticmethod
    def _recency_to_freshness(recency_days: Optional[int]) -> str:
        if recency_days is None:
            return "noLimit"
        try:
            d = int(recency_days)
        except Exception:
            return "noLimit"

        if d <= 1:
            return "oneDay"
        if d <= 7:
            return "oneWeek"
        if d <= 31:
            return "oneMonth"
        if d <= 365:
            return "oneYear"
        return "noLimit"

    @staticmethod
    def _extract_items_from_response(data: Dict[str, Any]) -> List[Dict[str, Any]]:
        if isinstance(data, dict):
            wp = data.get("webPages")
            if isinstance(wp, dict):
                v = wp.get("value")
                if isinstance(v, list):
                    return v

        # 一些实现/封装可能包一层 data
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            inner = data["data"]
            wp = inner.get("webPages")
            if isinstance(wp, dict) and isinstance(wp.get("value"), list):
                return wp["value"]

            # 如果 inner 里直接就是 value 列表
            if isinstance(inner.get("value"), list):
                return inner["value"]

        # 最后的兜底：尝试在顶层找 value
        if isinstance(data, dict) and isinstance(data.get("value"), list):
            return data["value"]

        return []

    def search(
        self,
        query: str,
        top_k: int,
        recency_days: Optional[int],
        domains: Optional[List[str]],
        timeout: float,
        max_retries: int,
    ) -> List[Dict[str, Any]]:
        freshness = self._recency_to_freshness(recency_days)

        # 域名限制：如果你只有 domains（白名单），最稳妥的是用 site: 拼到 query 里（搜索引擎普遍支持）
        q = (query or "").strip()
        if domains:
            site_query = " OR ".join(["site:{0}".format(d) for d in domains])
            q = "{0} ({1})".format(q, site_query)

        payload = {
            "query": q,
            "summary": True,  # 你的 tool 目标是给 LLM 用，建议直接开 summary
            "freshness": freshness,  # oneDay/oneWeek/oneMonth/oneYear/noLimit
            "count": max(1, min(int(top_k), 50)),  # 官方说明最多 50
        }

        headers = {
            "Authorization": "Bearer {0}".format(self.api_key),
            "Content-Type": "application/json",
        }

        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                print("- [web_search] Bocha request attempt {0}/{1}".format(attempt, max_retries))
                r = requests.post(self.endpoint, headers=headers, json=payload, timeout=timeout)
                if r.status_code != 200:
                    last_err = "HTTP {0}: {1}".format(r.status_code, r.text[:300])
                    time.sleep(0.5 * attempt)
                    continue

                data = r.json()
                raw_items = self._extract_items_from_response(data)

                results = []
                for idx, it in enumerate(raw_items[:top_k]):
                    results.append({
                        "id": "r{0}".format(idx + 1),
                        "title": it.get("name") or it.get("title"),
                        "url": it.get("url") or it.get("link"),
                        "snippet": it.get("summary") or it.get("snippet"),
                        "source": "bocha",
                        "published_time": it.get("publishedTime") or it.get("datePublished") or it.get("dateLastCrawled"),
                        "site_name": it.get("siteName"),
                        "site_icon": it.get("siteIcon"),
                    })

                return results

            except Exception as e:
                last_err = str(e)
                time.sleep(0.5 * attempt)

        raise RuntimeError("Bocha search failed: {0}".format(last_err))

# 4) 选择后端 + 统一入口函数（暴露给模型的 tool）

def _get_backend() -> SearchBackend:
    backend = (os.getenv("SEARCH_BACKEND") or "bocha").strip().lower()
    if backend == "bocha":
        return BochaBackend()
    raise ValueError("Unknown SEARCH_BACKEND: {0}".format(backend))


def web_search(
    query: str,
    top_k: int = 6,
    recency_days: Optional[int] = None,
    domains: Optional[List[str]] = None,
) -> str:
    payload = {
        "query": query,
        "top_k": int(top_k),
        "recency_days": recency_days if recency_days is None else int(recency_days),
        "domains": domains or [],
        "backend": (os.getenv("SEARCH_BACKEND") or "bocha").strip().lower(),
    }

    # 1) 缓存命中
    ck = _make_cache_key(payload)
    cached = _CACHE.get(ck)
    if cached is not None:
        print("- [web_search] cache hit")
        return cached

    # 2) 参数整理与基本校验
    q = (query or "").strip()
    if not q:
        out = json.dumps({"ok": False, "error": "Empty query"}, ensure_ascii=False)
        _CACHE.set(ck, out)
        return out

    top_k = max(1, min(int(top_k), 10))  # tool 层面先限制到 10（后端最多 50）
    timeout = float(os.getenv("WEBSEARCH_TIMEOUT", "12"))
    max_retries = int(os.getenv("WEBSEARCH_RETRIES", "3"))

    # 3) 调后端
    try:
        print("- [web_search] query={0} top_k={1}".format(repr(q), top_k))
        backend = _get_backend()
        results = backend.search(
            query=q,
            top_k=top_k,
            recency_days=recency_days,
            domains=domains,
            timeout=timeout,
            max_retries=max_retries,
        )

        out_obj = {
            "ok": True,
            "query": q,
            "top_k": top_k,
            "recency_days": recency_days,
            "domains": domains or [],
            "results": results,
        }
        out = json.dumps(out_obj, ensure_ascii=False)
        _CACHE.set(ck, out)
        return out

    except Exception as e:
        out = json.dumps({"ok": False, "query": q, "error": str(e)}, ensure_ascii=False)
        _CACHE.set(ck, out)
        return out
