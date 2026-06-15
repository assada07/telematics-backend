# run.py
import asyncio
import platform
import uvicorn

if __name__ == "__main__":
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()
        )

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False
    )