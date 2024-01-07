import asyncio

async def printList(i):
    await asyncio.sleep(1)
    print(i)

async def task1():
    print("Begin task1")
    tasks = [printList(i) for i in range(10)]
    await asyncio.gather(*tasks)
    print("End task1")


async def task2():
    print("Begin task2")
    await asyncio.sleep(4)
    print("End task2")


async def main():
    print("Begin main")
    task1_ = asyncio.create_task(task1())
    task2_ = asyncio.create_task(task2())
    await asyncio.gather(task1_, task2_)
    print("End main")

asyncio.run(main())