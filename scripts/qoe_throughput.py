#!/usr/bin/env python3
"""
Motor de medición de velocidad por tiempo (solo biblioteca estándar).

Por qué existe
--------------
Las mediciones anteriores descargaban una cantidad fija de bytes (por ejemplo
32 MB repartidos en 8 conexiones) y dividían entre el tiempo total. Con un
plan de 600 Mbps esa transferencia dura menos de un segundo, y casi todo ese
tiempo se va en el handshake TCP/TLS y en el arranque lento de TCP: la
velocidad resultante sale muy por debajo de la real y varía mucho de una
corrida a otra. Los speedtest reales (Ookla, fast.com) miden durante un tiempo
fijo con varias conexiones y descartan los primeros segundos.

Este módulo hace lo mismo:
- N conexiones en paralelo durante `duration_s` segundos.
- Cada conexión repite peticiones mientras quede tiempo (sirve también para
  archivos pequeños, que se vuelven a pedir).
- Los bytes se leen y se descartan en memoria (no se escriben a disco).
- Se descartan los primeros `warmup_s` segundos y la velocidad se calcula con
  la ventana estable.
"""

from __future__ import annotations

import http.client
import os
import re
import socket
import ssl
import statistics
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Sequence

READ_BLOCK_BYTES = 64 * 1024
SAMPLE_INTERVAL_S = 0.2


def _ssl_context(verify_tls: bool) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not verify_tls:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # nosec B501 - solo si el catálogo lo pide explícitamente
    return ctx


def _validate_url(url: str) -> None:
    if not (url.lower().startswith("http://") or url.lower().startswith("https://")):
        raise ValueError(f"URL must start with http:// or https://: {url}")


class _ByteCounter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total = 0
        self.requests = 0
        self.errors: List[str] = []

    def add(self, n: int) -> None:
        with self._lock:
            self.total += n

    def request_done(self) -> None:
        with self._lock:
            self.requests += 1

    def error(self, msg: str) -> None:
        with self._lock:
            if len(self.errors) < 10:
                self.errors.append(msg)

    def value(self) -> int:
        with self._lock:
            return self.total


def _steady_mbps(samples: List[tuple], warmup_s: float) -> float:
    """Velocidad (Mbps) en la ventana posterior al calentamiento."""
    if len(samples) < 2:
        return 0.0
    t0 = samples[0][0]
    start = None
    for t, b in samples:
        if t - t0 >= warmup_s:
            start = (t, b)
            break
    end = samples[-1]
    if start is None or end[0] - start[0] < 0.5:
        # La transferencia terminó antes del calentamiento: usar todo el intervalo.
        start = samples[0]
    elapsed = end[0] - start[0]
    if elapsed <= 0:
        return 0.0
    return round(((end[1] - start[1]) * 8) / (elapsed * 1_000_000), 2)


def _run_timed(worker: Callable[[int, float, _ByteCounter], None], connections: int,
               duration_s: float, warmup_s: float) -> Dict[str, Any]:
    counter = _ByteCounter()
    started = time.perf_counter()
    deadline = started + duration_s
    threads = [
        threading.Thread(target=worker, args=(i, deadline, counter), daemon=True)
        for i in range(max(1, connections))
    ]
    for th in threads:
        th.start()

    samples = [(started, 0)]
    while time.perf_counter() < deadline:
        time.sleep(SAMPLE_INTERVAL_S)
        samples.append((time.perf_counter(), counter.value()))
        if not any(th.is_alive() for th in threads):
            break
    for th in threads:
        th.join(timeout=5)

    total_elapsed = samples[-1][0] - started
    return {
        "Mbps": _steady_mbps(samples, warmup_s),
        "Bytes": counter.value(),
        "DurationMs": round(total_elapsed * 1000, 2),
        "Requests": counter.requests,
        "Errors": counter.errors,
    }


