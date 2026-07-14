from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="AI Foreign Trade Sales Platform")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"service": "foreign-trade-api", "status": "ok"}

    return app


app = create_app()
