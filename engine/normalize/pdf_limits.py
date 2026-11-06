"""Bound PDF Flate streams while the OS ceiling covers other parser allocations."""

import contextvars
import zlib
from contextlib import contextmanager


class PDFResourceLimitError(ValueError):
    pass


_budget = contextvars.ContextVar("pdf_decode_budget", default=None)


class _Inflater:
    def __init__(self, inner):
        self.inner = inner

    def decompress(self, data, max_length=0):
        budget = _budget.get()
        if budget is None:
            return self.inner.decompress(data, max_length)
        limit = min(max_length or budget[0] + 1, budget[0] + 1)
        result = self.inner.decompress(data, limit)
        budget[0] -= len(result)
        if budget[0] < 0 or self.inner.unconsumed_tail:
            raise PDFResourceLimitError("PDF decompression limit exceeded")
        return result

    def __getattr__(self, name):
        return getattr(self.inner, name)


class _BoundedZlib:
    error = zlib.error

    def decompressobj(self, *args, **kwargs):
        return _Inflater(zlib.decompressobj(*args, **kwargs))

    def decompress(self, data, wbits=zlib.MAX_WBITS, bufsize=zlib.DEF_BUF_SIZE):
        if _budget.get() is None:
            return zlib.decompress(data, wbits, bufsize)
        inflater = self.decompressobj(wbits)
        result = inflater.decompress(data)
        if not inflater.eof:
            raise zlib.error("Incomplete PDF compressed stream")
        return result


@contextmanager
def pdf_decode_budget(limit):
    # Change only pdfminer's module reference; other zlib users remain untouched.
    from pdfminer import pdftypes

    pdftypes.zlib = _BoundedZlib()
    token = _budget.set([limit])
    try:
        yield
    finally:
        _budget.reset(token)