def measure_download(
    urls: Sequence[str],
    connections: int = 8,
    duration_s: float = 10.0,
    warmup_s: float = 2.0,
    request_bytes: int = 0,
    timeout_s: float = 10.0,
    user_agent: str = "",
    verify_tls: bool = True,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Descarga durante `duration_s` con `connections` conexiones en paralelo.

    `urls` se reparten entre conexiones. Si `request_bytes` > 0 se pide un
    Range `bytes=0-(request_bytes-1)` en cada petición.
    """
    if not urls:
        raise ValueError("measure_download requires at least one URL.")
    for u in urls:
        _validate_url(u)
    ctx = _ssl_context(verify_tls)

    def worker(idx: int, deadline: float, counter: _ByteCounter) -> None:
        # Cada conexión se reutiliza entre peticiones (keep-alive), como hace un
        # navegador. Con archivos pequeños, abrir una conexión TCP+TLS por pedido
        # hacía que casi todo el tiempo se fuera en handshakes (Disney+: 55 Mbps).
        conns: Dict[tuple, http.client.HTTPConnection] = {}

        def get_conn(parsed: urllib.parse.SplitResult, timeout: float) -> http.client.HTTPConnection:
            key = (parsed.scheme, parsed.hostname, parsed.port)
            conn = conns.get(key)
            if conn is None:
                if parsed.scheme == "https":
                    conn = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=timeout, context=ctx)
                else:
                    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)
                conns[key] = conn
            return conn

        def drop(parsed: urllib.parse.SplitResult) -> None:
            conn = conns.pop((parsed.scheme, parsed.hostname, parsed.port), None)
            if conn is not None:
                conn.close()

        n = 0
        try:
            while time.perf_counter() < deadline:
                url = urls[(idx + n) % len(urls)]
                n += 1
                for _ in range(4):  # hasta 3 redirecciones
                    parsed = urllib.parse.urlsplit(url)
                    path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
                    headers = {"Accept-Encoding": "identity"}
                    if user_agent:
                        headers["User-Agent"] = user_agent
                    if request_bytes > 0:
                        headers["Range"] = f"bytes=0-{request_bytes - 1}"
                    headers.update(extra_headers or {})
                    remaining = max(1.0, deadline - time.perf_counter())
                    try:
                        conn = get_conn(parsed, min(timeout_s, remaining + 2))
                        conn.request("GET", path, headers=headers)
                        resp = conn.getresponse()
                    except Exception as e:
                        drop(parsed)
                        counter.error(f"{type(e).__name__}: {e}")
                        time.sleep(0.2)
                        break
                    if resp.status in (301, 302, 303, 307, 308) and resp.getheader("Location"):
                        resp.read()
                        url = urllib.parse.urljoin(url, resp.getheader("Location"))
                        try:
                            _validate_url(url)
                        except ValueError as e:
                            counter.error(str(e))
                            break
                        continue
                    if resp.status >= 400:
                        resp.read()
                        counter.error(f"HTTP {resp.status} {url}")
                        time.sleep(0.2)
                        break
                    complete = False
                    try:
                        while time.perf_counter() < deadline:
                            chunk = resp.read(READ_BLOCK_BYTES)
                            if not chunk:
                                complete = True
                                break
                            counter.add(len(chunk))
                    except Exception as e:
                        counter.error(f"{type(e).__name__}: {e}")
                    if complete:
                        counter.request_done()
                        if resp.will_close:
                            drop(parsed)
                    else:
                        drop(parsed)  # respuesta a medias: la conexión no se puede reutilizar
                    break
        finally:
            for conn in conns.values():
                conn.close()

    return _run_timed(worker, connections, duration_s, warmup_s)


def measure_upload(
    urls: Sequence[str],
    connections: int = 8,
    duration_s: float = 10.0,
    warmup_s: float = 2.0,
    payload_bytes: int = 8 * 1024 * 1024,
    timeout_s: float = 10.0,
    user_agent: str = "",
    verify_tls: bool = True,
    method: str = "POST",
    content_type: str = "application/octet-stream",
) -> Dict[str, Any]:
    """Sube datos aleatorios durante `duration_s`, contando los bytes enviados."""
    if not urls:
        raise ValueError("measure_upload requires at least one URL.")
    for u in urls:
        _validate_url(u)
    ctx = _ssl_context(verify_tls)
    block = os.urandom(READ_BLOCK_BYTES)
    payload_bytes = max(READ_BLOCK_BYTES, payload_bytes)

    def worker(idx: int, deadline: float, counter: _ByteCounter) -> None:
        n = 0
        while time.perf_counter() < deadline:
            url = urls[(idx + n) % len(urls)]
            n += 1
            parsed = urllib.parse.urlsplit(url)
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            remaining = max(1.0, deadline - time.perf_counter())
            conn_timeout = min(timeout_s, remaining + 2)
            try:
                if parsed.scheme == "https":
                    conn = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=conn_timeout, context=ctx)
                else:
                    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=conn_timeout)
                try:
                    conn.putrequest(method, path)
                    conn.putheader("Content-Type", content_type)
                    conn.putheader("Content-Length", str(payload_bytes))
                    if user_agent:
                        conn.putheader("User-Agent", user_agent)
                    conn.endheaders()
                    sent = 0
                    while sent < payload_bytes:
                        size = min(READ_BLOCK_BYTES, payload_bytes - sent)
                        conn.send(block[:size])
                        sent += size
                        counter.add(size)
                        if time.perf_counter() >= deadline:
                            break
                    if sent >= payload_bytes:
                        resp = conn.getresponse()
                        resp.read()
                        if resp.status >= 400:
                            counter.error(f"HTTP {resp.status}")
                        counter.request_done()
                finally:
                    conn.close()
            except Exception as e:
                counter.error(f"{type(e).__name__}: {e}")
                time.sleep(0.2)

    return _run_timed(worker, connections, duration_s, warmup_s)


class high_res_timer:
    """Sube la resolución del reloj de Windows a 1 ms mientras se mide.

    Por defecto Windows despierta los sockets en ticks de 15,6 ms, así que una
    conexión de 3 ms se registra como 15,6 ms y una de 20 ms como 31,2 ms. Con
    `timeBeginPeriod(1)` la latencia medida vuelve a ser la real. En otros
    sistemas no hace nada.
    """

    def __enter__(self) -> "high_res_timer":
        self._winmm = None
        if os.name == "nt":
            try:
                import ctypes
                self._winmm = ctypes.windll.winmm  # type: ignore[attr-defined]
                self._winmm.timeBeginPeriod(1)
            except Exception:
                self._winmm = None
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._winmm is not None:
            try:
                self._winmm.timeEndPeriod(1)
            except Exception:
                pass


def resolve_host(host: str, port: int = 443, timeout_s: float = 3.0) -> Optional[tuple]:
    """Resuelve `host` una vez. Devuelve (familia, dirección) o None.

    `getaddrinfo` no acepta tiempo límite, así que corre en un hilo aparte: con
    el DNS caído puede tardar decenas de segundos y no debe frenar la medición.
    """
    try:
        info = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, flags=socket.AI_NUMERICHOST)
        return info[0][0], info[0][4]
    except OSError:
        pass
    box: List[Any] = []

    def work() -> None:
        try:
            info = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            v4 = [i for i in info if i[0] == socket.AF_INET]
            pick = (v4 or info)[0]
            box.append((pick[0], pick[4]))
        except OSError:
            pass

    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(timeout_s)
    return box[0] if box else None


def tcp_connect_ms(addr: tuple, timeout_s: float = 2.0) -> Optional[float]:
    """Tiempo de conexión TCP a una dirección ya resuelta, en ms. None si no conecta."""
    family, sockaddr = addr
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(timeout_s)
    t0 = time.perf_counter()
    try:
        sock.connect(sockaddr)
        return (time.perf_counter() - t0) * 1000
    except OSError:
        return None
    finally:
        try:
            sock.close()
        except OSError:
            pass


def summarize_latency(samples: Sequence[Optional[float]]) -> Dict[str, Any]:
    """Resume una serie de muestras (ms o None si no hubo respuesta)."""
    rtts = [s for s in samples if s is not None]
    total = max(1, len(samples))
    if rtts:
        diffs = [abs(rtts[i] - rtts[i - 1]) for i in range(1, len(rtts))]
        ordered = sorted(rtts)
        latency = round(statistics.median(rtts), 2)
        p95 = round(ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))], 2)
        jitter = round(statistics.mean(diffs), 2) if diffs else 0.0
    else:
        latency, p95, jitter = 0.0, 0.0, 0.0
    return {
        "LatencyMs": latency,
        "P95Ms": p95,
        "JitterMs": jitter,
        "LossPercentage": round((len(samples) - len(rtts)) * 100.0 / total, 1),
        "Samples": len(rtts),
    }


def measure_tcp_latency(host: str, port: int = 443, count: int = 10, timeout_s: float = 2.0,
                        interval_s: float = 0.1) -> Dict[str, Any]:
    """Latencia por tiempo de conexión TCP (no depende de ICMP, que suele estar filtrado).

    El nombre se resuelve una sola vez y fuera del cronómetro: antes cada
    muestra incluía la consulta DNS y la latencia salía inflada.
    """
    count = max(1, count)
    addr = resolve_host(host, port, timeout_s=max(timeout_s, 3.0))
    if addr is None:
        return summarize_latency([None] * count)
    samples: List[Optional[float]] = []
    with high_res_timer():
        for i in range(count):
            samples.append(tcp_connect_ms(addr, timeout_s))
            if i < count - 1:
                time.sleep(interval_s)
    return summarize_latency(samples)


# ---------------------------------------------------------------------------
# fast.com (Netflix) sin navegador
# ---------------------------------------------------------------------------
FAST_HOME = "https://fast.com/"
FAST_API = "https://api.fast.com/netflix/speedtest/v2"
FAST_DEFAULT_TOKEN = "YXNkZmFzZGxmbnNkYWZoYXNkZmhrYWxm"  # token público embebido en el JS de fast.com


def _http_get_text(url: str, timeout_s: float, user_agent: str, verify_tls: bool) -> str:
    _validate_url(url)
    req = urllib.request.Request(url)
    if user_agent:
        req.add_header("User-Agent", user_agent)
    with urllib.request.urlopen(req, context=_ssl_context(verify_tls), timeout=timeout_s) as resp:  # nosec B310 - esquema validado
        return resp.read().decode("utf-8", errors="replace")


def get_fast_token(timeout_s: float = 10.0, user_agent: str = "", verify_tls: bool = True) -> str:
    """Lee el token público del JS de fast.com; si falla, usa el conocido."""
    try:
        html = _http_get_text(FAST_HOME, timeout_s, user_agent, verify_tls)
        m = re.search(r'src="(/app-[A-Za-z0-9]+\.js)"', html)
        if m:
            js = _http_get_text(urllib.parse.urljoin(FAST_HOME, m.group(1)), timeout_s, user_agent, verify_tls)
            t = re.search(r'token:"([A-Za-z0-9]+)"', js)
            if t:
                return t.group(1)
    except Exception:
        pass
    return FAST_DEFAULT_TOKEN


def get_fast_targets(url_count: int = 5, timeout_s: float = 10.0, user_agent: str = "",
                     verify_tls: bool = True) -> Dict[str, Any]:
    """Devuelve las OCAs (cachés de Netflix) que fast.com asigna a este cliente."""
    import json

    token = get_fast_token(timeout_s, user_agent, verify_tls)
    query = urllib.parse.urlencode({"https": "true", "token": token, "urlCount": max(1, url_count)})
    data = json.loads(_http_get_text(f"{FAST_API}?{query}", timeout_s, user_agent, verify_tls))
    targets = []
    for t in data.get("targets", []):
        url = t.get("url", "")
        if not url:
            continue
        loc = t.get("location", {}) or {}
        targets.append({
            "url": url,
            "host": urllib.parse.urlsplit(url).hostname or "",
            "city": loc.get("city", ""),
            "country": loc.get("country", ""),
        })
    client = data.get("client", {}) or {}
    return {
        "targets": targets,
        "client_asn": str(client.get("asn", "")),
        "client_city": (client.get("location", {}) or {}).get("city", ""),
    }


def fast_range_url(url: str, size: int) -> str:
    """fast.com convierte .../speedtest?x en .../speedtest/range/0-N?x."""
    return url.replace("/speedtest", f"/speedtest/range/0-{max(0, size)}", 1)


# ---------------------------------------------------------------------------
# Servidores Ookla (OoklaServer) por HTTP
# ---------------------------------------------------------------------------
def ookla_urls(host: str, port: int = 8080, scheme: str = "http", download_bytes: int = 25_000_000) -> Dict[str, str]:
    base = f"{scheme}://{host}:{port}"
    return {
        "hello": f"{base}/hello",
        "download": f"{base}/download?size={download_bytes}",
        "upload": f"{base}/upload",
    }
