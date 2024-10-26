"""Stuff missing from/awkward to do with anyio."""

import contextlib
import math

import anyio
import anyio.streams.buffered
import anyio.streams.stapled


def create_pipe():
    """Create a pair of socket-like objects that are connected to each other."""

    left_send, right_receive = anyio.create_memory_object_stream(math.inf)
    right_receive = anyio.streams.buffered.BufferedByteReceiveStream(right_receive)
    right_send, left_receive = anyio.create_memory_object_stream(math.inf)
    left_receive = anyio.streams.buffered.BufferedByteReceiveStream(left_receive)
    left_end = anyio.streams.stapled.StapledByteStream(left_send, left_receive)
    right_end = anyio.streams.stapled.StapledByteStream(right_send, right_receive)
    return left_end, right_end


class _Future:
    value = None

    def __init__(self):
        self.event = anyio.Event()

    def set_value(self, value):
        """Cause any tasks running x = await self.wait() to resume (with x = value)."""

        self.value = value
        self.event.set()

    async def wait(self):
        """Wait for self.set_value(x) to be called, then return x."""

        await self.event.wait()
        return self.value

    def __await__(self):
        return self.wait().__await__()


class _TaskGroupWrapper:

    def __init__(self, tg):
        self.tg = tg

    def start_soon(self, func, *args, **kwargs):
        """Schedule func(*args) to run soon. Await this to get func()'s return value."""

        future = _Future()

        async def wrapper():
            future.set_value(await func(*args))

        self.tg.start_soon(wrapper, **kwargs)

        return future


@contextlib.asynccontextmanager
async def create_task_group():
    """Create a TaskGroup whose start_soon returns a future of the called func's return value."""

    async with anyio.create_task_group() as tg:
        yield _TaskGroupWrapper(tg)
