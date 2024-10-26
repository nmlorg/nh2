"""Tests for nh2.anyio_util."""

import anyio
import pytest

import nh2.anyio_util

pytestmark = pytest.mark.anyio


async def test_create_pipe():
    """Test nh2.anyio_util.create_pipe."""

    left, right = nh2.anyio_util.create_pipe()
    await left.send('alpha')
    assert await right.receive() == 'alpha'
    await right.send('bravo')
    assert await left.receive() == 'bravo'


async def test_create_task_group():
    """Test nh2.anyio_util.create_task_group."""

    async def return_string():
        return 'value'

    started = anyio.Event()
    finished = anyio.Event()

    async def set_event():
        started.set()
        await anyio.sleep(.02)
        finished.set()

    async with nh2.anyio_util.create_task_group() as tg:
        tg.start_soon(set_event)
        await anyio.sleep(.01)
        assert started.is_set()
        assert await tg.start_soon(return_string) == 'value'
        assert not finished.is_set()

    assert finished.is_set()


async def test_create_task_group_exceptions_break_await():
    """Verify `await tg.start_soon(func)` doesn't block if func() throws an exception."""

    started = anyio.Event()

    class MyError(Exception):  # pylint: disable=missing-class-docstring
        pass

    async def raise_exception():
        await anyio.sleep(.01)
        raise MyError

    async def start_tg_raise_exception():
        async with nh2.anyio_util.create_task_group() as tg:
            future = tg.start_soon(raise_exception)
            started.set()
            assert await future == 'not checked'
            return 'not reachable'

    with pytest.raises(Exception) as excinfo:
        assert await start_tg_raise_exception() == 'never run'

    assert started.is_set()
    assert len(excinfo.value.exceptions) == 1
    assert isinstance(excinfo.value.exceptions[0], MyError)
