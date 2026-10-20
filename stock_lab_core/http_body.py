"""Read response bodies with a byte cap and a wall-clock budget."""

import requests


def read_response_body(response, deadline, clock, *, max_bytes=2 * 1024 * 1024):
    raw = getattr(response, "raw", None)
    read1 = getattr(raw, "read1", None)
    if callable(read1):
        def chunks():
            while True:
                chunk = read1(65536, decode_content=True)
                if not chunk:
                    break
                yield chunk
        parts = chunks()
    elif callable(getattr(response, "iter_content", None)):
        parts = response.iter_content(chunk_size=1)
    else:
        # Injected in-memory responses have no network stream.
        return response.text
    output, size = [], 0
    for chunk in parts:
        if clock() >= deadline:
            raise requests.ReadTimeout("Response body deadline reached")
        size += len(chunk)
        if size > max_bytes:
            raise ValueError("Response body exceeds size limit")
        output.append(chunk)
    return b"".join(output)
