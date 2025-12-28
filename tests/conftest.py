import asyncio
import inspect


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test to run in event loop")


def pytest_pyfunc_call(pyfuncitem):
    if "asyncio" not in pyfuncitem.keywords:
        return None

    test_func = pyfuncitem.obj
    if not inspect.iscoroutinefunction(test_func):
        return None

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(test_func(**pyfuncitem.funcargs))
    finally:
        loop.close()
        asyncio.set_event_loop(None)

    return True
