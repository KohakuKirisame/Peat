import os

import uvicorn


def main():
    from .runtime_bootstrap import activate

    activate()
    from .app import create_app

    uvicorn.run(
        create_app(),
        host=os.getenv("PEAT_HOST", "127.0.0.1"),
        port=int(os.getenv("PEAT_PORT", "8787")),
        access_log=False,
    )


if __name__ == "__main__":
    main()
