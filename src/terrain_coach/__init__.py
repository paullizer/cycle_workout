def main() -> None:
    import uvicorn

    uvicorn.run("terrain_coach.app:app", host="127.0.0.1", port=8000)
