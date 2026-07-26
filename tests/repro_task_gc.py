# -*- coding: utf-8 -*-
"""Reproduce the fire-and-forget create_task GC pitfall.
Mirrors auto_poster/scheduler.py:67 which does NOT hold a reference to the task.
"""
import asyncio, gc

completed = []

async def worker(tag):
    # yield control so the task is pending when GC runs
    await asyncio.sleep(0.05)
    completed.append(tag)

async def scenario(hold_ref):
    refs = set()
    def spawn(tag):
        t = asyncio.create_task(worker(tag))
        if hold_ref:
            refs.add(t)
            t.add_done_callback(refs.discard)
        # else: drop the reference entirely (the bug)
        return t
    # spawn several and immediately drop local refs
    for i in range(20):
        spawn(f"job{i}")
    # force garbage collection while tasks are still pending
    gc.collect()
    await asyncio.sleep(0.2)
    return len(completed)

async def main():
    completed.clear()
    n_bug = await scenario(hold_ref=False)
    print(f"WITHOUT holding reference: {n_bug}/20 tasks completed")
    completed.clear()
    n_fix = await scenario(hold_ref=True)
    print(f"WITH held reference (fix):  {n_fix}/20 tasks completed")

asyncio.run(main())
